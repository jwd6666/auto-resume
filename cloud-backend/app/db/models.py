"""ORM 模型：User。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(64), default="")
    # user / admin
    role: Mapped[str] = mapped_column(String(16), default="user")
    # active / banned
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 个人每日 token 额度覆盖（NULL=跟随整体默认额度）
    daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ModelTemplate(Base):
    """管理员预定义的模型模板，用户客户端可拉取并一键导入。"""

    __tablename__ = "model_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(128))
    api_format: Mapped[str] = mapped_column(String(32), default="openai")
    base_url: Mapped[str] = mapped_column(String(512))
    full_url: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[str] = mapped_column(String(256))
    multimodal: Mapped[bool] = mapped_column(Boolean, default=False)
    model_series: Mapped[str] = mapped_column(String(64), default="")
    api_key: Mapped[str] = mapped_column(String(512), default="")
    context_input: Mapped[int] = mapped_column(Integer, default=128000)
    context_output: Mapped[int] = mapped_column(Integer, default=4096)
    tool_call_rounds: Mapped[int] = mapped_column(Integer, default=3)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Release(Base):
    """客户端版本：下载走外部链接（官网/网盘），云端只管版本号、日志与发布状态。"""

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    download_url: Mapped[str] = mapped_column(String(1024))
    # 强制更新：客户端横幅不可关闭
    force: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class SystemSetting(Base):
    """系统级键值配置（如整体默认日额度），管理后台可改、重启不丢。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class UserUsage(Base):
    """每用户每日云端模型 token 用量（配额记账，按 UTC 日重置）。

    tokens 为「预留 + 结转」后的累计值：请求准入前预留 输入估算+max_tokens，
    请求结束后按服务商 usage 或估算结转为实际用量；上游报错全额退还。
    """

    __tablename__ = "user_usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_user_usage_user_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # UTC 日期 "YYYY-MM-DD"
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
