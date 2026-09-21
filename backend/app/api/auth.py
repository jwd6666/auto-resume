"""本地鉴权路由：登录/登出/状态查询（转发到云端）。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.cloud_auth import CloudAuthError, cloud_auth
from ..core.config import CLOUD_SERVER_URL

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    account: str = Field(min_length=3, max_length=64)
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/login")
async def login(body: LoginBody) -> dict:
    try:
        return await cloud_auth.login(body.account, body.password)
    except CloudAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/logout")
async def logout() -> dict:
    return await cloud_auth.logout()


@router.get("/status")
async def status() -> dict:
    return cloud_auth.snapshot()


@router.get("/cloud-models")
async def cloud_models() -> list[dict]:
    """代理：从云端拉取已发布的模型模板列表。"""
    token = cloud_auth.current_token()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CLOUD_SERVER_URL}/client/models",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="云端模型拉取失败")
        templates = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"无法连接云端：{e}")
    # 缓存模板能力信息（multimodal 等），供本地 is_current_model_multimodal 判断云端模型
    try:
        from ..services.provider_settings import load_settings, save_settings
        settings = load_settings()
        settings["cloud_models"] = templates
        save_settings(settings)
    except Exception:
        pass
    return templates


@router.post("/cloud-activate")
async def cloud_activate(body: dict) -> dict:
    """激活云端官方模型：设置 provider 为 cloud:<template_id>。"""
    template_id = body.get("template_id")
    if template_id is None:
        raise HTTPException(status_code=400, detail="template_id 必填")
    provider = f"cloud:{template_id}"
    from ..services.provider_settings import load_settings, save_settings
    settings = load_settings()
    settings["provider"] = provider
    settings["model"] = ""
    save_settings(settings)
    return {"ok": True, "provider": provider}


@router.post("/change-password")
async def change_password(body: ChangePasswordBody) -> dict:
    """代理：修改当前登录用户的密码（转发到云端）。"""
    token = cloud_auth.current_token()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{CLOUD_SERVER_URL}/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={"old_password": body.old_password, "new_password": body.new_password},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"无法连接云端：{e}")
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail") or "密码修改失败"
        except Exception:
            detail = "密码修改失败"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()
