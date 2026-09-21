"""OpenAI 兼容提供商适配：流式调用 + 云端代理调用。"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


async def _stream_openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: list,
    max_tokens: int = 8192,
    timeout: float = 1800.0,
) -> AsyncGenerator[str, None]:
    if AsyncOpenAI is None:
        raise RuntimeError("openai 库未安装，请 pip install openai")
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url[: -len("/chat/completions")]
    client = AsyncOpenAI(base_url=clean_url, api_key=api_key, timeout=timeout)
    openai_messages = [{"role": "system", "content": system}] + messages
    stream = await client.chat.completions.create(
        model=model,
        messages=openai_messages,
        stream=True,
        max_tokens=max_tokens,
    )
    try:
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except Exception as e:
        yield f"\n\n[流式输出中断: {str(e)[:200]}]"


async def stream_cloud_chat(
    token: str,
    template_id: int,
    messages: list,
    max_tokens: int = 8192,
    tools: list | None = None,
    tool_choice: str | None = None,
) -> AsyncGenerator[dict, None]:
    """通过云端代理调用官方模型（SSE 流式）。

    yield 事件：
      - {"type": "text", "content": "..."}           文本片段
      - {"type": "error", "content": "..."}          调用失败
      - {"type": "tool_calls", "calls": [...]}       完整 tool_calls（流结束后，仅当传入 tools）
    """
    if httpx is None:
        raise RuntimeError("httpx 库未安装")

    from ..core.config import CLOUD_SERVER_URL
    from ..core.json_utils import repair_json_args

    payload: dict = {
        "template_id": template_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    tool_call_acc: dict[int, dict] = {}
    output_chars = 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
        async with client.stream(
            "POST",
            f"{CLOUD_SERVER_URL}/client/models/chat",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        ) as resp:
            if resp.status_code != 200:
                error_body = await resp.aread()
                try:
                    err = json.loads(error_body)
                    yield {"type": "error", "content": f"云端模型调用失败: {err.get('detail', resp.status_code)}"}
                except Exception:
                    yield {"type": "error", "content": f"云端模型调用失败: HTTP {resp.status_code}"}
                return

            finished = False
            sse_buffer = b""
            try:
                async for chunk in resp.aiter_bytes():
                    # 按字节缓冲、整行再解码：chunk 边界可能切开 UTF-8 多字节字符，
                    # 逐 chunk 解码会产生 U+FFFD 导致 JSON 解析失败、整段事件被丢弃
                    sse_buffer += chunk
                    while b"\n" in sse_buffer:
                        line_bytes, sse_buffer = sse_buffer.split(b"\n", 1)
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            finished = True
                            break
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            logging.getLogger("autoresume.cloud_chat").warning("SSE JSON decode failed: %s", data_str[:200])
                            continue
                        if "error" in data and "choices" not in data:
                            yield {"type": "error", "content": f"云端模型调用失败: {data['error']}"}
                            return
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}) or {}
                        content = delta.get("content", "")
                        if content:
                            output_chars += len(content)
                            yield {"type": "text", "content": content}
                        for tc in delta.get("tool_calls", []) or []:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_acc:
                                tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.get("id"):
                                tool_call_acc[idx]["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                tool_call_acc[idx]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tool_call_acc[idx]["arguments"] += fn["arguments"]
                    if finished:
                        break
            except httpx.HTTPError as e:
                err_str = str(e)
                is_incomplete_chunked = "incomplete chunked" in err_str or "StreamClosed" in err_str or "peer closed" in err_str
                if not finished:
                    if is_incomplete_chunked and (output_chars > 0 or tool_call_acc):
                        finished = True
                    else:
                        yield {"type": "error", "content": f"云端连接中断（输出可能不完整）: {err_str[:150]}"}
                        return

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
