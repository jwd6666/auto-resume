"""
文件 hash 与乐观锁校验工具。

核心思路：Agent 每次 view 后对文件内容得到一份"快照"，并在调用 str_replace 时携带该
快照对应的 expected_hash (md5)。执行前比对磁盘文件的当前 md5：
- 一致  -> 说明磁盘内容还是 Agent 所 view 的那份，可以安全修改。
- 不一致 -> 说明磁盘文件已被其它进程/会话改动，直接报错，要求 Agent 重新 view 获取最新内容。
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_hash(path: str | Path) -> str:
    """读取文件内容并计算 md5 十六进制摘要。

    以二进制方式读取，避免换行符（\r\n / \n）或字符编码差异造成基线漂移，
    保证"磁盘真实字节内容"与 Agent 端 hash 严格一致。
    """
    data = Path(path).read_bytes()
    return hashlib.md5(data).hexdigest()


def verify_hash(path: str | Path, expected_hash: str | None) -> str | None:
    """
    校验磁盘文件的当前 hash 是否等于 expected_hash（乐观锁）。

    Args:
        path: 目标文件路径。
        expected_hash: Agent 调用工具时携带的期望 md5；为 None 时跳过校验（仅在显式
            允许跳过乐观锁的场景使用，例如首次创建文件）。

    Returns:
        current_hash: 磁盘上的当前 md5。

    Raises:
        HashMismatchError: 磁盘 hash 与 expected_hash 不一致，
            说明文件已被改动，禁止继续修改。
    """
    current_hash = compute_hash(path)

    if expected_hash is not None and current_hash != expected_hash:
        raise HashMismatchError(
            f"乐观锁校验失败 (HashMismatch): 文件 {path} 已被外部修改。\n"
            f"  expected_hash = {expected_hash}\n"
            f"  current_hash  = {current_hash}\n"
            f"请重新调用 view 读取最新内容，再基于最新快照进行修改。"
        )
    return current_hash


class HashMismatchError(Exception):
    """文件 hash 不一致导致乐观锁冲突。"""