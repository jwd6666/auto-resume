"""
暂存区（staging）模块。

核心设计：str_replace 并不直接覆盖磁盘文件。它只是在内存中对"当前基线内容"做替换，
生成 diff 预览，并把结果暂存在暂存区中。用户点击 Apply 后，才将暂存的新内容落地写入磁盘。

暂存区维护的是"文件路径 -> 待写入内容"的映射。之所以不直接用磁盘做基线：
- 磁盘是用户工作区，Agent 的多次小改动之间需要保持一致、可叠加、可整体确认或丢弃。
- 每次 str_replace 前都必须重新校验磁盘 hash（乐观锁），防止旧快照改到新文件。

提供关键操作:
- get_current_content(path): 返回该文件"当前工作内容"，优先取暂存内容，否则读磁盘。
- stage_edit(path, new_content): 将一次替换结果暂存起来（不落盘）。
- apply_all(): 用户确认后，把所有暂存内容写回磁盘字符串。
- discard(): 丢弃全部暂存改动。
"""
from __future__ import annotations

from pathlib import Path


class StagingStore:
    """进程内暂存区，保存尚未 apply 的编辑。"""

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}

    def has_pending(self, path: str | Path) -> bool:
        return str(Path(path).resolve()) in self._pending

    def get_pending(self, path: str | Path) -> str | None:
        return self._pending.get(str(Path(path).resolve()))

    def current_content(self, path: str | Path) -> str | None:
        """返回当前应生效的内容：暂存优先，否则读磁盘（返回 None 表示文件不存在）。"""
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
        """将全部暂存好的内容批量写入磁盘。write_func(path, content) 回调。"""
        applied: list[str] = []
        for path, content in self._pending.items():
            write_func(Path(path), content)
            applied.append(path)
        self._pending.clear()
        return {"applied": applied, "count": len(applied)}


# 全局暂存区（单例，供各工具共享）
_staging = StagingStore()


def get_staging() -> StagingStore:
    return _staging