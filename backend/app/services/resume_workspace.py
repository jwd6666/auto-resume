"""简历工作空间：磁盘文件存储 + WebSocket 文件变更推送。

存储路径：{RESUME_STORE_DIR}/{resume_id}/resume.html
AI agent 通过 read_file / write_file 工具直接操作磁盘上的简历 HTML 文件，
前端通过 WebSocket 监听文件变更并自动刷新预览。
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import WebSocket

from ..core.config import RESUME_STORE_DIR


def resume_dir(resume_id: int) -> Path:
    """简历磁盘目录。"""
    return RESUME_STORE_DIR / str(resume_id)


def resume_file_path(resume_id: int) -> Path:
    """简历 HTML 在磁盘上的路径。"""
    return resume_dir(resume_id) / "resume.html"


def ensure_resume_file(resume_id: int, html: Optional[str]) -> Path:
    """确保磁盘文件存在；若不存在且 DB 有 html，则写入。返回文件路径。"""
    p = resume_file_path(resume_id)
    if not p.exists() and html:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    return p


def read_resume_file(resume_id: int) -> str:
    """读取简历文件内容。文件不存在时返回空串。"""
    p = resume_file_path(resume_id)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def write_resume_file(resume_id: int, content: str) -> Path:
    """写入简历文件并广播变更通知。返回文件路径。"""
    p = resume_file_path(resume_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_manager.broadcast(resume_id, {
                "type": "file_changed",
                "resume_id": resume_id,
                "path": str(p),
            }))
        else:
            loop.run_until_complete(_manager.broadcast(resume_id, {
                "type": "file_changed",
                "resume_id": resume_id,
                "path": str(p),
            }))
    except RuntimeError:
        pass
    return p


def delete_resume_dir(resume_id: int) -> bool:
    """删除简历磁盘目录（含 resume.html 及所有附属资源）。返回是否成功。"""
    d = resume_dir(resume_id)
    if d.exists():
        try:
            shutil.rmtree(d)
            return True
        except Exception:
            return False
    return True


class ResumeWorkspaceManager:
    """简历工作空间 WebSocket 连接管理器（单例）。"""

    def __init__(self) -> None:
        self._subscribers: Dict[int, List[WebSocket]] = {}

    def subscribe(self, resume_id: int, ws: WebSocket) -> None:
        self._subscribers.setdefault(resume_id, []).append(ws)

    def unsubscribe(self, resume_id: int, ws: WebSocket) -> None:
        subs = self._subscribers.get(resume_id)
        if subs and ws in subs:
            subs.remove(ws)

    async def broadcast(self, resume_id: int, message: dict) -> None:
        subs = self._subscribers.get(resume_id, [])
        dead: List[WebSocket] = []
        for ws in subs:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(resume_id, ws)


_manager = ResumeWorkspaceManager()


def get_workspace_manager() -> ResumeWorkspaceManager:
    return _manager
