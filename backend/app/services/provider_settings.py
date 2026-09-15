"""AI 提供商配置管理：内置 provider 定义、设置读写、自定义模型 CRUD、provider 解析。"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEBUG_LOG_ENABLED = False

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
    "custom": {
        "base_url": "",
        "api_key": "",
        "model": "",
    },
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
    if not provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        return None
    model_id = provider.split(":", 1)[1]
    for cm in settings.get("custom_models", []):
        if cm.get("id") == model_id:
            return cm
    return None


def add_custom_model(data: dict, settings: dict) -> dict:
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
    custom_models: List[dict] = settings.get("custom_models", [])
    before = len(custom_models)
    settings["custom_models"] = [cm for cm in custom_models if cm.get("id") != model_id]
    deleted = len(settings["custom_models"]) != before
    if deleted:
        if settings.get("provider") == f"{CUSTOM_PROVIDER_KEY}:{model_id}":
            settings["provider"] = _DEFAULT_SETTINGS["provider"]
            settings["model"] = _DEFAULT_SETTINGS["model"]
        save_settings(settings)
    return deleted


def update_custom_model(model_id: str, data: dict, settings: dict) -> Optional[dict]:
    custom_models: List[dict] = settings.get("custom_models", [])
    target: Optional[dict] = None
    for cm in custom_models:
        if cm.get("id") == model_id:
            target = cm
            break
    if not target:
        return None

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

    new_key = data.get("api_key")
    if new_key is not None:
        new_key_str = (new_key or "").strip()
        if new_key_str and new_key_str != "••••••":
            target["api_key"] = new_key_str

    save_settings(settings)
    return target


def _resolve_base_url(cm: dict) -> str:
    url = (cm.get("base_url") or "").strip().rstrip("/")
    if cm.get("full_url"):
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        return url
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


def _resolve_current_provider(settings: dict) -> Tuple[str, str, str, str]:
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
    provider = settings.get("provider", "")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_input") or 128000)
    if provider == CUSTOM_PROVIDER_KEY:
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
    provider = settings.get("provider", "anthropic")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_output") or 8192)
    return 8192


def is_current_model_multimodal(settings: dict) -> bool:
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
