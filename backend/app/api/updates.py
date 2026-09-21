"""更新检查路由：状态查询、偏好设置、手动触发检查。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.cloud_auth import cloud_auth
from ..core.updates import update_service

router = APIRouter(prefix="/api/updates", tags=["updates"])


class UpdateSettingsBody(BaseModel):
    # 关闭/开启更新提示（设置页开关）
    prompt_enabled: bool | None = None
    # 跳过指定版本（"不再提醒此版本"），传空字符串清除
    skip_version: str | None = None


@router.get("/check")
async def check() -> dict:
    return update_service.status()


@router.put("/settings")
async def put_settings(body: UpdateSettingsBody) -> dict:
    settings = update_service.save_settings(
        prompt_enabled=body.prompt_enabled,
        skip_version=body.skip_version,
    )
    return {"ok": True, "settings": settings}


@router.post("/check-now")
async def check_now() -> dict:
    """立即向云端拉取一次最新版本（供前端「检查更新」按钮）。"""
    token = cloud_auth.current_token()
    if token:
        await update_service.check_once(token)
    return update_service.status()
