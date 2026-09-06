"""任务 REST 路由。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..core.logger import get_logger
from ..schemas.task import TaskCreate
from ..services import storage
from ..services.task_manager import manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks() -> dict:
    return {"items": manager.list()}


@router.post("")
async def create_task(payload: TaskCreate) -> dict:
    info = await manager.create(payload)
    return info.model_dump()


@router.get("/greeted-recent")
async def greeted_recent(days: int = 3) -> dict:
    return {"items": storage.list_greeted_recent(days)}


class BatchDeleteGreetedRequest(BaseModel):
    ids: List[int]


@router.post("/greeted-batch-delete")
async def batch_delete_greeted(req: BatchDeleteGreetedRequest) -> dict:
    deleted = storage.batch_delete_greeted(req.ids)
    return {"ok": True, "deleted": deleted}


@router.put("/{task_id}")
async def update_task(task_id: str, payload: TaskCreate) -> dict:
    """编辑任务：覆盖 sub_tasks/招呼语/间隔/上限/延迟等；运行中会先自动停止。"""
    try:
        info = await manager.update(task_id, payload)
        return info.model_dump()
    except KeyError:
        raise HTTPException(404, "task not found")


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict:
    rt = manager.get(task_id)
    if not rt: raise HTTPException(404, "task not found")
    return rt.to_dict()


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> dict:
    await manager.remove(task_id)
    return {"ok": True}


@router.post("/{task_id}/start")
async def start_task(task_id: str) -> dict:
    try:
        return await manager.start(task_id)
    except KeyError:
        raise HTTPException(404, "task not found")


@router.post("/{task_id}/login")
async def login_task(task_id: str) -> dict:
    """仅打开浏览器登录，登录后关闭浏览器并保存 cookie；不进入打招呼循环。"""
    try:
        return await manager.start_login(task_id)
    except KeyError:
        raise HTTPException(404, "task not found")


@router.post("/{task_id}/pause")
async def pause_task(task_id: str) -> dict:
    await manager.pause(task_id); return {"ok": True}


@router.post("/{task_id}/resume")
async def resume_task(task_id: str) -> dict:
    await manager.resume(task_id); return {"ok": True}


@router.post("/{task_id}/stop")
async def stop_task(task_id: str) -> dict:
    await manager.stop(task_id); return {"ok": True}


@router.get("/{task_id}/logs")
async def task_logs(task_id: str, n: int = 200) -> dict:
    return {"items": get_logger(task_id).tail(n)}


@router.get("/{task_id}/greeted")
async def task_greeted(task_id: str, limit: int = 100) -> dict:
    return {"items": storage.list_greeted_today(task_id, limit)}


@router.post("/{task_id}/reset-ai-judged")
async def reset_ai_judged(task_id: str) -> dict:
    """清除该任务今日所有 AI 判断缓存，让 AI 重新判断所有岗位。"""
    deleted = storage.reset_ai_judged(task_id)
    return {"ok": True, "deleted": deleted}


@router.websocket("/ws/{task_id}")
async def task_ws(ws: WebSocket, task_id: str) -> None:
    await ws.accept()
    if not manager.get(task_id):
        await ws.send_json({"type": "error", "msg": "task not found"})
        await ws.close(); return
    manager.subscribe(task_id, ws)
    try:
        await ws.send_json({"type": "snapshot", "task_id": task_id, "info": manager.get(task_id).to_dict(), "logs": get_logger(task_id).tail(200)})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(task_id, ws)
