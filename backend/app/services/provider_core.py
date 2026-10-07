"""公共 API 调度层：连接测试、流式/非流式调用、工具调用、debug 日志、SSE 心跳。"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Tuple

from fastapi import HTTPException

from .provider_settings import (
    CUSTOM_PROVIDER_KEY, CLOUD_PROVIDER_PREFIX, DEBUG_LOG_ENABLED,
    load_settings, get_api_key, get_custom_model,
    _resolve_base_url, _resolve_current_provider,
    _get_context_output, is_cloud_provider, get_cloud_template_id,
)
from .provider_openai import _stream_openai_compat, stream_cloud_chat
from ..core.json_utils import repair_json_args
from ..core.config import CLOUD_SERVER_URL

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

_DEBUG_LOG_DIR = Path(__file__).resolve().parents[2] / "debug_logs"

# 前端回显的工具调用痕迹行（🔧 调用 xxx / ✅ xxx 完成），模型会逐字模仿它们伪造工具轮次，
# 回放历史时必须剥除，避免污染上下文导致伪调用
_PSEUDO_TOOL_TRACE_RE = re.compile(
    r"^[ \t\-*·（\[\{]*(?:[\U0001F300-\U0001FAFF☀-➿][ \t\u3000]*)?(?:调用|执行|正在调用)[ \t\u3000]*(?:read_file|patch_file|write_file)\b[^\n]*"
    r"|^[ \t\-*·（\[\{]*(?:[\U0001F300-\U0001FAFF☀-➿][ \t\u3000]*)?(?:read_file|patch_file|write_file)[ \t\u3000]*(?:完成|调用成功|执行成功|已完成|已读取|已替换|已写入|修改成功)[^\n]*"
    r"|^[ \t\-*·（\[\{]*(?:[\U0001F300-\U0001FAFF☀-➿][ \t\u3000]*)?(?:read_file|patch_file|write_file)[ \t\u3000]*[^\n]{0,80}\btool_use_id\b[^\n]*",
    re.MULTILINE,
)
# DeepSeek 等兼容端点泄漏到正文里的原生函数调用特殊标记（如 <|DSML|...>、＜｜xx｜＞）
_SPECIAL_TOKEN_LEAK_RE = re.compile(r"[<＜｜|][a-zA-Z0-9_｜|<]{0,24}(?:DSML|tool_call|parameter)[^>＞\n]{0,80}[>＞]")


def _blocks_to_text(content) -> str:
    """Anthropic content blocks / 纯文本 → 拼接后的纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", "") or "")
        return "\n".join(p for p in parts if p)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def _strip_pseudo_tool_text(text: str) -> str:
    """剥除文本里的伪调用痕迹行与泄漏的原生特殊标记。"""
    return _SPECIAL_TOKEN_LEAK_RE.sub("", _PSEUDO_TOOL_TRACE_RE.sub("", text)).strip()


