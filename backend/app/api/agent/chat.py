from __future__ import annotations

import json
import re
from typing import AsyncGenerator, Optional

from ...services.resume_provider import (
    stream_response, stream_with_tools, load_settings, ConversationDebugLog,
    sanitize_anthropic_history,
)
from ...services.resume_workspace import (
    ensure_resume_file, read_resume_file, write_resume_file, resume_file_path,
)
from ...services.local_edit import snapshot
from .prompts import SYSTEM_PROMPT, INTERVIEW_SIM_SYSTEM
from .tools import RESUME_TOOLS, execute_tool, reset_full_read_state, _list_sections


def _estimate_tokens(messages: list) -> int:
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    total_chars += len(part)
                elif isinstance(part, dict):
                    text = part.get("text", "") or json.dumps(part, ensure_ascii=False)
                    total_chars += len(text)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total_chars += len(json.dumps(tc, ensure_ascii=False))
    return total_chars // 2


def _group_tool_calls(messages: list) -> list:
    """将 messages 按 tool_calls 组切分为不可拆分的原子组。

    每个组是一个 list：
    - 普通消息 → [msg]（单元素组）
    - assistant(tool_calls) + 后续紧跟的 tool 消息 → [assistant_msg, tool_msg1, ...]
    """
    groups: list = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            group = [msg]
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                group.append(messages[i])
                i += 1
            groups.append(group)
        else:
            groups.append([msg])
            i += 1
    return groups


def _compact_messages(messages: list, max_tokens: int) -> list:
    if not messages or _estimate_tokens(messages) <= max_tokens:
        return messages

    system_msgs = []
    conversation_msgs = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            conversation_msgs.append(msg)

    if not conversation_msgs:
        return messages

    groups = _group_tool_calls(conversation_msgs)

    keep_min_groups = 4
    if len(groups) > keep_min_groups + 1:
        older_groups = groups[:-keep_min_groups]
        recent_groups = groups[-keep_min_groups:]

        older_summary_parts = []
        for grp in older_groups:
            for msg in grp:
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    older_summary_parts.append(content[:150])
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            older_summary_parts.append(part.get("text", "")[:150])

        summary_text = "；".join(older_summary_parts[:6])
        if len(summary_text) > 500:
            summary_text = summary_text[:500] + "..."

        summary_msg = {
            "role": "user",
            "content": f"[历史对话摘要] {summary_text}",
        }
        assistant_ack = {
            "role": "assistant",
            "content": "（已了解之前的对话背景，继续当前对话）",
        }

        result = system_msgs + [summary_msg, assistant_ack] + [
            m for g in recent_groups for m in g
        ]
    else:
        result = list(messages)

    if _estimate_tokens(result) <= max_tokens:
        return result

    non_system = [m for m in result if m.get("role") != "system"]
    sys_part = [m for m in result if m.get("role") == "system"]

    non_sys_groups = _group_tool_calls(non_system)

    while len(non_sys_groups) > 1 and _estimate_tokens(sys_part + [m for g in non_sys_groups for m in g]) > max_tokens:
        non_sys_groups.pop(0)

    return sys_part + [m for g in non_sys_groups for m in g]


def _build_message_content(msg: dict):
    role = msg.get("role", "")
    text = msg.get("content", "")
    images = msg.get("images") or []

    if images and role == "user":
        content_parts = []
        for img in images:
            content_parts.append({"type": "image_url", "image_url": {"url": img}})
        if text:
            content_parts.append({"type": "text", "text": text})
        return content_parts
    return text


