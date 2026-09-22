"""管理后台 API：用户列表 / 创建 / 封禁 / 解封 / 改密 / token 额度调整。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..core import quota
from ..core.config import DAILY_TOKEN_QUOTA
from ..core.deps import get_admin_user, get_db
from ..core.security import hash_password
from ..db.models import User, UserUsage
from ..schemas.auth import BanRequest, CreateUserRequest, QuotaUpdateRequest, UpdateUserRequest, UserOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])


@router.get("/users", response_model=dict)
def list_users(
    db: Session = Depends(get_db),
    keyword: str = Query(default="", description="按账号/昵称模糊搜索"),
    status: str = Query(default="", pattern="^(|active|banned)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((User.account.like(like)) | (User.nickname.like(like)))
    if status:
        q = q.filter(User.status == status)
    total = q.count()
    items = (
        q.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [UserOut.model_validate(u, from_attributes=True) for u in items],
    }


@router.post("/users", response_model=UserOut)
def create_user(body: CreateUserRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.account == body.account).first():
        raise HTTPException(status_code=400, detail="该账号已存在")
    user = User(
        account=body.account,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.account,
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user, from_attributes=True)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UpdateUserRequest, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/users/{user_id}/ban", response_model=UserOut)
def ban_user(user_id: int, body: BanRequest, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能封禁管理员")
    user.status = "banned"
    user.ban_reason = body.reason or "违规使用"
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/users/{user_id}/unban", response_model=UserOut)
def unban_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = "active"
    user.ban_reason = None
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user, from_attributes=True)


@router.delete("/users/{user_id}", response_model=dict)
def delete_user(user_id: int, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/quota", response_model=dict)
def get_quota_config(db: Session = Depends(get_db)):
    """整体默认日额度（未自定义时回退环境变量 DAILY_TOKEN_QUOTA）。"""
    value, customized = quota.global_quota_state(db)
    return {
        "global_quota": value,
        "customized": customized,
        "env_default": DAILY_TOKEN_QUOTA,
    }


@router.put("/quota", response_model=dict)
def update_quota_config(body: QuotaUpdateRequest, db: Session = Depends(get_db)):
    """提升/调整整体默认日额度；daily_token_quota=null 恢复环境变量默认。"""
    quota.set_global_quota(db, body.daily_token_quota)
    value, customized = quota.global_quota_state(db)
    return {"global_quota": value, "customized": customized, "env_default": DAILY_TOKEN_QUOTA}


@router.put("/users/{user_id}/quota", response_model=UserOut)
def update_user_quota(user_id: int, body: QuotaUpdateRequest, db: Session = Depends(get_db)):
    """调整个人每日 token 额度（当日即时生效）；null=清除个人额度、跟随整体默认。"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.daily_token_quota = body.daily_token_quota
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user, from_attributes=True)


@router.get("/stats", response_model=dict)
def stats(db: Session = Depends(get_db)):
    import datetime as dt
    from sqlalchemy import func
    total = db.query(User).count()
    banned = db.query(User).filter(User.status == "banned").count()
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    today_usage = db.query(func.sum(UserUsage.tokens), func.sum(UserUsage.requests)).filter(UserUsage.day == today).first()
    total_usage = db.query(func.sum(UserUsage.tokens), func.sum(UserUsage.requests)).first()
    return {
        "total_users": total,
        "banned_users": banned,
        "today_tokens": today_usage[0] or 0,
        "today_requests": today_usage[1] or 0,
        "total_tokens": total_usage[0] or 0,
        "total_requests": total_usage[1] or 0,
    }


@router.get("/usage", response_model=dict)
def list_usage(
    db: Session = Depends(get_db),
    day: str = Query(default="", description="UTC 日期 YYYY-MM-DD，空=今天"),
    user_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    import datetime as dt
    from sqlalchemy import func
    if not day:
        day = dt.datetime.utcnow().strftime("%Y-%m-%d")
    q = db.query(UserUsage).filter(UserUsage.day == day)
    if user_id is not None:
        q = q.filter(UserUsage.user_id == user_id)
    total = q.count()
    items = q.order_by(UserUsage.tokens.desc()).offset((page - 1) * page_size).limit(page_size).all()
    global_quota = quota.get_global_quota(db)
    result = []
    for u in items:
        user = db.get(User, u.user_id)
        override = user.daily_token_quota if user else None
        result.append({
            "user_id": u.user_id,
            "account": user.account if user else "unknown",
            "nickname": user.nickname if user else "",
            "day": u.day,
            "tokens": u.tokens,
            "requests": u.requests,
            # 当日生效额度：个人覆盖优先，否则跟随整体默认
            "quota": override or global_quota,
            "quota_override": override,
        })
    return {"total": total, "page": page, "page_size": page_size, "items": result}
