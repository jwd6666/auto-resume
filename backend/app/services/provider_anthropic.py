"""Anthropic Claude 提供商适配：格式转换、流式调用、工具调用。"""
from __future__ import annotations

import json
from typing import AsyncGenerator

from .provider_openai import _repair_json_args

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore


def _convert_openai_images_to_anthropic(messages: list) -> list:
    """将 OpenAI 格式的 image_url content 转换为 Anthropic 格式。"""
    import base64
    converted = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list) and msg.get("role") == "user":
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        try:
                            header, data = url.split(",", 1)
                            media_type = header.split(";")[0].split(":")[1] if ":" in header else "image/png"
                            new_parts.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": data},
                            })
                        except (ValueError, IndexError):
                            new_parts.append(part)
                    else:
                        new_parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    new_parts.append({"type": "text", "text": part.get("text", "")})
                else:
                    new_parts.append(part)
            converted.append({**msg, "content": new_parts})
        else:
            converted.append(msg)
    return converted


def _convert_openai_tools_to_anthropic(tools: list) -> list:
    """将 OpenAI 格式的 tools 定义转换为 Anthropic 格式。"""
    anthropic_tools = []
    for t in tools:
        func = t.get("function", {})
        anthropic_tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return anthropic_tools


def _convert_openai_messages_to_anthropic_tool_messages(messages: list) -> list:
    """将 OpenAI 格式的 tool_calls / tool 消息转换为 Anthropic 格式。"""
    converted = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "assistant" and msg.get("tool_calls"):
            content_parts = []
            text_content = msg.get("content", "")
            if text_content:
                content_parts.append({"type": "text", "text": text_content})
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args = _repair_json_args(args_str) or {}
                content_parts.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "input": args,
                })
            converted.append({"role": "assistant", "content": content_parts})
            i += 1
            tool_results: dict[str, str] = {}
            while i < len(messages) and messages[i].get("role") == "tool":
                tid = messages[i].get("tool_call_id", "")
                tool_results[tid] = messages[i].get("content", "")
                i += 1
            if tool_results:
                result_parts = []
                for tid, content in tool_results.items():
                    result_parts.append({"type": "tool_result", "tool_use_id": tid, "content": content})
                converted.append({"role": "user", "content": result_parts})
        elif role == "tool":
            i += 1
        else:
            converted.append(msg)
            i += 1

    return _convert_openai_images_to_anthropic(converted)


async def _stream_anthropic(
    api_key: str,
    model: str,
    system: str,
    messages: list,
) -> AsyncGenerator[str, None]:
    if anthropic is None:
        raise RuntimeError("anthropic 库未安装，请 pip install anthropic")
    client = anthropic.AsyncAnthropic(api_key=api_key)
    extra: dict = {}
    if "opus" in model:
        extra["thinking"] = {"type": "adaptive"}

    converted_messages = _convert_openai_images_to_anthropic(messages)

    async with client.messages.stream(
        model=model,
        max_tokens=8192,
        system=system,
        messages=converted_messages,
        **extra,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_anthropic_with_tools(
    api_key: str,
    model: str,
    system: str,
    messages: list,
    tools: list,
    tool_choice: str = "auto",
) -> AsyncGenerator[dict, None]:
    """Anthropic 工具调用流式支持。

    yield 事件格式与 stream_with_tools 一致：
      - {"type": "text", "content": "..."}
      - {"type": "tool_calls", "calls": [...]}
      - {"type": "done"}
    """
    if anthropic is None:
        yield {"type": "text", "content": "⚠️ anthropic 库未安装，请 pip install anthropic"}
        yield {"type": "done"}
        return

    client = anthropic.AsyncAnthropic(api_key=api_key)

    anthropic_tools = _convert_openai_tools_to_anthropic(tools)
    converted_messages = _convert_openai_messages_to_anthropic_tool_messages(messages)

    extra: dict = {}
    if "opus" in model:
        extra["thinking"] = {"type": "adaptive"}

    tc_param: dict = {"type": "auto"}
    if tool_choice == "required":
        tc_param = {"type": "tool", "name": tools[0]["function"]["name"]} if tools else {"type": "any"}
    elif tool_choice == "auto":
        tc_param = {"type": "auto"}

    tool_call_id_counter = 0
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=8192,
            system=system,
            messages=converted_messages,
            tools=anthropic_tools,
            tool_choice=tc_param if anthropic_tools else anthropic.NOT_GIVEN,
            **extra,
        ) as stream:
            current_tool_id = ""
            current_tool_name = ""
            current_tool_input = ""
            text_buffer = ""

            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool_id = event.content_block.id
                        current_tool_name = event.content_block.name
                        current_tool_input = ""
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        text_buffer += event.delta.text
                        yield {"type": "text", "content": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        current_tool_input += event.delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool_id and current_tool_name:
                        try:
                            args = json.loads(current_tool_input) if current_tool_input else {}
                        except json.JSONDecodeError:
                            args = _repair_json_args(current_tool_input) or {}
                        tool_call_id_counter += 1
                        call_id = current_tool_id or f"call_anthropic_{tool_call_id_counter}"
                        yield {
                            "type": "tool_calls",
                            "calls": [{
                                "id": call_id,
                                "name": current_tool_name,
                                "arguments": args,
                                "raw_arguments": current_tool_input,
                            }],
                        }
                        current_tool_id = ""
                        current_tool_name = ""
                        current_tool_input = ""

        yield {"type": "done"}
    except Exception as e:
        yield {"type": "text", "content": f"\n\n[Anthropic 调用失败: {str(e)[:300]}]"}
        yield {"type": "done"}
