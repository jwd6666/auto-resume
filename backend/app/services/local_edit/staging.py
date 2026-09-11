"""
暂存区（staging）模块 — 按 resume_id 分桶。

每个 resume_id 拥有独立的 StagingStore，防止不同简历的编辑互相干扰。
str_replace 在暂存区生成新内容而不直接覆盖磁盘，apply 后才落地。
"""
from __future__ import annotations

from pathlib import Path


class StagingStore:
    def __init__(self) -> None:
        self._pending: dict[str, str] = {}

    def has_pending(self, path: str | Path) -> bool:
        return str(Path(path).resolve()) in self._pending

    def get_pending(self, path: str | Path) -> str | None:
        return self._pending.get(str(Path(path).resolve()))

    def current_content(self, path: str | Path) -> str | None:
        resolved = str(Path(path).resolve())
        if resolved in self._pending:
            return self._pending[resolved]
        p = Path(path)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8", errors="replace")

    def stage(self, path: str | Path, new_content: str) -> None:
        self._pending[str(Path(path).resolve())] = new_content

    def pending_items(self) -> dict[str, str]:
        return dict(self._pending)

    def discard(self, path: str | Path | None = None) -> int:
        if path is None:
            count = len(self._pending)
            self._pending.clear()
        else:
            key = str(Path(path).resolve())
            count = 1 if key in self._pending else 0
            self._pending.pop(key, None)
        return count

    def apply_all(self, write_func) -> dict:
        applied: list[str] = []
        for path, content in self._pending.items():
            write_func(Path(path), content)
            applied.append(path)
        self._pending.clear()
        return {"applied": applied, "count": len(applied)}


class StagingManager:
    def __init__(self) -> None:
        self._stores: dict[int, StagingStore] = {}

    def get_store(self, resume_id: int) -> StagingStore:
        if resume_id not in self._stores:
            self._stores[resume_id] = StagingStore()
        return self._stores[resume_id]

    def clear_store(self, resume_id: int) -> None:
        self._stores.pop(resume_id, None)


_manager = StagingManager()


def get_staging(resume_id: int) -> StagingStore:
    return _manager.get_store(resume_id)


def clear_staging(resume_id: int) -> None:
    _manager.clear_store(resume_id)
