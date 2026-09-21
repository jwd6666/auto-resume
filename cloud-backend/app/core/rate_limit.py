"""登录限流：滑动窗口统计失败次数，超限后临时锁定（防账号爆破）。

- 按 ip + 账号 维度统计登录失败
- 窗口内失败达到阈值 → 锁定一段时间，期间直接拒绝（429）
- 登录成功清除该 key 的失败记录
- 进程内存实现（MVP 单实例部署足够；多实例部署需换 Redis）
"""
from __future__ import annotations

import threading
import time

# 失败统计窗口：15 分钟内
FAIL_WINDOW_SECONDS = 15 * 60
# 窗口内允许的最大失败次数
MAX_FAILS = 5
# 超限后的锁定时长
LOCK_SECONDS = 10 * 60

_lock = threading.Lock()
# key -> (失败时间戳列表, 锁定截止时间；0 表示未锁定)
_records: dict[str, tuple[list[float], float]] = {}


def _now() -> float:
    return time.monotonic()


def check_locked(key: str) -> int:
    """返回剩余锁定秒数；0 表示未锁定。"""
    with _lock:
        rec = _records.get(key)
        if rec is None:
            return 0
        fails, locked_until = rec
        now = _now()
        if locked_until > now:
            return int(locked_until - now) + 1
        if locked_until > 0:
            # 锁定刚到期：清空失败记录，重新计数
            _records[key] = ([], 0.0)
        return 0


def record_fail(key: str) -> None:
    """记录一次登录失败；窗口内失败达到阈值则进入锁定。"""
    now = _now()
    with _lock:
        fails, locked_until = _records.get(key, ([], 0.0))
        if locked_until > now:
            return
        fails = [t for t in fails if now - t < FAIL_WINDOW_SECONDS]
        fails.append(now)
        if len(fails) >= MAX_FAILS:
            _records[key] = ([], now + LOCK_SECONDS)
        else:
            _records[key] = (fails, 0.0)


def record_success(key: str) -> None:
    """登录成功：清除该 key 的失败记录。"""
    with _lock:
        _records.pop(key, None)
