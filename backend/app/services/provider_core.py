"""公共 API 调度层：连接测试、流式/非流式调用、工具调用、debug 日志、SSE 心跳。"""
from __future__ import annotations

import asyncio
import json
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
            async for ev in stream_cloud_chat(token, template_id, [{"role": "user", "content": "Hi"}], max_tokens=10):
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
) -> AsyncGenerator[str, None]:
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
        async for ev in stream_cloud_chat(token, template_id, openai_messages):
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


async def complete_response(system: str, messages: list) -> str:
    parts: list[str] = []
    async for text in stream_response(system, messages):
        parts.append(text)
    return "".join(parts)


async def complete_response_with_provider(provider: str, model: str, system: str, messages: list, max_tokens: int = 300) -> str:
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
        async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens):
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


def complete_response_sync(system: str, messages: list, *, max_tokens: int = 8192, timeout: float = 600.0) -> str:
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
            async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens):
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
) -> AsyncGenerator[dict, None]:
    """带工具调用的流式对话（OpenAI 兼容格式）。

    yield 事件：
      - {"type": "text", "content": "..."}      文本片段
      - {"type": "tool_calls", "calls": [...]}   完整的 tool_calls（流结束后）
      - {"type": "done"}                         本轮流结束
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
        openai_messages = [{"role": "system", "content": system}] + messages
        try:
            async for ev in stream_cloud_chat(token, template_id, openai_messages, max_tokens=max_tokens, tools=tools, tool_choice=tool_choice):
                if ev["type"] == "error":
                    yield {"type": "text", "content": ev["content"]}
                else:
                    yield ev
        except Exception as e:
            yield {"type": "text", "content": f"\n\n[云端调用失败: {str(e)[:200]}]"}
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
                        args = repair_json_args(raw_args)
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
