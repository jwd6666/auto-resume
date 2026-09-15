"""OpenAI 兼容提供商适配：流式调用、JSON 参数修复。"""
from __future__ import annotations

import json
import re
from typing import AsyncGenerator

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore


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


def _repair_json_args(raw: str) -> dict | None:
    """尝试修复模型返回的非法 JSON arguments（DeepSeek 等模型常见问题）。

    常见问题：
    1. 字符串值内含未转义的换行/引号
    2. 缺少闭合引号或大括号
    3. 截断（流式输出提前结束）
    """
    if not raw or not raw.strip():
        return None

    s = raw.strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    depth = 0
    in_str = False
    escape = False
    last_safe_end = 0
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_str:
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[:i + 1])
                except json.JSONDecodeError:
                    pass
        elif ch == ',':
            last_safe_end = i

    if last_safe_end > 0:
        truncated = s[:last_safe_end]
        depth = 0
        for ch in truncated:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
        closing = '}' * max(depth, 1)
        try:
            return json.loads(truncated + closing)
        except json.JSONDecodeError:
            pass

    try:
        result = {}
        i = 0
        while i < len(s):
            kv_match = re.search(r'"(\w+)"\s*:\s*', s[i:])
            if not kv_match:
                break
            key = kv_match.group(1)
            val_start = i + kv_match.end()

            if val_start >= len(s):
                break

            ch = s[val_start]
            if ch == '"':
                val_start += 1
                end = val_start
                while end < len(s):
                    if s[end] == '\\':
                        end += 2
                        continue
                    if s[end] == '"':
                        break
                    end += 1
                if end < len(s):
                    val_raw = s[val_start:end]
                    result[key] = val_raw
                    i = end + 1
                else:
                    result[key] = s[val_start:]
                    break
            elif ch == '{':
                end = val_start + 1
                d = 1
                while end < len(s) and d > 0:
                    if s[end] == '{':
                        d += 1
                    elif s[end] == '}':
                        d -= 1
                    end += 1
                try:
                    result[key] = json.loads(s[val_start:end])
                except json.JSONDecodeError:
                    result[key] = s[val_start:end]
                i = end
            elif ch in ('t', 'f'):
                bool_end = s.find(',', val_start)
                if bool_end == -1:
                    bool_end = s.find('}', val_start)
                if bool_end == -1:
                    bool_end = len(s)
                bool_str = s[val_start:bool_end].strip()
                result[key] = bool_str == "true"
                i = bool_end
            elif ch.isdigit() or ch == '-':
                num_end = s.find(',', val_start)
                if num_end == -1:
                    num_end = s.find('}', val_start)
                if num_end == -1:
                    num_end = len(s)
                num_str = s[val_start:num_end].strip()
                try:
                    result[key] = int(num_str)
                except ValueError:
                    try:
                        result[key] = float(num_str)
                    except ValueError:
                        result[key] = num_str
                i = num_end
            elif ch == 'n':
                result[key] = None
                i = val_start + 4
            else:
                i = val_start + 1

        if result:
            return result
    except Exception:
        pass

    return None
