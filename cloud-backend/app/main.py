"""云端后端入口：用户认证 + 心跳 + 管理后台 API。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parents[1]

from .api.admin import router as admin_router
from .api.auth import router as auth_router
from .api.models import admin_router as model_admin_router, client_router as model_client_router
from .api.releases import admin_router as release_admin_router, client_router as release_client_router
from .db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="auto-resume cloud", version="0.1.0", lifespan=lifespan)

# 桌面客户端本地 sidecar 转发请求，管理后台是浏览器直连，均需放开 CORS
# 生产部署请将 origins 收紧为实际域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(model_admin_router)
app.include_router(model_client_router)
app.include_router(release_admin_router)
app.include_router(release_client_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "auto-resume-cloud"}


@app.get("/")
async def index() -> FileResponse:
    """首页：显示服务信息和入口链接。"""
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    """管理后台（浏览器直接访问）。"""
    return FileResponse(BASE_DIR / "static" / "admin.html")
