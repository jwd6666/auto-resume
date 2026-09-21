"""认证 API：登录 / 当前用户 / 心跳 / 修改密码。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core import rate_limit
from ..core.deps import get_current_user, get_db, utcnow
from ..db.models import User
from ..schemas.auth import (
    ChangePasswordRequest,
    HeartbeatResponse,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from ..core.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    limit_key = f"{ip}:{body.account}"
    remaining = rate_limit.check_locked(limit_key)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请约 {max(1, remaining // 60)} 分钟后再试",
        )
    user = db.query(User).filter(User.account == body.account).first()
    if user is None or not verify_password(body.password, user.password_hash):
        rate_limit.record_fail(limit_key)
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if user.status == "banned":
        raise HTTPException(status_code=403, detail=f"账户已被禁用：{user.ban_reason or '违规使用'}")
    rate_limit.record_success(limit_key)
    user.last_login_at = utcnow()
    user.last_heartbeat_at = utcnow()
    db.commit()
    token = create_token(user.id, user.role)
    return LoginResponse(token=token, user=UserOut.model_validate(user, from_attributes=True))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """客户端定时调用；封禁用户会在这里被 get_current_user 拦下（403）。"""
    user.last_heartbeat_at = utcnow()
    db.commit()
    return HeartbeatResponse(ok=True, status=user.status, ban_reason=None)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改自己的密码：需验证原密码；失败次数过多会被临时锁定。"""
    ip = request.client.host if request.client else "unknown"
    limit_key = f"{ip}:chpw:{user.id}"
    remaining = rate_limit.check_locked(limit_key)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"尝试次数过多，请约 {max(1, remaining // 60)} 分钟后再试",
        )
    if not verify_password(body.old_password, user.password_hash):
        rate_limit.record_fail(limit_key)
        raise HTTPException(status_code=400, detail="原密码错误")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    rate_limit.record_success(limit_key)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True, "message": "密码已更新"}
