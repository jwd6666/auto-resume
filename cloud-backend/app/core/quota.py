"""每用户每日云端模型 token 配额：原子预留 + 事后按实际用量结转。

计费流程：
1. 请求准入前，按「输入估算 + max_tokens」预留配额（INSERT OR IGNORE +
   单条条件 UPDATE，SQLite 单写者模型下原子生效，并发请求不会超卖）
2. 请求结束后，用服务商返回的 usage.total_tokens 结转为实际用量；
   无 usage 时退回字符估算；上游报错全额退还
3. 配额按 UTC 日期重置（每天一行新记录）
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.config import DAILY_TOKEN_QUOTA
from ..db.database import SessionLocal


def today_str() -> str:
    """UTC 日期字符串（配额按此重置）。"""
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def estimate_request_tokens(
    messages: list[dict], tools: list[dict] | None, max_tokens: int
) -> tuple[int, int]:
    """粗估单次请求的最坏消耗，返回 (预留总量, 输入估算)。

    中文约 1.5~2 字符/token、英文约 4 字符/token，取 /2 折中；
    估算仅用于准入预留，最终按服务商 usage 结转，误差会被修正。
    """
    chars = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            # 多模态 content：只统计文本部分；图片按固定额度预留（最终按服务商 usage 结转修正），
            # 避免把 base64 字符数当 token 估算导致单次预留爆掉日配额
            for part in content:
                if isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        chars += len(part["text"])
                    elif isinstance(part.get("image_url"), (str, dict)):
                        chars += 2000
        else:
            chars += len(str(m))
    if tools:
        chars += sum(len(json.dumps(t, ensure_ascii=False)) for t in tools)
    est_input = max(1, (chars + 1) // 2)
    return est_input + max_tokens, est_input


def reserve_tokens(db: Session, user_id: int, amount: int, day: str | None = None) -> tuple[bool, int]:
    """预留配额，返回 (是否成功, 当日已用 tokens)。

    UPDATE 带 `tokens + :amt <= :cap` 守卫，单条语句原子生效：
    并发请求中没有一个能把 tokens 推过上限，不会超卖。
    """
    day = day or today_str()
    db.execute(
        text("INSERT OR IGNORE INTO user_usage (user_id, day, tokens, requests) VALUES (:u, :d, 0, 0)"),
        {"u": user_id, "d": day},
    )
    db.commit()
    result = db.execute(
        text(
            "UPDATE user_usage SET tokens = tokens + :amt, requests = requests + 1 "
            "WHERE user_id = :u AND day = :d AND tokens + :amt <= :cap"
        ),
        {"amt": amount, "u": user_id, "d": day, "cap": DAILY_TOKEN_QUOTA},
    )
    db.commit()
    used = db.execute(
        text("SELECT tokens FROM user_usage WHERE user_id = :u AND day = :d"),
        {"u": user_id, "d": day},
    ).scalar()
    return result.rowcount == 1, int(used or 0)


def reconcile_tokens(user_id: int, day: str, reserved: int, actual: int) -> None:
    """请求结束后结转：把预留值替换为实际用量。

    使用独立会话执行：流式响应的收尾（含客户端断开）可能发生在
    请求级依赖会话关闭之后。
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE user_usage SET tokens = tokens - :reserved + :actual "
                "WHERE user_id = :u AND day = :d"
            ),
            {"reserved": reserved, "actual": actual, "u": user_id, "d": day},
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def fallback_actual_tokens(data: dict, est_input: int) -> int:
    """非流式响应缺少 usage 时的兜底估算。"""
    try:
        message = (data.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        extra = sum(len(json.dumps(tc, ensure_ascii=False)) for tc in tool_calls)
        return est_input + (len(str(content)) + extra + 1) // 2
    except Exception:
        return est_input
