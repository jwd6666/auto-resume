from __future__ import annotations

import json
from typing import AsyncGenerator, Optional

from ...services.resume_provider import (
    stream_response, stream_with_tools, load_settings,
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


_FAKE_CALL_PATTERNS = [
    r"我将(?:调用|使用|执行|运行)\s*(?:read_file|write_file|patch_file)",
    r"让我(?:先|来)?(?:调用|使用|执行|运行)\s*(?:read_file|write_file|patch_file)",
    r"(?:正在|现在|接下来)?(?:调用|使用|执行|运行)\s*(?:read_file|write_file|patch_file)",
    r"(?:read_file|write_file|patch_file)\s*(?:来|去|以)",
    r"我(?:已经|已|将)?(?:读取|写入|修改|保存|替换)了?(?:文件|简历|section)",
]

_FAKE_DONE_PATTERNS = [
    r"(?:已|已经)(?:将|把).{1,30}(?:修改|调整|更改|更新|替换|设置|改为|调成)(?:了|完成|好了|成功)",
    r"我已经.{0,10}(?:修改|调整|更改|更新|替换|设置)(?:了|完成|好了|成功)",
    r"(?:修改|调整|更改|更新|设置).{1,20}(?:完成|成功|好了|已搞定|已处理)",
]

_USER_INTENT_EDIT_PATTERNS = [
    r"(?:改|修改|调整|设置|更改|更新|换|增加|删除|去掉|加大|减小|调大|调小|设成|改为|调成)",
]


def _detect_fake_tool_call(text: str, user_msg: str = "") -> bool:
    import re
    for pat in _FAKE_CALL_PATTERNS:
        if re.search(pat, text):
            return True
    if "===HTML_PATCH===" in text:
        return True
    if user_msg:
        is_edit_intent = any(re.search(pat, user_msg) for pat in _USER_INTENT_EDIT_PATTERNS)
        if is_edit_intent:
            for pat in _FAKE_DONE_PATTERNS:
                if re.search(pat, text):
                    return True
    return False


def _needs_tool_use(text: str) -> bool:
    edit_keywords = ["修改", "调整", "润色", "优化", "改", "换", "删", "添加", "增加",
                     "修改简历", "改简历", "修改样式", "改颜色", "调字号", "改排版",
                     "write_file", "read_file", "patch_file",
                     "写入", "读取", "更新简历", "更新HTML", "替换section", "替换经历", "替换技能"]
    return any(kw in text for kw in edit_keywords)


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
        context_parts.append(f"## 简历文件路径\n\n{file_path}\n（修改简历请使用 patch_file 按 section 局部替换，或使用 read_file 读取指定 section；仅大范围重写时使用 write_file）{sections_hint}")

    context = "\n\n---\n\n".join(context_parts)
    system_with_context = f"{SYSTEM_PROMPT}\n\n---\n\n{context}"

    api_messages = [{"role": m["role"], "content": _build_message_content(m)} for m in messages]

    from ...services.resume_provider import _get_context_input
    settings = load_settings()
    context_limit = _get_context_input(settings)
    token_budget = int(context_limit * 0.8)
    api_messages = _compact_messages(api_messages, token_budget)

    MAX_TOOL_ROUNDS = 10
    _MAX_FAKE_RETRY = 3
    _fake_retry_count = 0
    _context_compacted = False
    _last_round_text = ""
    _override_choice = None
    _pending_read_html = ""

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            round_text = ""
            tool_calls_received = None

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
                    _pending_read_html = ""
                async for event in stream_with_tools(system_with_context, _request_messages, RESUME_TOOLS, tool_choice=choice):
                    etype = event.get("type")
                    if etype == "text":
                        chunk = event["content"]
                        round_text += chunk
                        yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
                    elif etype == "tool_calls":
                        tool_calls_received = event["calls"]
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
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 对话上下文超出模型窗口限制，正在自动压缩早期对话...'}, ensure_ascii=False)}\n\n"
                    api_messages = _compact_messages(api_messages, token_budget // 2)
                    continue
                elif is_context_error and _context_compacted:
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 对话过长，正在进一步裁剪早期消息...'}, ensure_ascii=False)}\n\n"
                    api_messages = _compact_messages(api_messages, token_budget // 3)
                    continue
                elif is_args_error:
                    # DeepSeek 等模型可能因历史 tool_calls arguments 非法 JSON 而报 400
                    # 尝试修复：清理最近 assistant 消息中的 tool_calls arguments
                    yield f"data: {json.dumps({'type': 'error', 'content': '⚠️ 模型返回了非法的 tool_calls 参数，正在自动修复...'}, ensure_ascii=False)}\n\n"
                    _fix_invalid_tool_calls_in_messages(api_messages)
                    continue
                else:
                    yield f"data: {json.dumps({'type': 'error', 'content': f'模型调用失败: {str(stream_err)[:300]}'})}\n\n"
                    break

            _last_round_text = round_text

            if not tool_calls_received:
                is_fake = _detect_fake_tool_call(round_text, user_msg)
                should_force_tool = bool(file_path) and _needs_tool_use(user_msg) and "===HTML_PATCH===" not in user_msg

                if is_fake and _fake_retry_count < _MAX_FAKE_RETRY:
                    _fake_retry_count += 1
                    yield f"data: {json.dumps({'type': 'retry', 'content': '检测到模型未实际调用工具，正在自动重试...'}, ensure_ascii=False)}\n\n"
                    api_messages.append({"role": "assistant", "content": round_text})
                    if _fake_retry_count == 1:
                        api_messages.append({"role": "user", "content": "你刚才用文本描述了工具操作但没有实际发起tool_calls调用。这是违规的。请直接通过tool_calls调用read_file或patch_file工具来修改简历，不要在回复文本中描述工具操作。"})
                    else:
                        api_messages.append({"role": "user", "content": "你仍然没有实际调用工具。你必须通过tool_calls来执行操作，不要用文字说\"已修改\"。请现在就调用工具。"})
                    _override_choice = "required"
                    continue

                if _round == 0 and force_tool and not round_text.strip():
                    api_messages.append({"role": "user", "content": "请调用工具来修改简历文件，不要只用文字回复。"})
                    _override_choice = "required"
                    continue

                if should_force_tool and not is_fake and not round_text.strip():
                    api_messages.append({"role": "user", "content": "请调用工具来修改简历文件，不要只用文字回复。"})
                    _override_choice = "required"
                    continue

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

                result_preview = result[:500] + "..." if len(result) > 500 else result
                yield f"data: {json.dumps({'type': 'tool_result', 'name': call['name'], 'result': result_preview}, ensure_ascii=False)}\n\n"

                is_read = call["name"] == "read_file"
                read_section_id = call["arguments"].get("section_id", "").strip() if isinstance(call.get("arguments"), dict) else ""
                if is_read:
                    _pending_read_html = result
                    section_hint = f"（section: {read_section_id}）" if read_section_id else "（全文）"
                    content_chars = len(result)
                    section_list = _list_sections(result) if not read_section_id else ""
                    context_result = f"【read_file 已读取{section_hint}，共{content_chars}字符。完整 HTML 已临时注入本轮 LLM 请求，不存入对话上下文。下次修改需重新 read_file。】{section_list}"
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
        async for text in stream_response(system, api_messages):
            yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'content': f'模型输出中断: {str(e)[:300]}'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
