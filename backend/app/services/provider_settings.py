"""AI 提供商配置管理：设置读写、自定义模型 CRUD、provider 解析。"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

DEBUG_LOG_ENABLED = False

# 本应用仅支持自定义模型，不再内置厂商。此处保留空字典以兼容既有 import 与返回结构。
PROVIDERS: dict = {}

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
    # 仅支持自定义模型；此处保留设置文件中的 api_keys（通常为空）作为兼容兜底
    return settings.get("api_keys", {}).get(provider, "")


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


def _resolve_current_provider(settings: dict) -> Tuple[str, str, str, str]:
    provider = settings.get("provider", "")
    model = settings.get("model", "")
    api_key = get_api_key(provider, settings)

    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return _resolve_base_url(cm), api_key, cm.get("model_id", "") or model, "openai_compat"
        return "", api_key, model, "openai_compat"

    # CUSTOM_PROVIDER_KEY 或任何非自定义 provider：一律按 OpenAI 兼容对待
    custom_cfg = settings.get("custom", {})
    return custom_cfg.get("base_url", ""), api_key, custom_cfg.get("model", "") or model, "openai_compat"


def _get_context_input(settings: dict) -> int:
    provider = settings.get("provider", "")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_input") or 128000)
    # 仅支持自定义模型；默认 128K
    return 128000


def _get_context_output(settings: dict) -> int:
    provider = settings.get("provider", "")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        if cm:
            return int(cm.get("context_output") or 8192)
    return 8192


def is_current_model_multimodal(settings: dict) -> bool:
    provider = settings.get("provider", "")
    if provider.startswith(f"{CUSTOM_PROVIDER_KEY}:"):
        cm = get_custom_model(provider, settings)
        return bool(cm and cm.get("multimodal"))
    return False