class _ThinkSplitter:
    """把模型流式输出拆分为「思考」与「正文」，兼容两类思考格式：

    1. 显式标签：<think>...</think>
    2. 裸思考：回复开头直接是思考内容，以 </think> 结束（部分 DeepSeek 兼容端点）

    provider 层的 reasoning_content 字段不经过本类（直接作为 reasoning 事件透传）。

    开头未判定阶段先按思考输出（前端收缩展示）；若超过上限仍未见任何标签，
    通过 retract_to_text 事件把已输出的内容转回正文，避免无思考模型的内容被
    一直折叠。feed/flush 返回事件列表：("reasoning", s) / ("text", s) /
    ("retract_to_text", s)。
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"
    _KEEP = 7  # 标签长度-1，防止标签被 chunk 边界切断
    _START_LIMIT = 3000  # 开头未判定阶段的暂存上限

    def __init__(self) -> None:
        self._mode = "start"  # start: 未判定 | thinking | normal
        self._buf = ""
        self._start_emitted = ""  # start 阶段已按思考输出的内容

    def _emit_keep_tail(self, kind: str):
        """输出 buf 中除尾部保留区外的内容，返回事件或 None。"""
        if len(self._buf) > self._KEEP:
            emit, self._buf = self._buf[:-self._KEEP], self._buf[-self._KEEP:]
            return (kind, emit)
        return None

    def feed(self, chunk: str) -> list:
        self._buf += chunk
        events: list = []
        while self._buf:
            if self._mode == "start":
                open_at = self._buf.find(self._OPEN)
                close_at = self._buf.find(self._CLOSE)
                if close_at != -1 and (open_at == -1 or close_at < open_at):
                    # 裸思考结束：close 之前的内容全部是思考
                    if self._buf[:close_at]:
                        events.append(("reasoning", self._buf[:close_at]))
                    self._buf = self._buf[close_at + len(self._CLOSE):]
                    self._mode = "normal"
                elif open_at != -1:
                    # 显式思考标签：标签之前的内容（含已输出的）转回正文
                    head = self._start_emitted + self._buf[:open_at]
                    if head:
                        events.append(("retract_to_text", head))
                    self._buf = self._buf[open_at + len(self._OPEN):]
                    self._mode = "thinking"
                elif len(self._start_emitted) + len(self._buf) > self._START_LIMIT:
                    # 累计输出超过上限仍无标签：判定为无思考
                    events.append(("retract_to_text", self._start_emitted + self._buf))
                    self._buf = ""
                    self._start_emitted = ""
                    self._mode = "normal"
                else:
                    ev = self._emit_keep_tail("reasoning")
                    if ev:
                        events.append(ev)
                        self._start_emitted += ev[1]
                    break
            elif self._mode == "thinking":
                close_at = self._buf.find(self._CLOSE)
                if close_at != -1:
                    if self._buf[:close_at]:
                        events.append(("reasoning", self._buf[:close_at]))
                    self._buf = self._buf[close_at + len(self._CLOSE):]
                    self._mode = "normal"
                else:
                    ev = self._emit_keep_tail("reasoning")
                    if ev:
                        events.append(ev)
                    break
            else:  # normal
                open_at = self._buf.find(self._OPEN)
                if open_at != -1:
                    text_part = self._buf[:open_at].replace(self._CLOSE, "")
                    if text_part:
                        events.append(("text", text_part))
                    self._buf = self._buf[open_at + len(self._OPEN):]
                    self._mode = "thinking"
                else:
                    # 剔除裸残留的闭合标签
                    self._buf = self._buf.replace(self._CLOSE, "")
                    ev = self._emit_keep_tail("text")
                    if ev:
                        events.append(ev)
                    break
        return events

    def flush(self) -> list:
        events: list = []
        if self._mode == "thinking":
            # think 未闭合：全部按思考处理
            if self._buf:
                events.append(("reasoning", self._buf))
        elif self._mode == "start":
            # 直到流结束都未出现标签：开头内容按正文处理
            head = self._start_emitted + self._buf
            if head:
                events.append(("retract_to_text", head))
        else:
            if self._buf:
                events.append(("text", self._buf))
        self._buf = ""
        self._start_emitted = ""
        return events


def _needs_tool_use(text: str) -> bool:
    edit_keywords = ["修改", "调整", "润色", "优化", "改", "换", "删", "添加", "增加",
                     "修改简历", "改简历", "修改样式", "改颜色", "调字号", "改排版",
                     "write_file", "read_file", "patch_file",
                     "写入", "读取", "更新简历", "更新HTML", "替换section", "替换经历", "替换技能"]
    return any(kw in text for kw in edit_keywords)


# 正文/思考内容里的伪工具调用形态：痕迹行模仿、裸函数调用标签、原生特殊标记泄漏
_FAKE_TOOL_CALL_RE = re.compile(
    r"[\U0001F527\u2705]\s*(?:调用|执行|完成)"
    r"|<tool_call\b|<invoke\b|function_calls\b"
    # 模型把工具名当 XML 标签写进正文（如 <read_file>…</read_file>、<replace_in_file>…）
    r"|</?\s*(?:read_file|patch_file|write_file|replace_in_file|create_file|update_file|tool_use|function)\b"
    r"|｜[^｜\n]{0,24}｜\s*(?:parameter|function|invoke)"
    r"|\b(?:read_file|patch_file|write_file)\b[^\n]{0,24}(?:调用成功|执行成功|已完成|已读取|已替换|已写入|修改成功)"
    r"|(?:已|现)将?通过\s*(?:read_file|patch_file|write_file)"
    r"|\n[^\n]{0,40}(?:修改成功|替换成功|写入成功)\n"
)


def _detect_fake_tool_call(msg: dict) -> bool:
    """检测模型未发起真实 tool_calls、却在正文或 thinking 里输出伪调用痕迹/自称修改成功。

    DeepSeek 等模型会逐字模仿历史里的 🔧 调用/✅ 完成痕迹行，在文本里“演戏”调用
    read_file/patch_file 并自称完成，实际文件未被修改；命中时由调用方塞纠正消息强制重试。
    """
    content = msg.get("content")
    texts = [content] if isinstance(content, str) else []
    reasoning = msg.get("reasoning")
    if isinstance(reasoning, str):
        texts.append(reasoning)
    return any(_FAKE_TOOL_CALL_RE.search(t) for t in texts)


# 部分思考模型（DeepSeek 等）会把内部推理直接吐进正文而不用任何标签包裹，
# _ThinkSplitter 无法识别导致独白刷屏；按第一人称决策/自我怀疑句式特征拆入思考通道
_DELIB_RE = re.compile(
    r"我(?:先|来|将|要|得|应|需要|必须|还是|不能|不该|理解为|意识到|注意到|发现|记得|记不清|不确定|获取到|定位到)"
    r"|我(?:看到|读到|读取|查看|确认|检查|搜索)"
    r"|(?:下面|接下来|随后)?让我(?:先|来|确认|读取|查看|重新|针对)?"
    r"|先确认|再确认|重新读取|重新查看|下一(?:步|轮)"
    r"|在(?:本轮|上一轮|下一轮)"
    r"|\bI(?:'ll| will| need to| must| should| have to| think| was| can)\b[^\n]{0,40}?\b(?:patch|read|confirm|check|inspect|the text|the original|old_str|old string|the eval)\b",
    re.IGNORECASE,
)
_SENTENCE_END = "。！？;；\n"
# 独白刷屏的门槛：长度与命中次数双重阈值，避免误伤含一两个“让我/我先”的正常简短回复
_DELIB_MIN_CHARS = 600
_DELIB_MIN_HITS = 3


def _split_deliberation(raw: str, force: bool = False) -> tuple[str, str]:
    """把混入正文的内部独白拆到思考通道，返回（干净正文, 独白片段）。

    仅当正文足够长且独白特征命中次数达阈值时才拆：从第一个命中句首拆分，
    之前保留为用户可见正文，之后视为模型内部推演。未达阈值时正文原样、独白为空。
    force=True（流尾定稿）时降低长度与命中门槛，仅防段落级缓冲各自未达门槛而漏判。
    """
    if not raw:
        return raw, ""
    min_chars = _DELIB_MIN_CHARS // 2 if force else _DELIB_MIN_CHARS
    if len(raw) < min_chars:
        return raw, ""
    hits = list(_DELIB_RE.finditer(raw))
    if len(hits) < (2 if force else _DELIB_MIN_HITS):
        return raw, ""
    start = hits[0].start()
    # 回退到该句句首（上一个句子结束符之后）
    cut = start
    for i in range(start - 1, -1, -1):
        if raw[i] in _SENTENCE_END:
            cut = i + 1
            break
    # 独白应从正文句后开始；若命中点前无句子边界则整段从开头视为独白
    clean = raw[:cut].rstrip()
    delib = raw[cut:].strip()
    return (clean, delib) if delib else (raw, "")


def _fix_invalid_tool_calls_in_messages(messages: list) -> int:
    """修复 messages 中 assistant tool_calls 的非法 JSON arguments。

    DeepSeek 等模型偶尔会生成 arguments 不是合法 JSON 的 tool_calls，
    导致后续请求被 API 拒绝（400 - arguments must be valid JSON）。

    策略：遍历 assistant 消息的 tool_calls，将非法 arguments 替换为
    修复后的合法 JSON（基于 arguments dict 重新序列化）或 fallback 到 "{}"。

    返回修复数量。
    """
    fixed = 0
    for msg in messages:
        if msg.get("role") != "assistant" or "tool_calls" not in msg:
            continue
        for tc in msg["tool_calls"]:
            if "function" not in tc:
                continue
            args_str = tc["function"].get("arguments", "")
            if not args_str:
                tc["function"]["arguments"] = "{}"
                continue
            try:
                json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                repaired = None
                try:
                    from ...core.json_utils import repair_json_args
                    repaired = repair_json_args(args_str)
                except Exception:
                    pass
                if repaired and isinstance(repaired, dict):
                    tc["function"]["arguments"] = json.dumps(repaired, ensure_ascii=False)
                else:
                    tc["function"]["arguments"] = "{}"
                fixed += 1
    return fixed


async def generate(
    job_content: str,
    resume_content: str,
    messages: list,
    user_background: str = None,
    resume_structured: str = None,
    resume_rendered_html: str = None,
    resume_id: int = None,
) -> AsyncGenerator[str, None]:
    def _last_user_message() -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                return c if isinstance(c, str) else ""
        return ""

    file_path = ensure_resume_file(resume_id, resume_rendered_html) if resume_id else None
    # 新一轮对话：重置"已读完整文件"标记 + 清空暂存区，写入前必须重新读全文
    await reset_full_read_state(resume_id)

    # 对话开始时自动创建快照备份，确保可回滚
    if resume_id and file_path and file_path.exists():
        snapshot.make_snapshot(file_path, resume_id=resume_id)
        snapshot.clean_old_snapshots(resume_id, max_age_days=7)
    if resume_id:
        yield f"data: {json.dumps({'type': 'snapshot_depth', 'depth': snapshot.stack_depth(resume_id)})}\n\n"

    context_parts = [f"## 目标岗位信息\n\n{job_content}"]
    if user_background:
        context_parts.append(f"## 用户补充的个人经历\n\n{user_background}")

    if file_path:
        sections_hint = ""
        if resume_rendered_html:
            sections_hint = "\n\n可用 section 列表：\n" + _list_sections(resume_rendered_html)
        context_parts.append(f"## 简历文件路径\n\n{file_path}\n（需要修改简历时：先用 read_file 读取全文，再用 patch_file 局部替换；仅大范围重写时使用 write_file）{sections_hint}")

    context = "\n\n---\n\n".join(context_parts)
    system_with_context = f"{SYSTEM_PROMPT}\n\n---\n\n{context}"

    api_messages = sanitize_anthropic_history(
        [{"role": m["role"], "content": _build_message_content(m)} for m in messages]
    )

    from ...services.resume_provider import _get_context_input
    settings = load_settings()
    context_limit = _get_context_input(settings)
    token_budget = int(context_limit * 0.8)
    api_messages = _compact_messages(api_messages, token_budget)

    MAX_TOOL_ROUNDS = 10
    _context_compacted = False
    _last_round_text = ""
    _override_choice = None
    _pending_read_html = ""
    _fake_retry = 0
    _empty_retry = 0      # 模型既无 tool_calls 也无正文的强制重试次数（防 hint 堆积空转）
    _had_tool_calls = False  # 本轮对话是否已成功发起过 tool_calls

    # 一次对话一个 debug 日志文件：记录每轮请求(tools/messages)、
    # LLM 返回(finish_reason/content/tool_calls)、工具执行结果与最终回复
    debug_log = ConversationDebugLog()

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            round_text = ""
            round_reasoning = ""
            tool_calls_received = None
            _think = _ThinkSplitter()
            _delib_note = False
            _pend_body = ""     # 正文待决缓冲（text 事件）
            _pend_retracted = ""  # 被 _ThinkSplitter 暂存为思考、判定为正文的部分（尚未转回前端）

            def _flush_pending(final: bool = False) -> list:
                """把待决缓冲过独白检测后发出：干净内容留在正文通道，
                泄漏的内部推流转入思考通道（text_to_reasoning），避免刷屏式展示。
                final=流尾/工具轮定稿：此时降低长度门槛强制拆分，防段落级缓冲各自未达门槛而漏判。"""
                nonlocal round_text, round_reasoning, _delib_note, _pend_body, _pend_retracted
                merged = _pend_retracted + _pend_body
                had_retracted = bool(_pend_retracted)
                if not merged.strip():
                    _pend_body = _pend_retracted = ""
                    return []
                if _delib_note:
                    clean, delib = "", merged  # 本轮已判定：后续缓冲内容全部转思考
                else:
                    if final and len(merged) >= _DELIB_MIN_CHARS // 2:
                        clean, delib = _split_deliberation(merged, force=True)
                    else:
                        clean, delib = _split_deliberation(merged)
                if delib:
                    _delib_note = True
                _pend_body = _pend_retracted = ""
                round_reasoning = f"{round_reasoning}\n\n{delib}".strip() if delib else round_reasoning
                round_text += clean
                out: list = []
                # 可见正文：经 _ThinkSplitter 思考通道暂存过的用 retract 转回，纯正文通道的新内容用 text 推送
                if clean:
                    if had_retracted:
                        out.append(f"data: {json.dumps({'type': 'reasoning_to_text', 'content': clean}, ensure_ascii=False)}\n\n")
                    else:
                        out.append(f"data: {json.dumps({'type': 'text', 'content': clean}, ensure_ascii=False)}\n\n")
                # 独白部分：统一用 text_to_reasoning，前端将对应内容从正文移除并追加到 reasoning
                if delib:
                    out.append(f"data: {json.dumps({'type': 'text_to_reasoning', 'content': delib}, ensure_ascii=False)}\n\n")
                return out

            def _split_sse(kind: str, payload: str) -> list:
                """_ThinkSplitter 事件转 SSE；正文/retract 先进待决缓冲，由段落或尾幕触发拆分。"""
                nonlocal _pend_body, _pend_retracted
                if kind == "reasoning":
                    return [f"data: {json.dumps({'type': 'reasoning', 'content': payload}, ensure_ascii=False)}\n\n"]
                if kind == "retract_to_text":
                    _pend_retracted += payload
                else:
                    _pend_body += payload
                if "\n\n" in _pend_body or len(_pend_body) + len(_pend_retracted) > 600:
                    return _flush_pending()
                return []

            user_msg = _last_user_message()
            force_tool = bool(file_path) and _round == 0 and _needs_tool_use(user_msg) and "===HTML_PATCH===" not in user_msg
            if _override_choice is not None:
                choice = _override_choice
                _override_choice = None
            else:
                choice = "required" if force_tool else "auto"

            try:
                _request_messages = list(api_messages)
                if _pending_read_html:
                    _request_messages.append({"role": "user", "content": f"以下是 read_file 读取的简历 HTML 完整源码（仅本次请求临时传入，不存入对话历史）：\n\n{_pending_read_html}"})
                    debug_log.log_note("本轮请求临时注入 read_file 读取的完整 HTML（仅本次请求、不存入对话历史；全文见上方 [tool] 结果）")
                    _pending_read_html = ""
                async for event in stream_with_tools(system_with_context, _request_messages, RESUME_TOOLS, tool_choice=choice, debug_log=debug_log):
                    etype = event.get("type")
                    if etype == "text":
                        for ev in _think.feed(event["content"]):
                            for sse in _split_sse(*ev):
                                yield sse
                    elif etype == "reasoning":
                        round_reasoning += event["content"]
                        yield f"data: {json.dumps({'type': 'reasoning', 'content': event['content']}, ensure_ascii=False)}\n\n"
                    elif etype == "tool_calls":
                        tool_calls_received = event["calls"]
                        # 真实工具轮：本轮正文就是行动说明，定稿不再做独白拆分
                        for sse in _flush_pending(final=True):
                            yield sse
                # 流结束：冲出缓冲区残留内容，再做正文/独白拆分（泄漏进思维链的兑底）
                for ev in _think.flush():
                    for sse in _split_sse(*ev):
                        yield sse
                for sse in _flush_pending(final=True):
                    yield sse
                if _delib_note:
                    debug_log.log_note("本轮正文含模型内部独白，已拆入思考通道展示（text_to_reasoning）")
            except Exception as stream_err:
                err_msg = str(stream_err).lower()
                is_context_error = any(kw in err_msg for kw in [
                    "context_length", "context window", "maximum context", "token limit",
                    "too many tokens", "reduce the length", "input is too long",
                    "请求长度超", "上下文长度", "max_tokens",
                ])
                is_args_error = "arguments must be valid json" in err_msg or "invalid json" in err_msg
                if is_context_error and not _context_compacted:
                    _context_compacted = True
                    debug_log.log_note("上下文超出模型窗口限制，已自动压缩早期对话后重试")
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 对话上下文超出模型窗口限制，正在自动压缩早期对话...'}, ensure_ascii=False)}\n\n"
                    api_messages = _compact_messages(api_messages, token_budget // 2)
                    continue
                elif is_context_error and _context_compacted:
                    debug_log.log_note("对话过长，已进一步裁剪早期消息后重试")
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 对话过长，正在进一步裁剪早期消息...'}, ensure_ascii=False)}\n\n"
                    api_messages = _compact_messages(api_messages, token_budget // 3)
                    continue
                elif is_args_error:
                    # DeepSeek 等模型可能因历史 tool_calls arguments 非法 JSON 而报 400
                    # 尝试修复：清理最近 assistant 消息中的 tool_calls arguments
                    debug_log.log_note("历史 tool_calls 参数为非法 JSON 导致 API 拒绝，已自动修复后重试")
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 模型返回了非法的 tool_calls 参数，正在自动修复...'}, ensure_ascii=False)}\n\n"
                    _fix_invalid_tool_calls_in_messages(api_messages)
                    continue
                else:
                    debug_log.log_note(f"模型调用失败，结束本轮: {str(stream_err)[:300]}")
                    yield f"data: {json.dumps({'type': 'error', 'content': f'模型调用失败: {str(stream_err)[:300]}'})}\n\n"
                    break

            _last_round_text = round_text
            if tool_calls_received:
                _had_tool_calls = True

            if not tool_calls_received:
                should_force_tool = bool(file_path) and _needs_tool_use(user_msg) and "===HTML_PATCH===" not in user_msg

                # 模型未发起 tool_calls 且无正文：分场景最多重试 2 次。
                # 反复插入的提示会堆积在历史里，反而诱导模型无休止地继续调用工具
                if should_force_tool and not round_text.strip():
                    if _empty_retry >= 2:
                        # 已重试 2 次仍无正文无工具调用：放弃，避免空转烧 token
                        debug_log.log_note(f"空回复重试 {_empty_retry} 次无果，结束本轮")
                        yield f"data: {json.dumps({'type': 'warning', 'content': '⚠️ 模型未能完成修改（可能不支持工具调用或输出异常），请重试或换用支持工具调用的模型。'}, ensure_ascii=False)}\n\n"
                        break
                    _empty_retry += 1
                    if not _had_tool_calls:
                        # 从未成功调用过工具：强制工具调用（第 2 次换措辞给模型文字出口）
                        _hint = (
                            "请调用工具来修改简历文件，不要只用文字回复。"
                            if _empty_retry == 1
                            else "请通过 tool_calls 真实调用 read_file/patch_file 修改简历；若确实无法调用工具，请用文字说明原因。"
                        )
                        _override_choice = "required"
                    else:
                        # 已调用过工具后的空正文：多为收尾总结被拆入思考通道或提前收束，
                        # 中性续写一次，不强制工具
                        _hint = "请继续：基于工具结果完成剩余修改，或输出本次修改的总结。"
                        _override_choice = None
                    api_messages.append({"role": "user", "content": _hint})
                    debug_log.log_message("user", _hint, note=f"空回复重试#{_empty_retry}")
                    continue

                # 伪调用检测不依赖用户消息关键词：本轮输出本身出现工具调用痕迹/自称改完，
                # 即证明模型意图改文件却没真实发起 tool_calls（“空格太大了”这类无关键词的隐含指令也能兜住）
                if (bool(file_path) and "===HTML_PATCH===" not in user_msg
                        and _fake_retry < 3 and _detect_fake_tool_call(
                            {"content": round_text, "reasoning": round_reasoning}
                        )):
                    # 模型在正文/thinking 里模仿 🔧/✅ 痕迹行、写 <read_file> 等工具名标签或自称修改成功，
                    # 但未发起真实 tool_calls；本轮文本不回放进历史，塞纠正消息强制重试
                    _fake_retry += 1
                    _hint = ("检测到你上一条回复只在文本里描述了工具调用，并未真实执行任何工具，"
                             "文件没有被修改。禁止在正文和思考内容中输出 🔧/✅ 痕迹、"
                             "<read_file>/<patch_file>/<replace_in_file> 等工具名标签或自称已完成，"
                             "请直接通过 API 的 tool_calls 结构体真实发起 read_file/patch_file 调用。")
                    api_messages.append({"role": "user", "content": _hint})
                    debug_log.log_message("user", _hint, note=f"伪调用纠正重试#{_fake_retry}")
                    _override_choice = "required"
                    continue

                if _fake_retry:
                    debug_log.log_note(f"伪工具调用纠正 {_fake_retry} 次后仍未发出真实 tool_calls，结束本轮")
                    yield f"data: {json.dumps({'type': 'warning', 'content': '⚠️ 模型多次声称已修改但未真实执行工具，本次修改未生效，请重试或换个表述。'}, ensure_ascii=False)}\n\n"

                # 本轮完全无输出（无正文无思考无工具）：给用户可见提示，避免静默结束
                if not round_text.strip() and not round_reasoning.strip():
                    debug_log.log_note("本轮模型无任何输出，结束")
                    yield f"data: {json.dumps({'type': 'warning', 'content': '⚠️ 模型未返回有效内容，请重试或换个表述。'}, ensure_ascii=False)}\n\n"

                break

            assistant_msg: dict = {"role": "assistant", "content": round_text or ""}
            _MAX_ARG_IN_CONTEXT = 1500
            trimmed_calls = []
            for c in tool_calls_received:
                raw_args = c.get("raw_arguments") or json.dumps(c["arguments"], ensure_ascii=False)
                call_name = c["name"]

                # 确保 arguments 是合法 JSON（DeepSeek 等模型会校验）
                try:
                    json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    if isinstance(c.get("arguments"), dict):
                        raw_args = json.dumps(c["arguments"], ensure_ascii=False)
                    else:
                        raw_args = "{}"

                if call_name in ("write_file", "patch_file") and len(raw_args) > _MAX_ARG_IN_CONTEXT:
                    try:
                        parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        if isinstance(parsed, dict):
                            for _trunc_key in ("content", "old_str", "new_str"):
                                if _trunc_key in parsed and len(str(parsed[_trunc_key])) > _MAX_ARG_IN_CONTEXT:
                                    parsed[_trunc_key] = str(parsed[_trunc_key])[:_MAX_ARG_IN_CONTEXT] + f"...（共{len(str(c['arguments'].get(_trunc_key, '')))}字符，已截断）"
                            raw_args = json.dumps(parsed, ensure_ascii=False)
                    except (json.JSONDecodeError, AttributeError):
                        pass
                trimmed_calls.append({
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": call_name,
                        "arguments": raw_args,
                    },
                })
            assistant_msg["tool_calls"] = trimmed_calls
            api_messages.append(assistant_msg)

            for call in tool_calls_received:
                arg_preview = call["arguments"].copy() if isinstance(call["arguments"], dict) else {}
                for _arg_key in ("content", "new_html", "old_str", "new_str"):
                    if _arg_key in arg_preview and len(str(arg_preview[_arg_key])) > 200:
                        arg_preview[_arg_key] = str(arg_preview[_arg_key])[:200] + "..."
                yield f"data: {json.dumps({'type': 'tool_call', 'name': call['name'], 'arguments': arg_preview}, ensure_ascii=False)}\n\n"

                result = await execute_tool(call["name"], call["arguments"], resume_id)
                debug_log.log_tool_result(debug_log.current_round, name=call["name"], arguments=call["arguments"], result=result)

                result_preview = result[:500] + "..." if len(result) > 500 else result
                yield f"data: {json.dumps({'type': 'tool_result', 'name': call['name'], 'result': result_preview}, ensure_ascii=False)}\n\n"

                is_read = call["name"] == "read_file"
                if is_read:
                    _pending_read_html = result
                    content_chars = len(result)
                    section_list = _list_sections(result)
                    context_result = f"【read_file 已读取全文，共{content_chars}字符。完整 HTML 已临时注入本轮 LLM 请求，不存入对话上下文。内容未截断，无需重读；下次修改前仍需重新 read_file。】{section_list}"
                else:
                    MAX_TOOL_RESULT_IN_CONTEXT = 1500
                    if len(result) > MAX_TOOL_RESULT_IN_CONTEXT:
                        context_result = result[:MAX_TOOL_RESULT_IN_CONTEXT] + f"\n...（共{len(result)}字符，完整内容已写入文件，不再重复展示）"
                    else:
                        context_result = result
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": context_result,
                })

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
        return
    finally:
        # 无论正常结束、异常还是客户端提前断开，都落盘最终回复文本
        debug_log.finish(_last_round_text)

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def stream_sim(
    job_content: str,
    resume_content: str,
    messages: list,
    user_background: Optional[str],
    questionnaire_markdown: Optional[str] = None,
    job_id: Optional[int] = None,
    resume_id: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    context_parts = [f"## 目标岗位 JD\n\n{job_content}"]
    if resume_content:
        context_parts.append(f"## 候选人简历\n\n{resume_content}")
    if user_background:
        context_parts.append(f"## 候选人补充经历\n\n{user_background}")
    if questionnaire_markdown and questionnaire_markdown.strip():
        context_parts.append(questionnaire_markdown.strip())

    context = "\n\n---\n\n".join(context_parts)
    system = f"{INTERVIEW_SIM_SYSTEM}\n\n---\n\n{context}"

    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    try:
        async for text in stream_response(system, api_messages, source="interview"):
            yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