def sanitize_anthropic_history(messages: list) -> list:
    """归一化回放的对话历史，防模型模仿伪工具调用痕迹。

    DeepSeek 等 OpenAI 风格 provider 不识别 Anthropic 块，一旦回放含 tool_use/tool_result
    的历史，模型会模仿其文本形态输出伪工具调用（参数里甚至夹带 ｜DSML｜ 特殊标记）。规则：
    - assistant + tool_use 块 → OpenAI 的 tool_calls 结构（后续 tool 结果消息保持紧随）
    - user + tool_result 块 → 按 tool_use_id 配对转成 role=tool 消息
    - 所有 user/assistant 文本统一剥除 🔧/✅ 伪调用痕迹行与泄漏的原生特殊标记
      （OpenAI 风格历史同样适用，不依赖 Anthropic 块存在）
    - 无需任何修改时原样返回同一列表（零开销透传）
    """
    def _has_tool_blocks(m: dict) -> bool:
        content = m.get("content")
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in content
        )

    def _needs_strip(m: dict) -> bool:
        return (
            m.get("role") in ("assistant", "user")
            and isinstance(m.get("content"), str)
            and bool(_PSEUDO_TOOL_TRACE_RE.search(m["content"]) or _SPECIAL_TOKEN_LEAK_RE.search(m["content"]))
        )

    if not messages or not (any(_has_tool_blocks(m) for m in messages) or any(_needs_strip(m) for m in messages)):
        return messages

    out: list = []
    emitted_tool_ids: set = set()
    group_end = 0  # 最近一段 assistant(tool_calls)+tool... 块的插入尾部位置
    for m in messages:
        role = m.get("role", "")
        content = m.get("content")
        if not _has_tool_blocks(m):
            # 已是 OpenAI 形态：assistant tool_calls / role=tool 组内顺序合法，原样透传；
            # 普通文本剥除伪调用痕迹后透传
            if _needs_strip(m):
                out.append({**m, "content": _strip_pseudo_tool_text(content)})
            else:
                out.append(m)
            continue
        if role == "assistant":
            text = _strip_pseudo_tool_text(_blocks_to_text(content))
            tc_list = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    try:
                        args_str = json.dumps(block.get("input") or {}, ensure_ascii=False)
                    except Exception:
                        args_str = "{}"
                    tc_list.append({
                        "id": block.get("id") or f"call_hist_{len(out)}_{len(tc_list)}",
                        "type": "function",
                        "function": {"name": block.get("name", ""), "arguments": args_str},
                    })
            nm = dict(m)
            nm.pop("content", None)
            if text:
                nm["content"] = text
            if tc_list:
                nm["tool_calls"] = (m.get("tool_calls") or []) + tc_list
            out.append(nm)
            group_end = len(out)
        elif role == "user":
            # tool_result 块 → role=tool 消息；必须插回其对应 assistant tool_calls 之后，
            # 避免打乱 OpenAI 的 assistant(tool_calls) → tool... 分组而触发 400
            pos = group_end
            rest_texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    if not tid or tid in emitted_tool_ids:
                        continue
                    rc = block.get("content", "")
                    if isinstance(rc, list):
                        rc = _blocks_to_text(rc)
                    out.insert(pos, {"role": "tool", "tool_call_id": tid, "content": str(rc)})
                    emitted_tool_ids.add(tid)
                    pos += 1
                    group_end = max(group_end, pos)
                elif isinstance(block, dict) and block.get("type") == "text":
                    rest_texts.append(block.get("text", "") or "")
                elif isinstance(block, str):
                    rest_texts.append(block)
            if rest_texts:
                out.append({**m, "content": _strip_pseudo_tool_text("\n".join(t for t in rest_texts if t))})

    # 兜底：assistant 带 tool_calls 但结果缺失/游离的 tool 消息会导致部分 provider 400，
    # 按 tool_call_id 配对重排，未配对的 tool_calls 补占位结果、游离 tool 消息丢弃
    final: list = []
    i = 0
    pending_ids: list = []
    while i < len(out):
        m = out[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            final.append(m)
            pending_ids = [tc.get("id") for tc in m["tool_calls"]]
            i += 1
            tool_map: dict = {}
            while i < len(out) and out[i].get("role") == "tool":
                tool_map[out[i].get("tool_call_id", "")] = out[i].get("content", "")
                i += 1
            for tid in pending_ids:
                if tid in tool_map:
                    final.append({"role": "tool", "tool_call_id": tid, "content": tool_map[tid]})
                else:
                    final.append({"role": "tool", "tool_call_id": tid, "content": "（历史结果缺失，内容未截断，无需重读）"})
            pending_ids = []
            continue
        if m.get("role") == "tool":
            i += 1  # 游离 tool 消息
            continue
        final.append(m)
        i += 1
    return final


class ConversationDebugLog:
    """一次对话一个 debug 日志文件（受 DEBUG_LOG_ENABLED 开关控制）。

    人类可读的文本格式，按时间顺序记录完整工具调用链路：

      ────────── 组装请求#1 (tool_choice=auto) ──────────
      [system] ...
      [user] 北京天气怎么样？
      ← LLM 返回 (finish_reason=tool_calls)
      [assistant] {"tool": "get_weather", "args": {"city": "北京"}}
      ← 执行工具 get_weather {"city": "北京"}
      [tool] 晴，25°C
      ────────── 组装请求#2 ... ──────────
      ← LLM 返回 (finish_reason=stop)
      [assistant] 北京晴，25度，适合跑步
    """

    def __init__(self):
        from datetime import datetime

        self.enabled = DEBUG_LOG_ENABLED
        self.current_round: int = -1
        self.path: Optional[Path] = None
        self._round_count = 0      # 已发出的请求轮数
        self._attempt_idx = 0      # 当前轮内的尝试序号（required→auto 重试）
        self._tool_call_count = 0  # 工具执行总次数
        if not self.enabled:
            return
        conv_id = uuid.uuid4().hex[:12]
        now = datetime.now()
        self.path = _DEBUG_LOG_DIR / f"conv_{now.strftime('%Y%m%d_%H%M%S')}_{conv_id}.log"
        try:
            _DEBUG_LOG_DIR.mkdir(exist_ok=True)
            self.path.write_text("", encoding="utf-8")
        except Exception:
            self.enabled = False
            return
        self._bar("═")
        self._write(f"对话调试日志 | 会话: {conv_id} | 开始: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        self._bar("═")
        self._write("")

    # ── 基础写入 ──

    def _write(self, text: str = "") -> None:
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _bar(self, char: str = "─") -> None:
        self._write(char * 64)

    @staticmethod
    def _fmt_message(m: dict) -> str:
        """把一条消息格式化为 [role] 内容 的可读行；tool_calls 用 {"tool":..,"args":..} 样式。"""
        role = m.get("role", "?")
        content = m.get("content", "")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                content = str(content)
        lines: list = []
        if content:
            lines.append(f"[{role}] {content}")
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw = fn.get("arguments", "")
            if isinstance(raw, str):
                try:
                    args = json.loads(raw) if raw else {}
                except Exception:
                    args = raw
            else:
                args = raw
            lines.append(f"[{role}] " + json.dumps({"tool": fn.get("name"), "args": args}, ensure_ascii=False))
        if not lines:
            lines.append(f"[{role}] (空)")
        return "\n".join(lines)

    @staticmethod
    def _parse_maybe_json(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    # ── 事件记录（由 stream_with_tools / chat 调用） ──

    def start_round(self, *, model: str, messages: list, tools: list, tool_choice) -> int:
        """新一轮 LLM 请求：原样打印本轮实际发送的完整请求体（工具定义 + 全部消息）。"""
        if not self.enabled:
            return -1
        self._round_count += 1
        self.current_round = self._round_count - 1
        self._attempt_idx = 0
        total_chars = sum(
            len(m.get("content")) if isinstance(m.get("content"), str) else 0
            for m in messages
        )
        self._bar()
        self._write(f"组装请求#{self._round_count} (model={model}, tool_choice={tool_choice}, {len(messages)}条消息/约{total_chars}字符)")
        self._bar()
        if tools:
            self._write("工具定义:")
            for t in tools:
                fn = t.get("function", {})
                self._write(f"  - {fn.get('name')}: {fn.get('description', '')}")
                if fn.get("parameters"):
                    self._write(f"    参数: {json.dumps(fn['parameters'], ensure_ascii=False)}")
            self._write("")
        for m in messages:
            self._write(self._fmt_message(m))
        self._write("")
        return self.current_round

    def log_attempt(self, round_no: int, *, tool_choice, finish_reason, content, tool_calls, error=None) -> None:
        """记录一次 LLM API 调用返回：finish_reason / content / tool_calls。"""
        if not self.enabled or round_no < 0:
            return
        self._attempt_idx += 1
        tag = f"[尝试{self._attempt_idx} tool_choice={tool_choice}] " if self._attempt_idx > 1 else ""
        if error:
            self._write(f"← LLM 返回 {tag}(finish_reason={finish_reason}) ⚠ 失败: {error}")
        else:
            self._write(f"← LLM 返回 {tag}(finish_reason={finish_reason})")
        if content:
            self._write(f"[assistant] {content}")
        for tc in tool_calls or []:
            args = self._parse_maybe_json(tc.get("arguments"))
            self._write("[assistant] " + json.dumps({"tool": tc.get("name"), "args": args}, ensure_ascii=False))
        self._write("")

    def log_tool_result(self, round_no: int, *, name: str, arguments, result) -> None:
        """记录工具执行的参数与完整返回内容。"""
        if not self.enabled or round_no < 0:
            return
        self._tool_call_count += 1
        args = self._parse_maybe_json(arguments)
        if args:
            self._write(f"← 执行工具 {name} {json.dumps(args, ensure_ascii=False)}")
        else:
            self._write(f"← 执行工具 {name}")
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        self._write(f"[tool] {text}")
        self._write("")

    def log_message(self, role: str, content, note: str = None) -> None:
        """记录系统/框架追加到对话的消息（重试提示、强制工具提示等）。"""
        if not self.enabled:
            return
        prefix = f"({note}) " if note else ""
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self._write(f"[{role}] {prefix}{text}")

    def log_note(self, text: str) -> None:
        """记录系统行为提示（上下文压缩、参数修复、临时注入等）。"""
        if not self.enabled:
            return
        self._write(f"⚠ {text}")
        self._write("")

    def finish(self, final_text: str) -> None:
        """对话结束：汇总轮次与工具调用次数，记录最终回复文本。"""
        if not self.enabled:
            return
        from datetime import datetime

        self._bar("═")
        self._write(f"对话结束 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 共 {self._round_count} 轮请求, {self._tool_call_count} 次工具调用")
        self._write("最终回复:")
        self._write(final_text or "(无)")
        self._bar("═")


async def test_connection(
    provider: str,
    model: str,
    api_key_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
) -> Tuple[bool, str]:
    if is_cloud_provider(provider):
        template_id = get_cloud_template_id(provider)
        if template_id is None:
            return False, "云端模型配置异常，请重新选择"
        from ..core.cloud_auth import cloud_auth
        token = cloud_auth.current_token()
        if not token:
            return False, "未登录，无法测试官方模型"
        try:
            async for ev in stream_cloud_chat(token, template_id, [{"role": "user", "content": "Hi"}], max_tokens=10, source="test"):
                if ev.get("type") == "error":
                    return False, ev["content"]
                if ev.get("type") == "text" and ev.get("content"):
                    break
            return True, "连接成功（云端代理）"
        except Exception as e:
            return False, f"云端连接失败: {str(e)[:100]}"

    settings = load_settings()
    api_key = api_key_override or get_api_key(provider, settings)
    if not api_key:
        return False, "未配置当前所选模型的 API Key"

    custom_cm: Optional[dict] = None
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        custom_cm = get_custom_model(provider, settings)
        if not custom_cm:
            return False, f"找不到自定义模型: {provider}"
    elif provider != CUSTOM_PROVIDER_KEY:
        return False, f"不支持的 Provider: {provider}（本应用仅支持自定义模型）"

    try:
        if custom_cm is not None:
            base_url = base_url_override or _resolve_base_url(custom_cm)
            if not base_url:
                return False, "自定义模型未配置 Base URL"
            test_model = model or custom_cm.get("model_id", "")
            if not test_model:
                return False, "自定义模型未配置 Model ID"
        else:
            base_url = base_url_override or settings.get("custom", {}).get("base_url", "")
            if not base_url:
                return False, "自定义模型未配置 Base URL"
            test_model = model

        clean_url = base_url.rstrip("/")
        if clean_url.endswith("/chat/completions"):
            clean_url = clean_url[: -len("/chat/completions")]
        client = AsyncOpenAI(base_url=clean_url, api_key=api_key)
        stream = await client.chat.completions.create(
            model=test_model, messages=[{"role": "user", "content": "Hi"}], stream=True, max_tokens=10,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                break
        return True, "连接成功"
    except Exception as e:
        err_msg = str(e)
        if "401" in err_msg or "Unauthorized" in err_msg or "invalid" in err_msg.lower():
            return False, "API Key 无效或已过期"
        if "429" in err_msg or "rate" in err_msg.lower():
            return False, "请求过于频繁，请稍后再试"
        return False, f"连接失败: {err_msg[:100]}"


async def stream_response(
    system: str,
    messages: list,
    source: str = "resume",
) -> AsyncGenerator[str, None]:
    """流式调用当前配置的模型。source 为额度用量明细的功能来源。"""
    settings = load_settings()
    provider = settings.get("provider", "")
    model = settings.get("model", "")

    if is_cloud_provider(provider):
        template_id = get_cloud_template_id(provider)
        if template_id is None:
            yield "⚠️ 云端模型配置异常，请重新选择。"
            return
        from ..core.cloud_auth import cloud_auth
        token = cloud_auth.current_token()
        if not token:
            yield "⚠️ 未登录，请先登录后再使用官方模型。"
            return
        openai_messages = [{"role": "system", "content": system}] + messages
        async for ev in stream_cloud_chat(token, template_id, openai_messages, source=source):
            if ev["type"] == "text":
                yield ev["content"]
            elif ev["type"] == "error":
                raise RuntimeError(ev["content"])
        return

    api_key = get_api_key(provider, settings)

    if not api_key:
        yield "⚠️ 未配置当前所选模型的 API Key，请在「模型管理」中填写。"
        return

    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if not cm:
            yield f"⚠️ 找不到自定义模型: {provider}"
            return
        base_url = _resolve_base_url(cm)
        if not base_url:
            yield "⚠️ 自定义模型未配置 Base URL，请在「模型管理」中填写。"
            return
        custom_model = cm.get("model_id", "") or model
        ctx_out = int(cm.get("context_output") or 8192)
        async for text in _stream_openai_compat(base_url, api_key, custom_model, system, messages, max_tokens=ctx_out):
            yield text
        return

    # CUSTOM_PROVIDER_KEY 或未配置情况：一律按自定义的 OpenAI 兼容模型处理
    custom_cfg = settings.get("custom", {})
    base_url = custom_cfg.get("base_url", "")
    if not base_url:
        yield "⚠️ 自定义模型未配置 Base URL，请在「模型管理」中填写。"
        return
    custom_model = custom_cfg.get("model", "") or model
    async for text in _stream_openai_compat(base_url, api_key, custom_model, system, messages):
        yield text


async def complete_response(system: str, messages: list, source: str = "resume") -> str:
    parts: list[str] = []
    async for text in stream_response(system, messages, source=source):
        parts.append(text)
    return "".join(parts)


async def complete_response_with_provider(provider: str, model: str, system: str, messages: list, max_tokens: int = 300, source: str = "greeting") -> str:
    """使用指定 provider+model 调用模型，返回完整文本。用于 AI 招呼语等非全局配置场景。"""
    if is_cloud_provider(provider):
        template_id = get_cloud_template_id(provider)
        if template_id is None:
            raise RuntimeError("云端模型配置异常")
        from ..core.cloud_auth import cloud_auth
        token = cloud_auth.current_token()
        if not token:
            raise RuntimeError("未登录，无法使用官方模型")
        openai_messages = [{"role": "system", "content": system}] + messages
        parts: list[str] = []
        async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens, source=source):
            if ev["type"] == "text":
                parts.append(ev["content"])
            elif ev["type"] == "error":
                raise RuntimeError(ev["content"])
        return "".join(parts)

    settings = load_settings()
    api_key = get_api_key(provider, settings)
    if not api_key:
        raise RuntimeError(f"未配置 {provider} 的 API Key，请在「模型管理」中填写")

    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if not cm:
            raise RuntimeError(f"找不到自定义模型: {provider}")
        base_url = _resolve_base_url(cm)
        if not base_url:
            raise RuntimeError("自定义模型未配置 Base URL")
        use_model = cm.get("model_id", "") or model
        parts: list[str] = []
        async for text in _stream_openai_compat(base_url, api_key, use_model, system, messages, max_tokens=max_tokens):
            parts.append(text)
        return "".join(parts)

    if provider == CUSTOM_PROVIDER_KEY:
        custom_cfg = settings.get("custom", {})
        base_url = custom_cfg.get("base_url", "")
        if not base_url:
            raise RuntimeError("自定义模型未配置 Base URL")
        use_model = custom_cfg.get("model", "") or model
        parts: list[str] = []
        async for text in _stream_openai_compat(base_url, api_key, use_model, system, messages, max_tokens=max_tokens):
            parts.append(text)
        return "".join(parts)

    raise RuntimeError(f"不支持的 Provider: {provider}（本应用仅支持自定义模型）")


def complete_response_sync(system: str, messages: list, *, max_tokens: int = 8192, timeout: float = 600.0, source: str = "resume") -> str:
    """同步调用当前模型管理配置的模型，返回完整文本。供 resume_parser 等同步场景使用。"""
    settings = load_settings()
    provider = settings.get("provider", "")

    if is_cloud_provider(provider):
        template_id = get_cloud_template_id(provider)
        if template_id is None:
            raise RuntimeError("云端模型配置异常")
        from ..core.cloud_auth import cloud_auth
        token = cloud_auth.current_token()
        if not token:
            raise RuntimeError("未登录，无法使用官方模型")
        openai_messages = [{"role": "system", "content": system}] + messages

        async def _do_cloud():
            parts: list[str] = []
            async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens, source=source):
                if ev["type"] == "text":
                    parts.append(ev["content"])
                elif ev["type"] == "error":
                    raise RuntimeError(ev["content"])
            return "".join(parts)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的事件循环（纯同步/工作线程上下文）：直接新建循环执行
            return asyncio.run(_do_cloud())
        # 事件循环线程内被同步调用：提交到线程池用独立事件循环执行并阻塞等待。
        # 必须用 pool.submit（concurrent Future 可阻塞等待）；不能用 loop.run_in_executor，
        # 它返回 asyncio Future，pending 时 .result() 会抛 InvalidStateError
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_do_cloud())).result()

    base_url, api_key, model_id, provider_type = _resolve_current_provider(settings)
    ctx_out = _get_context_output(settings)
    max_tokens = min(max_tokens, ctx_out)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置当前所选模型的 API Key，请在「模型管理」中填写。",
        )

    if AsyncOpenAI is None:
        raise RuntimeError("openai 库未安装，请 pip install openai")
    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="当前模型未配置 Base URL，请在「模型管理」中填写。",
        )
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url[: -len("/chat/completions")]
    client = OpenAI(base_url=clean_url, api_key=api_key, timeout=timeout)
    openai_messages = [{"role": "system", "content": system}] + messages
    resp = client.chat.completions.create(
        model=model_id,
        messages=openai_messages,
        stream=False,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


async def sse_with_heartbeat(sse_gen: AsyncGenerator[str, None], interval: float = 10.0) -> AsyncGenerator[str, None]:
    """为 SSE 生成器添加心跳保活。"""
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    async def _producer():
        try:
            async for item in sse_gen:
                await queue.put(item)
        except Exception as e:
            await queue.put(("__error__", str(e)[:300]))
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(_producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _DONE:
                break
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__error__":
                yield f'data: {json.dumps({"type": "error", "content": item[1]})}\n\n'
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass


async def stream_with_tools(
    system: str,
    messages: list,
    tools: list,
    max_tokens: int = 8192,
    timeout: float = 1800.0,
    tool_choice: str = "auto",
    debug_log: Optional[ConversationDebugLog] = None,
    source: str = "chat",
) -> AsyncGenerator[dict, None]:
    """带工具调用的流式对话（OpenAI 兼容格式）。

    yield 事件：
      - {"type": "text", "content": "..."}      文本片段
      - {"type": "tool_calls", "calls": [...]}   完整的 tool_calls（流结束后）
      - {"type": "done"}                         本轮流结束

    debug_log: 传入 ConversationDebugLog 可将本轮请求/响应细节
    追加到该对话的 debug 日志文件中（一次对话一个文件）。
    source: 功能来源（额度用量明细），默认 chat（简历 Agent 对话）。
    """
    settings = load_settings()
    provider = settings.get("provider", "")
    model = settings.get("model", "")

    if is_cloud_provider(provider):
        template_id = get_cloud_template_id(provider)
        if template_id is None:
            yield {"type": "text", "content": "⚠️ 云端模型配置异常，请重新选择。"}
            yield {"type": "done"}
            return
        from ..core.cloud_auth import cloud_auth
        token = cloud_auth.current_token()
        if not token:
            yield {"type": "text", "content": "⚠️ 未登录，请先登录后再使用官方模型。"}
            yield {"type": "done"}
            return
        openai_messages = [{"role": "system", "content": system}] + sanitize_anthropic_history(messages)
        _round_no = -1
        if debug_log is not None:
            _round_no = debug_log.start_round(
                model=f"cloud:{template_id}",
                messages=openai_messages, tools=tools, tool_choice=tool_choice,
            )
        _cloud_texts: list = []
        _cloud_calls: list = []
        _cloud_err: Optional[str] = None
        try:
            async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens, tools=tools, tool_choice=tool_choice, source=source):
                if ev["type"] == "error":
                    _cloud_err = ev["content"]
                    yield {"type": "text", "content": ev["content"]}
                else:
                    if ev.get("type") == "text":
                        _cloud_texts.append(ev.get("content", ""))
                    elif ev.get("type") == "tool_calls":
                        _cloud_calls = ev.get("calls", [])
                    yield ev
        except Exception as e:
            _cloud_err = str(e)[:300]
            yield {"type": "text", "content": f"\n\n[云端调用失败: {str(e)[:200]}]"}
        if debug_log is not None:
            debug_log.log_attempt(
                _round_no,
                tool_choice=tool_choice,
                finish_reason=("error" if _cloud_err else ("tool_calls" if _cloud_calls else "stop")),
                content="".join(_cloud_texts),
                tool_calls=_cloud_calls,
                error=_cloud_err,
            )
        yield {"type": "done"}
        return

    api_key = get_api_key(provider, settings)

    if not api_key:
        yield {"type": "text", "content": "⚠️ 未配置当前所选模型的 API Key，请在「模型管理」中填写。"}
        yield {"type": "done"}
        return

    base_url: Optional[str] = None
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if not cm:
            yield {"type": "text", "content": f"⚠️ 找不到自定义模型: {provider}"}
            yield {"type": "done"}
            return
        base_url = _resolve_base_url(cm)
        if not base_url:
            yield {"type": "text", "content": "⚠️ 自定义模型未配置 Base URL"}
            yield {"type": "done"}
            return
        model = cm.get("model_id", "") or model
    else:
        # CUSTOM_PROVIDER_KEY 或未配置情况：一律按自定义的 OpenAI 兼容模型处理
        base_url = settings.get("custom", {}).get("base_url", "")
        if not base_url:
            yield {"type": "text", "content": "⚠️ 自定义模型未配置 Base URL"}
            yield {"type": "done"}
            return
        model = settings.get("custom", {}).get("model", "") or model

    if AsyncOpenAI is None:
        yield {"type": "text", "content": "⚠️ openai 库未安装"}
        yield {"type": "done"}
        return

    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url[: -len("/chat/completions")]
    client = AsyncOpenAI(base_url=clean_url, api_key=api_key, timeout=timeout)

    openai_messages = [{"role": "system", "content": system}] + sanitize_anthropic_history(messages)

    _round_no = -1
    if debug_log is not None:
        _round_no = debug_log.start_round(
            model=model, messages=openai_messages, tools=tools, tool_choice=tool_choice,
        )
    _finish_state: dict = {"reason": None}

    async def _run_once(tool_choice_val: str):
        """执行一次流式工具调用，产出 text / tool_calls / done 事件。"""
        tool_call_acc: Dict[int, dict] = {}
        _finish_state["reason"] = None
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=openai_messages,
                stream=True,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice_val,
            )
        except Exception:
            raise

        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    yield {"type": "text", "content": delta.content}

                # 思考模型经 OpenAI 兼容端点可能返回 reasoning_content / reasoning 字段
                _reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if _reasoning:
                    yield {"type": "reasoning", "content": _reasoning}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_acc:
                            tool_call_acc[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.id:
                            tool_call_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_call_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_call_acc[idx]["arguments"] += tc.function.arguments

                _fr = chunk.choices[0].finish_reason
                if _fr:
                    _finish_state["reason"] = _fr
                if _fr == "tool_calls":
                    break
        except Exception as e:
            yield {"type": "text", "content": f"\n\n[流式输出中断: {str(e)[:200]}]"}

        if tool_call_acc:
            calls = []
            for idx in sorted(tool_call_acc.keys()):
                tc = tool_call_acc[idx]
                raw_args = tc["arguments"]
                if raw_args:
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = repair_json_args(raw_args)
                else:
                    args = {}
                calls.append({"id": tc["id"], "name": tc["name"], "arguments": args, "raw_arguments": raw_args})
            yield {"type": "tool_calls", "calls": calls}

        yield {"type": "done"}

    attempts = ["required", "auto"] if tool_choice == "required" else [tool_choice]
    last_err: Optional[Exception] = None

    for attempt in attempts:
        buffered_events: list = []
        has_tool_calls = False
        has_done = False
        attempt_texts: list = []
        attempt_calls: list = []
        try:
            async for event in _run_once(attempt):
                buffered_events.append(event)
                if event.get("type") == "tool_calls":
                    has_tool_calls = True
                    attempt_calls = event.get("calls", [])
                if event.get("type") == "text":
                    attempt_texts.append(event.get("content", ""))
                if event.get("type") == "done":
                    has_done = True
        except Exception as e:
            last_err = e
            if debug_log is not None:
                debug_log.log_attempt(
                    _round_no, tool_choice=attempt, finish_reason="error",
                    content="".join(attempt_texts), tool_calls=attempt_calls,
                    error=str(e)[:500],
                )
            if not buffered_events:
                continue
            has_text = any(ev.get("type") == "text" for ev in buffered_events)
            if has_text:
                for ev in buffered_events:
                    yield ev
                return
            continue
        else:
            if debug_log is not None:
                debug_log.log_attempt(
                    _round_no, tool_choice=attempt,
                    finish_reason=_finish_state["reason"],
                    content="".join(attempt_texts),
                    tool_calls=attempt_calls,
                )

        for ev in buffered_events:
            yield ev
        if has_done:
            return

    if last_err:
        msg = str(last_err)
        if "tool" in msg.lower() or "function" in msg.lower() or "unspported" in msg.lower() or "not support" in msg.lower():
            _fb_texts: list = []
            async for text in _stream_openai_compat(base_url, api_key, model, system, messages, max_tokens):
                _fb_texts.append(text)
                yield {"type": "text", "content": text}
            yield {"type": "done"}
            if debug_log is not None:
                debug_log.log_attempt(
                    _round_no, tool_choice="auto（降级：不带 tools）",
                    finish_reason="stop", content="".join(_fb_texts), tool_calls=[],
                    error=f"工具调用不受支持，已降级为纯文本模式: {msg[:300]}",
                )
            return
        yield {"type": "text", "content": f"\n\n[API 调用失败: {msg[:300]}]"}
        yield {"type": "done"}
    return
