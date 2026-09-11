"""简历 Agent 多 AI 提供商抽象层（复制自 one_jd_one_resume/backend/providers.py）。

设置文件路径：backend/app/ai_settings.json
.env 文件路径：backend/.env
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import HTTPException

# 延迟导入 anthropic / openai，避免未安装时主项目启动崩溃
try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

PROVIDERS: dict = {
    "anthropic": {
        "name": "Anthropic Claude",
        "name_cn": "Claude",
        "type": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-6",   "name": "Claude Opus 4.6 (最强)", "multimodal": True},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (均衡)", "multimodal": True},
            {"id": "claude-haiku-4-5",  "name": "Claude Haiku 4.5 (快速)", "multimodal": True},
        ],
        "default_model": "claude-opus-4-6",
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "name_cn": "通义千问",
        "type": "openai_compat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "models": [
            {"id": "qwen-max",         "name": "Qwen Max (最强)", "multimodal": True},
            {"id": "qwen-plus",        "name": "Qwen Plus (均衡)"},
            {"id": "qwen-turbo",       "name": "Qwen Turbo (快速)"},
            {"id": "qwen-long",        "name": "Qwen Long (长文本)"},
            {"id": "qwen3-235b-a22b",  "name": "Qwen3-235B (最新)", "multimodal": True},
            {"id": "qwen3-32b",        "name": "Qwen3-32B"},
        ],
        "default_model": "qwen-plus",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "name_cn": "智谱",
        "type": "openai_compat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "models": [
            {"id": "glm-4-plus",  "name": "GLM-4-Plus (旗舰)", "multimodal": True},
            {"id": "glm-4",       "name": "GLM-4", "multimodal": True},
            {"id": "glm-4-flash", "name": "GLM-4-Flash (快速免费)", "multimodal": True},
            {"id": "glm-4-air",   "name": "GLM-4-Air"},
            {"id": "glm-z1-plus", "name": "GLM-Z1-Plus (推理)"},
        ],
        "default_model": "glm-4-flash",
    },
    "deepseek": {
        "name": "DeepSeek",
        "name_cn": "DeepSeek",
        "type": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "models": [
            {"id": "deepseek-chat",     "name": "DeepSeek V3 (对话)"},
            {"id": "deepseek-reasoner", "name": "DeepSeek R1 (推理)"},
        ],
        "default_model": "deepseek-chat",
    },
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "name_cn": "Kimi",
        "type": "openai_compat",
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "MOONSHOT_API_KEY",
        "models": [
            {"id": "moonshot-v1-128k", "name": "Moonshot 128K (推荐)"},
            {"id": "moonshot-v1-32k",  "name": "Moonshot 32K"},
            {"id": "moonshot-v1-8k",   "name": "Moonshot 8K (快速)"},
        ],
        "default_model": "moonshot-v1-128k",
    },
    "baidu": {
        "name": "百度文心 (ERNIE)",
        "name_cn": "文心",
        "type": "openai_compat",
        "base_url": "https://qianfan.baidubce.com/v2",
        "env_key": "QIANFAN_API_KEY",
        "models": [
            {"id": "ernie-4.0-8k",          "name": "ERNIE 4.0 (旗舰)", "multimodal": True},
            {"id": "ernie-4.0-turbo-8k",     "name": "ERNIE 4.0 Turbo"},
            {"id": "ernie-3.5-8k",           "name": "ERNIE 3.5"},
            {"id": "ernie-speed-128k",        "name": "ERNIE Speed (长文本)"},
        ],
        "default_model": "ernie-4.0-turbo-8k",
    },
}

# 自定义 provider 的固定 key
CUSTOM_PROVIDER_KEY = "custom"

def _settings_file_path() -> str:
    data_dir = os.environ.get("AUTORESUME_DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        target = os.path.join(data_dir, "ai_settings.json")
        if not os.path.exists(target):
            bundled = os.path.join(os.path.dirname(__file__), "ai_settings.json")
            if os.path.exists(bundled):
                import shutil
                shutil.copy2(bundled, target)
        return target
    return os.path.join(os.path.dirname(__file__), "ai_settings.json")

SETTINGS_FILE = _settings_file_path()

_DEFAULT_SETTINGS = {
    "provider": "",
    "model": "",
    "api_keys": {k: "" for k in PROVIDERS},
    # 自定义模型配置（单模型，向后兼容）
    "custom": {
        "base_url": "",
        "api_key": "",
        "model": "",
    },
    # 多自定义模型列表
    "custom_models": [],
}


def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings = dict(_DEFAULT_SETTINGS)
            settings.update(saved)
            settings["api_keys"] = {**_DEFAULT_SETTINGS["api_keys"], **saved.get("api_keys", {})}
            if "custom_models" not in settings:
                settings["custom_models"] = []
            return settings
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_api_key(provider: str, settings: dict) -> str:
    if provider == CUSTOM_PROVIDER_KEY:
        return settings.get("custom", {}).get("api_key", "")
    # 多自定义模型：provider 形如 "custom:<id>"
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return cm.get("api_key", "")
        return ""
    key_from_settings = settings.get("api_keys", {}).get(provider, "")
    if key_from_settings:
        return key_from_settings
    env_var = PROVIDERS.get(provider, {}).get("env_key", "")
    return os.environ.get(env_var, "")


def get_custom_model(provider: str, settings: dict) -> Optional[dict]:
    """根据 provider key（形如 'custom:<id>'）从 custom_models 列表中查找配置。"""
    if not provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        return None
    model_id = provider.split(":", 1)[1]
    for cm in settings.get("custom_models", []):
        if cm.get("id") == model_id:
            return cm
    return None


def add_custom_model(data: dict, settings: dict) -> dict:
    """新增一个自定义模型并持久化。data 由调用方传入（含明文 api_key）。"""
    custom_models: List[dict] = settings.setdefault("custom_models", [])
    new_model = {
        "id": data.get("id") or uuid.uuid4().hex[:12],
        "api_format": data.get("api_format", "openai_chat"),
        "base_url": (data.get("base_url") or "").strip(),
        "full_url": bool(data.get("full_url", False)),
        "model_id": (data.get("model_id") or "").strip(),
        "multimodal": bool(data.get("multimodal", False)),
        "api_key": (data.get("api_key") or "").strip(),
        "model_series": data.get("model_series", "default"),
        "display_name": (data.get("display_name") or "").strip(),
        "context_input": int(data.get("context_input") or 0),
        "context_output": int(data.get("context_output") or 0),
        "tool_call_rounds": int(data.get("tool_call_rounds") or 0),
    }
    custom_models.append(new_model)
    save_settings(settings)
    return new_model


def delete_custom_model(model_id: str, settings: dict) -> bool:
    """删除一个自定义模型，返回是否删除成功。"""
    custom_models: List[dict] = settings.get("custom_models", [])
    before = len(custom_models)
    settings["custom_models"] = [cm for cm in custom_models if cm.get("id") != model_id]
    deleted = len(settings["custom_models"]) != before
    if deleted:
        # 如果当前选中的正是被删除的模型，回退到默认 provider
        if settings.get("provider") == f"{CUSTOM_PROVIDER_KEY}:{model_id}":
            settings["provider"] = _DEFAULT_SETTINGS["provider"]
            settings["model"] = _DEFAULT_SETTINGS["model"]
        save_settings(settings)
    return deleted


def update_custom_model(model_id: str, data: dict, settings: dict) -> Optional[dict]:
    """更新一个自定义模型。api_key 为空或 '••••••' 时保留原值，其它字段仅更新提供的字段。"""
    custom_models: List[dict] = settings.get("custom_models", [])
    target: Optional[dict] = None
    for cm in custom_models:
        if cm.get("id") == model_id:
            target = cm
            break
    if not target:
        return None

    # 普通字段：仅更新显式提供的字段
    field_map = {
        "api_format": str,
        "base_url": lambda v: (v or "").strip(),
        "full_url": bool,
        "model_id": lambda v: (v or "").strip(),
        "multimodal": bool,
        "model_series": str,
        "display_name": lambda v: (v or "").strip(),
        "context_input": int,
        "context_output": int,
        "tool_call_rounds": int,
    }
    for field, cast in field_map.items():
        if field in data and data[field] is not None:
            try:
                target[field] = cast(data[field])
            except (TypeError, ValueError):
                pass

    # api_key 特殊处理：空 / 掩码 / 未提供 → 保留原值；非空且非掩码 → 更新
    new_key = data.get("api_key")
    if new_key is not None:
        new_key_str = (new_key or "").strip()
        if new_key_str and new_key_str != "••••••":
            target["api_key"] = new_key_str

    save_settings(settings)
    return target


def _resolve_base_url(cm: dict) -> str:
    """根据 full_url 开关计算最终请求根地址（去掉 /chat/completions 后缀，供 OpenAI SDK 使用）。"""
    url = (cm.get("base_url") or "").strip().rstrip("/")
    if cm.get("full_url"):
        # 用户填写的是完整 URL，SDK 会自动拼 /chat/completions，需去掉
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        return url
    # 非 full_url 模式：用户填的是根地址，去掉末尾斜杠即可
    return url


def sync_env_file(updates: Dict[str, str]) -> None:
    if not updates:
        return
    to_write: Dict[str, str] = {}
    for provider, value in updates.items():
        if provider not in PROVIDERS:
            continue
        env_var = PROVIDERS[provider].get("env_key", "")
        if not env_var:
            continue
        to_write[env_var] = (value or "").strip()
    if not to_write:
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    written = set()
    new_lines = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m and m.group(1) in to_write:
            env_var = m.group(1)
            new_lines.append(f"{env_var}={to_write[env_var]}")
            written.add(env_var)
        else:
            new_lines.append(line)
    for env_var, val in to_write.items():
        if env_var not in written:
            new_lines.append(f"{env_var}={val}")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _convert_openai_images_to_anthropic(messages: list) -> list:
    """将 OpenAI 格式的 image_url content 转换为 Anthropic 格式。
    OpenAI: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    Anthropic: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
    """
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
    # 用户可能填了完整地址（含 /chat/completions），OpenAI SDK 只需要根地址
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
        # 流式中途出错时，将错误信息作为文本返回，不 re-raise
        # 这样调用方 generator 正常结束，前端不会 "Failed to fetch"
        yield f"\n\n[流式输出中断: {str(e)[:200]}]"


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

    # 多自定义模型：provider 形如 "custom:<id>"
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


def _resolve_current_provider(settings: dict) -> Tuple[str, str, str, str]:
    """解析当前配置：返回 (base_url, api_key, model_id, provider_type)。

    provider_type: "anthropic" | "openai_compat"
    base_url: OpenAI 兼容根地址（anthropic 时为空）
    """
    provider = settings.get("provider", "anthropic")
    model = settings.get("model", PROVIDERS.get("anthropic", {}).get("default_model", ""))
    api_key = get_api_key(provider, settings)

    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return _resolve_base_url(cm), api_key, cm.get("model_id", "") or model, "openai_compat"
        return "", api_key, model, "openai_compat"

    if provider == CUSTOM_PROVIDER_KEY:
        custom_cfg = settings.get("custom", {})
        return custom_cfg.get("base_url", ""), api_key, custom_cfg.get("model", "") or model, "openai_compat"

    pconfig = PROVIDERS.get(provider)
    if not pconfig:
        return "", api_key, model, "openai_compat"

    if pconfig["type"] == "anthropic":
        return "", api_key, model, "anthropic"

    return pconfig.get("base_url", ""), api_key, model, "openai_compat"


def _get_context_input(settings: dict) -> int:
    """获取当前模型的输入 token 上限（context window）。

    自定义模型使用其 context_input 配置；内置模型按 provider 默认值。
    """
    provider = settings.get("provider", "")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_input") or 128000)
    if provider == CUSTOM_PROVIDER_KEY:
        custom_cfg = settings.get("custom", {})
        return 128000
    _PROVIDER_DEFAULTS = {
        "anthropic": 200000,
        "qwen": 131072,
        "zhipu": 128000,
        "deepseek": 128000,
        "moonshot": 131072,
        "baidu": 128000,
    }
    return _PROVIDER_DEFAULTS.get(provider, 128000)


def _get_context_output(settings: dict) -> int:
    """获取当前模型的输出 token 上限。

    自定义模型使用其 context_output 配置；内置模型默认 8192。
    """
    provider = settings.get("provider", "anthropic")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_output") or 8192)
    return 8192


def is_current_model_multimodal(settings: dict) -> bool:
    """判断当前选中的模型是否支持多模态（内置提供商模型或自定义模型）。"""
    provider = settings.get("provider", "")
    model_id = settings.get("model", "")

    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        return bool(cm and cm.get("multimodal"))

    if provider == CUSTOM_PROVIDER_KEY:
        return False

    pconfig = PROVIDERS.get(provider)
    if pconfig:
        for m in pconfig.get("models", []):
            if m.get("id") == model_id:
                return bool(m.get("multimodal"))

    return False


def complete_response_sync(system: str, messages: list, *, max_tokens: int = 8192, timeout: float = 600.0) -> str:
    """同步调用当前模型管理配置的模型，返回完整文本。供 resume_parser 等同步场景使用。"""
    settings = load_settings()
    base_url, api_key, model_id, provider_type = _resolve_current_provider(settings)
    # 按模型 context_output 上限截断 max_tokens，避免超出 API 限制
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

    # openai_compat
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
    """为 SSE 生成器添加心跳保活。

    当上游超过 interval 秒无数据时，发送 ``: keepalive\\n\\n`` 注释行，
    防止浏览器/代理因空闲超时断开连接。
    """
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

    # 多自定义模型：provider 形如 "custom:<id>"
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


# ── 工具调用流式支持 ────────────────────────────────────────

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

    # 尝试 1：直接解析
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 尝试 2：补全截断的 JSON — 找到最后一个完整的 key:value 对
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

    # 尝试 3：在最后一个安全逗号处截断，补全闭合括号
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

    # 尝试 4：暴力修复 — 用正则提取 key-value 对
    try:
        result = {}
        kv_pattern = re.compile(r'"(\w+)"\s*:\s*"')
        pos = 0
        while pos < len(s):
            m = kv_pattern.search(s, pos)
            if not m:
                break
            key = m.group(1)
            val_start = m.end()
            # 找到值的结束位置（未转义的引号）
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
                pos = end + 1
            else:
                # 未闭合的字符串 — 取剩余部分
                result[key] = s[val_start:]
                break
        if result:
            return result
    except Exception:
        pass

    return None

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

    tool_calls 格式：
      [{"id": "call_xxx", "name": "write_file", "arguments": {"path": "...", "content": "..."}}]

    调用方负责执行工具、把结果追加到 messages、再发起下一轮流式。
    """
    settings = load_settings()
    provider = settings.get("provider", "anthropic")
    model = settings.get("model", PROVIDERS["anthropic"]["default_model"])
    api_key = get_api_key(provider, settings)

    if not api_key:
        yield {"type": "text", "content": "⚠️ 未配置当前所选模型的 API Key，请在「模型管理」中填写。"}
        yield {"type": "done"}
        return

    # 解析 base_url（复用 stream_response 的逻辑）
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
            # Anthropic 工具调用格式不同，暂不支持，回退到纯文本
            async for text in _stream_anthropic(api_key, model, system, messages):
                yield {"type": "text", "content": text}
            yield {"type": "done"}
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

    async def _run_once(tool_choice_val: str):
        """执行一次流式工具调用，产出 text / tool_calls / done 事件。"""
        # 累积 tool_calls（按 index 分组，因为分块到达）
        tool_call_acc: Dict[int, dict] = {}
        stream = await client.chat.completions.create(
            model=model,
            messages=openai_messages,
            stream=True,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice_val,
        )
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # 文本
                if delta.content:
                    yield {"type": "text", "content": delta.content}

                # tool_calls 分块累积
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

                # finish_reason
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

    # 某些 provider（如 DeepSeek）不支持 tool_choice="required"，
    # 若指定了 required 且首次调用失败，则退一步用 "auto" 重试，保证工具调用可用。
    attempts = ["required", "auto"] if tool_choice == "required" else [tool_choice]
    last_err: Optional[Exception] = None
    for attempt in attempts:
        try:
            async for event in _run_once(attempt):
                yield event
            return
        except Exception as e:
            last_err = e
            continue

    # 多次尝试均失败：若模型本身不支持工具调用，则退回纯文本流
    msg = str(last_err)
    if "tool" in msg.lower() or "function" in msg.lower() or "unspported" in msg.lower() or "not support" in msg.lower():
        async for text in _stream_openai_compat(base_url, api_key, model, system, messages, max_tokens):
            yield {"type": "text", "content": text}
        yield {"type": "done"}
        return
    yield {"type": "text", "content": f"\n\n[API 调用失败: {msg[:300]}]"}
    yield {"type": "done"}
    return

