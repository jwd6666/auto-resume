"""
文件系统安全辅助模块。

所有涉及路径的工具都应经过 resolve_path 进行规范化与工作区约束校验：
- 将相对路径转绝对路径，resolve 掉 ../ 与符号链接，防止目录穿越。
- 若配置了工作区根目录（LOCAL_EDIT_WORKSPACE），则禁止访问其外部文件。
"""
from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ENV = "LOCAL_EDIT_WORKSPACE"


def workspace_root() -> Path | None:
    env = os.environ.get(WORKSPACE_ENV)
    if not env:
        return None
    root = Path(env).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_path(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    root = workspace_root()
    if root is not None:
        try:
            rel = p.relative_to(root)
        except ValueError:
            raise WorkspaceError(
                f"路径 {p} 超出工作区 {root}，为安全已拒绝。"
                f"请使用工作区内的相对/绝对路径。"
            )
        if str(rel).startswith(".."):
            raise WorkspaceError(f"路径 {p} 不可访问")
    return p


class WorkspaceError(Exception):
    """路径超出允许的工作区范围。"""
