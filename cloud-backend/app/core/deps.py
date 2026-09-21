"""依赖注入：从请求解析 JWT → 当前用户。"""
from __future__ import annotations

import datetime as dt

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..core.security import decode_token
from ..db.database import SessionLocal
from ..db.models import User


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _extract_token(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    return authorization[len("Bearer "):]


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(authorization)
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.status == "banned":
        raise HTTPException(status_code=403, detail=f"账户已被禁用：{user.ban_reason or '违规使用'}")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()
