"""Pydantic 请求/响应模型。"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    account: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    account: str
    nickname: str
    role: str
    status: str
    ban_reason: str | None = None
    # 个人每日 token 额度覆盖（None=跟随整体默认额度）
    daily_token_quota: int | None = None
    created_at: dt.datetime
    last_login_at: dt.datetime | None = None
    last_heartbeat_at: dt.datetime | None = None


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class HeartbeatResponse(BaseModel):
    ok: bool
    status: str
    ban_reason: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class CreateUserRequest(BaseModel):
    account: str = Field(min_length=3, max_length=64)
    password: str = Field(default="123456", min_length=1, max_length=128)
    nickname: str = ""


class UpdateUserRequest(BaseModel):
    nickname: str | None = None
    password: str | None = Field(default=None, min_length=1, max_length=128)


class BanRequest(BaseModel):
    reason: str = ""


class QuotaUpdateRequest(BaseModel):
    """token 日额度调整；daily_token_quota=null 表示清除、回退整体默认。"""

    daily_token_quota: int | None = Field(default=None, ge=1, le=10_000_000_000)


class ReleaseOut(BaseModel):
    id: int
    version: str
    notes: str
    download_url: str
    force: bool
    published: bool
    created_at: dt.datetime
    published_at: dt.datetime | None = None


class ReleaseCreateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32, pattern=r"^\d+(\.\d+){0,3}(-[\w.]+)?$")
    notes: str = ""
    download_url: str = Field(min_length=1, max_length=1024)
    force: bool = False


class ReleaseUpdateRequest(BaseModel):
    notes: str | None = None
    download_url: str | None = Field(default=None, min_length=1, max_length=1024)
    force: bool | None = None


class PublishRequest(BaseModel):
    published: bool = True


class ModelTemplateOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: int
    display_name: str
    api_format: str
    base_url: str
    full_url: bool
    model_id: str
    multimodal: bool
    model_series: str
    api_key_set: bool = False
    context_input: int
    context_output: int
    tool_call_rounds: int
    published: bool
    sort_order: int
    created_at: dt.datetime
    updated_at: dt.datetime | None = None


class ModelTemplateClientOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: int
    display_name: str
    api_format: str
    full_url: bool
    model_id: str
    multimodal: bool
    model_series: str
    context_input: int
    context_output: int
    tool_call_rounds: int
    sort_order: int


class ModelTemplateCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    display_name: str = Field(min_length=1, max_length=128)
    api_format: str = Field(default="openai", max_length=32)
    base_url: str = Field(min_length=1, max_length=512)
    full_url: bool = False
    model_id: str = Field(min_length=1, max_length=256)
    multimodal: bool = False
    model_series: str = Field(default="", max_length=64)
    api_key: str = Field(default="", max_length=512)
    context_input: int = 128000
    context_output: int = 4096
    tool_call_rounds: int = 3
    published: bool = False
    sort_order: int = 0


class ModelTemplateUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    display_name: str | None = Field(default=None, max_length=128)
    api_format: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=512)
    full_url: bool | None = None
    model_id: str | None = Field(default=None, max_length=256)
    multimodal: bool | None = None
    model_series: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=512)
    context_input: int | None = None
    context_output: int | None = None
    tool_call_rounds: int | None = None
    published: bool | None = None
    sort_order: int | None = None
