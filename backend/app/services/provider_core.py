"""公共 API 调度层：连接测试、流式/非流式调用、工具调用、debug 日志、SSE 心跳。"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Tuple

from fastapi import HTTPException

from .provider_settings import (
    PROVIDERS, CUSTOM_PROVIDER_KEY, DEBUG_LOG_ENABLED,
    load_settings, get_api_key, get_custom_model,
    _resolve_base_url, _resolve_current_provider,
    _get_context_input, _get_context_output,
    is_current_model_multimodal,
)
from .provider_openai import _repair_json_args, _stream_openai_compat
from .provider_anthropic import (
    _stream_anthropic, _stream_anthropic_with_tools,
)

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore


async def test_connection(
    provider: str,
    model: str,
    api_key_override: Optional[str] = None,
    base_url_override: Optional[str] = None,
) -> Tuple[bool, str]:
    settings = load_settings()
    api_key = api_key_override or get_api_key(provider, settings)
    if not api_key:
        return False, "未配置当前所选模型的 API Key"
    pconfig = PROVIDERS.get(provider)

    custom_cm: Optional[dict] = None
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        custom_cm = get_custom_model(provider, settings)
        if not custom_cm:
            return False, f"找不到自定义模型: {provider}"

    if not pconfig and provider != CUSTOM_PROVIDER_KEY and custom_cm is None:
        return False, f"不支持的 Provider: {provider}"
    try:
        if custom_cm is not None:
            base_url = base_url_override or _resolve_base_url(custom_cm)
            if not base_url:
                return False, "自定义模型未配置 Base URL"
            test_model = model or custom_cm.get("model_id", "")
            if not test_model:
                return False, "自定义模型未配置 Model ID"
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
        elif provider == CUSTOM_PROVIDER_KEY:
            base_url = base_url_override or settings.get("custom", {}).get("base_url", "")
            if not base_url:
                return False, "自定义模型未配置 Base URL"
            clean_url = base_url.rstrip("/")
            if clean_url.endswith("/chat/completions"):
                clean_url = clean_url[: -len("/chat/completions")]
            client = AsyncOpenAI(base_url=clean_url, api_key=api_key)
            stream = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "Hi"}], stream=True, max_tokens=10,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    break
        elif pconfig["type"] == "anthropic":
            client = anthropic.AsyncAnthropic(api_key=api_key)
            async with client.messages.stream(
                model=model, max_tokens=10, messages=[{"role": "user", "content": "Hi"}],
            ) as stream:
                async for _ in stream.text_stream:
                    break
        else:
            client = AsyncOpenAI(base_url=pconfig["base_url"], api_key=api_key)
            stream = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "Hi"}], stream=True, max_tokens=10,
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
) -> AsyncGenerator[str, None]:
    settings = load_settings()
    provider = settings.get("provider", "anthropic")
    model = settings.get("model", PROVIDERS["anthropic"]["default_model"])
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

    if provider == CUSTOM_PROVIDER_KEY:
        custom_cfg = settings.get("custom", {})
        base_url = custom_cfg.get("base_url", "")
        if not base_url:
            yield "⚠️ 自定义模型未配置 Base URL，请在「模型管理」中填写。"
            return
        custom_model = custom_cfg.get("model", "") or model
        async for text in _stream_openai_compat(base_url, api_key, custom_model, system, messages):
            yield text
        return

    pconfig = PROVIDERS.get(provider)
    if not pconfig:
        yield f"⚠️ 不支持的 Provider: {provider}"
        return

    if pconfig["type"] == "anthropic":
        async for text in _stream_anthropic(api_key, model, system, messages):
            yield text
    else:
        async for text in _stream_openai_compat(
            pconfig["base_url"], api_key, model, system, messages
        ):
            yield text


async def complete_response(system: str, messages: list) -> str:
    parts: list[str] = []
    async for text in stream_response(system, messages):
        parts.append(text)
    return "".join(parts)


async def complete_response_with_provider(provider: str, model: str, system: str, messages: list, max_tokens: int = 300) -> str:
    """使用指定 provider+model 调用模型，返回完整文本。用于 AI 招呼语等非全局配置场景。"""
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

    pconfig = PROVIDERS.get(provider)
    if not pconfig:
        raise RuntimeError(f"不支持的 Provider: {provider}")

    use_model = model or pconfig.get("default_model", "")

    if pconfig["type"] == "anthropic":
        parts: list[str] = []
        async for text in _stream_anthropic(api_key, use_model, system, messages):
            parts.append(text)
        return "".join(parts)
    else:
        parts: list[str] = []
        async for text in _stream_openai_compat(pconfig["base_url"], api_key, use_model, system, messages, max_tokens=max_tokens):
            parts.append(text)
        return "".join(parts)


def complete_response_sync(system: str, messages: list, *, max_tokens: int = 8192, timeout: float = 600.0) -> str:
    """同步调用当前模型管理配置的模型，返回完整文本。供 resume_parser 等同步场景使用。"""
    settings = load_settings()
    base_url, api_key, model_id, provider_type = _resolve_current_provider(settings)
    ctx_out = _get_context_output(settings)
    max_tokens = min(max_tokens, ctx_out)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置当前所选模型的 API Key，请在「模型管理」中填写。",
        )

    if provider_type == "anthropic":
        if anthropic is None:
            raise RuntimeError("anthropic 库未安装，请 pip install anthropic")
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        resp = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return (resp.content[0].text if resp.content else "").strip()

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
) -> AsyncGenerator[dict, None]:
    """带工具调用的流式对话（OpenAI 兼容格式）。

    yield 事件：
      - {"type": "text", "content": "..."}      文本片段
      - {"type": "tool_calls", "calls": [...]}   完整的 tool_calls（流结束后）
      - {"type": "done"}                         本轮流结束
    """
    settings = load_settings()
    provider = settings.get("provider", "anthropic")
    model = settings.get("model", PROVIDERS["anthropic"]["default_model"])
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
    elif provider == CUSTOM_PROVIDER_KEY:
        base_url = settings.get("custom", {}).get("base_url", "")
        if not base_url:
            yield {"type": "text", "content": "⚠️ 自定义模型未配置 Base URL"}
            yield {"type": "done"}
            return
        model = settings.get("custom", {}).get("model", "") or model
    else:
        pconfig = PROVIDERS.get(provider)
        if not pconfig:
            yield {"type": "text", "content": f"⚠️ 不支持的 Provider: {provider}"}
            yield {"type": "done"}
            return
        if pconfig["type"] == "anthropic":
            async for event in _stream_anthropic_with_tools(api_key, model, system, messages, tools, tool_choice):
                yield event
            return
        base_url = pconfig["base_url"]

    if AsyncOpenAI is None:
        yield {"type": "text", "content": "⚠️ openai 库未安装"}
        yield {"type": "done"}
        return

    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url[: -len("/chat/completions")]
    client = AsyncOpenAI(base_url=clean_url, api_key=api_key, timeout=timeout)

    openai_messages = [{"role": "system", "content": system}] + messages

    _DEBUG_DIR = Path(__file__).resolve().parents[2] / "debug_logs"
    _debug_id = uuid.uuid4().hex[:8]
    _debug_path = _DEBUG_DIR / f"llm_call_{_debug_id}.json"
    _debug_payload: dict = {"model": model, "tool_choice": tool_choice}
    _debug_msg_sizes: list = []
    _debug_response_parts: list = []
    _debug_tool_calls: list = []
    if DEBUG_LOG_ENABLED:
        _DEBUG_DIR.mkdir(exist_ok=True)
        for _mi, _m in enumerate(openai_messages):
            _c = _m.get("content", "")
            _sz = len(_c) if isinstance(_c, str) else -1
            _debug_msg_sizes.append({"index": _mi, "role": _m.get("role", ""), "size": _sz, "content": _c})
        _debug_payload["messages"] = _debug_msg_sizes
        _debug_payload["response"] = None
        _debug_payload["total_messages"] = len(openai_messages)
        _debug_payload["total_chars"] = sum(m.get("size", 0) for m in _debug_msg_sizes)
        try:
            _debug_path.write_text(json.dumps(_debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def _run_once(tool_choice_val: str):
        """执行一次流式工具调用，产出 text / tool_calls / done 事件。"""
        tool_call_acc: Dict[int, dict] = {}
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

                if chunk.choices[0].finish_reason == "tool_calls":
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
                        args = _repair_json_args(raw_args)
                else:
                    args = {}
                calls.append({"id": tc["id"], "name": tc["name"], "arguments": args, "raw_arguments": raw_args})
            yield {"type": "tool_calls", "calls": calls}

        yield {"type": "done"}

    attempts = ["required", "auto"] if tool_choice == "required" else [tool_choice]
    last_err: Optional[Exception] = None

    def _flush_debug():
        if not DEBUG_LOG_ENABLED:
            return
        _debug_payload["response"] = {
            "text": "".join(_debug_response_parts),
            "tool_calls": _debug_tool_calls,
        }
        try:
            _debug_path.write_text(json.dumps(_debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    for attempt in attempts:
        buffered_events: list = []
        has_tool_calls = False
        has_done = False
        try:
            async for event in _run_once(attempt):
                buffered_events.append(event)
                if event.get("type") == "tool_calls":
                    has_tool_calls = True
                    if DEBUG_LOG_ENABLED:
                        for _tc in event.get("calls", []):
                            _debug_tool_calls.append({"id": _tc.get("id", ""), "name": _tc.get("name", ""), "arguments": _tc.get("arguments", {})})
                if event.get("type") == "text":
                    if DEBUG_LOG_ENABLED:
                        _debug_response_parts.append(event.get("content", ""))
                if event.get("type") == "done":
                    has_done = True
        except Exception as e:
            last_err = e
            if not buffered_events:
                continue
            has_text = any(ev.get("type") == "text" for ev in buffered_events)
            if has_text:
                for ev in buffered_events:
                    yield ev
                _flush_debug()
                return
            continue

        for ev in buffered_events:
            yield ev
        if has_done:
            _flush_debug()
            return

    if last_err:
        msg = str(last_err)
        if "tool" in msg.lower() or "function" in msg.lower() or "unspported" in msg.lower() or "not support" in msg.lower():
            async for text in _stream_openai_compat(base_url, api_key, model, system, messages, max_tokens):
                yield {"type": "text", "content": text}
            yield {"type": "done"}
            _flush_debug()
            return
        yield {"type": "text", "content": f"\n\n[API 调用失败: {msg[:300]}]"}
        yield {"type": "done"}
    _flush_debug()
    return
