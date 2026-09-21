"""FastAPI 入口。Electron 在开发期通过 npm run dev:py 启动，
生产期由主进程作为 sidecar 启动。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.tasks import router as tasks_router
from .api.resume_agent import router as resume_agent_router
from .api.auth import router as auth_router
from .api.updates import router as updates_router
from .core.auth_middleware import CloudAuthMiddleware
from .core.cloud_auth import cloud_auth
from .services import storage
from .services.task_manager import manager
from .services.resume_db import init_resume_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    init_resume_db()
    await manager.init()
    await cloud_auth.restore_session()
    yield


app = FastAPI(title="auto-resume backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(CloudAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    # 仅放行本应用的两个加载来源：
    # - "null"：生产模式 Electron 通过 file:// 加载 renderer（Origin 头为 null）
    # - Vite dev server：开发期（浏览器直开 / Electron loadURL）
    allow_origins=["null", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(resume_agent_router, prefix="/agent")
app.include_router(updates_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
