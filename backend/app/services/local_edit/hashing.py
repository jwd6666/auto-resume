"""
文件 hash 与乐观锁校验工具。

Agent 每次 read_file 后获得文件的 md5 快照，在调用 patch_file 时携带 expected_hash。
执行前比对磁盘文件的当前 md5：
- 一致 → 可以安全修改
- 不一致 → 文件已被外部改动，报错要求重新读取
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_hash(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.md5(data).hexdigest()


def verify_hash(path: str | Path, expected_hash: str | None) -> str | None:
    current_hash = compute_hash(path)
    if expected_hash is not None and current_hash != expected_hash:
        raise HashMismatchError(
            f"乐观锁校验失败 (HashMismatch): 文件 {path} 已被外部修改。\n"
            f"  expected_hash = {expected_hash}\n"
            f"  current_hash  = {current_hash}\n"
            f"请重新调用 read_file 读取最新内容，再基于最新快照进行修改。"
        )
    return current_hash


class HashMismatchError(Exception):
    """文件 hash 不一致导致乐观锁冲突。"""
