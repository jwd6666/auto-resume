"""配置：从环境变量 / .env 加载。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

# 历史上存在过的内置默认密钥：继续视为未配置（防止老部署带着弱密钥跑在生产）
_LEGACY_INSECURE_SECRETS = ("dev-secret-do-not-use-in-prod",)

JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET or JWT_SECRET in _LEGACY_INSECURE_SECRETS:
    raise RuntimeError(
        "JWT_SECRET 未配置或仍为内置弱密钥，服务拒绝启动。"
        "请在 cloud-backend/.env 中设置随机密钥，生成方式："
        'python -c "import secrets; print(secrets.token_hex(32))"'
    )
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_SECONDS: int = int(os.environ.get("JWT_EXPIRE_SECONDS", "604800"))  # 7 天

DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'cloud.db'}")

# 每用户每日云端模型 token 配额（/client/models/chat 代理调用按此限额，防止刷爆管理员 API Key 账单）
# 按 UTC 日期重置
DAILY_TOKEN_QUOTA: int = int(os.environ.get("DAILY_TOKEN_QUOTA", "500000"))

HOST: str = os.environ.get("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", "8000"))
