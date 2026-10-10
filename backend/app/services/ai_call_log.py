"""AI 调用日志服务：异步写入、查询、统计。"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional

from ..schemas.ai_call_log import AICallLog
from ..services.resume_db import SessionLocal

_logger = logging.getLogger("autoresume.ai_call_log")


class AICallLogger:
    """异步 AI 调用日志记录器：内存缓冲 + 后台批量写入。"""

    def __init__(self, flush_interval: float = 2.0, buffer_size: int = 200):
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._lock = Lock()
        self._flush_interval = flush_interval
        self._flush_task: Optional[asyncio.Task] = None
        self._recent: deque[dict] = deque(maxlen=1000)

    def start(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._periodic_flush())
        except RuntimeError:
            pass

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            self._flush_to_db()

    def begin(self, *, source: str, provider: str, model: str, prompt_chars: int = 0, request_summary: str = "") -> str:
        call_id = uuid.uuid4().hex[:16]
        entry = {
            "call_id": call_id,
            "source": source,
            "provider": provider,
            "model": model,
            "status": "pending",
            "prompt_chars": prompt_chars,
            "response_chars": 0,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "latency_ms": None,
            "error_message": None,
            "request_summary": request_summary[:2000] if request_summary else None,
            "response_summary": None,
            "start_time": time.monotonic(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._buffer.append(entry)
        return call_id

    def finish(self, call_id: str, *, response_chars: int = 0, prompt_tokens: int = None, completion_tokens: int = None, total_tokens: int = None, response_summary: str = "", error: str = None) -> None:
        with self._lock:
            for entry in reversed(self._buffer):
                if entry.get("call_id") == call_id:
                    entry["status"] = "error" if error else "success"
                    entry["response_chars"] = response_chars
                    entry["prompt_tokens"] = prompt_tokens
                    entry["completion_tokens"] = completion_tokens
                    entry["total_tokens"] = total_tokens
                    entry["latency_ms"] = round((time.monotonic() - entry["start_time"]) * 1000, 1)
                    entry["error_message"] = error[:1000] if error else None
                    entry["response_summary"] = response_summary[:2000] if response_summary else None
                    self._recent.append({k: v for k, v in entry.items() if k != "start_time"})
                    break

    def _flush_to_db(self) -> None:
        with self._lock:
            pending = [e for e in self._buffer if e.get("status") != "pending"]
            if not pending:
                return
            self._buffer.clear()

        db = SessionLocal()
        try:
            for e in pending:
                row = AICallLog(
                    source=e["source"],
                    provider=e["provider"],
                    model=e["model"],
                    status=e["status"],
                    prompt_chars=e.get("prompt_chars"),
                    response_chars=e.get("response_chars"),
                    prompt_tokens=e.get("prompt_tokens"),
                    completion_tokens=e.get("completion_tokens"),
                    total_tokens=e.get("total_tokens"),
                    latency_ms=e.get("latency_ms"),
                    error_message=e.get("error_message"),
                    request_summary=e.get("request_summary"),
                    response_summary=e.get("response_summary"),
                )
                db.add(row)
            db.commit()
        except Exception as exc:
            _logger.warning("AI 调用日志写入失败: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    def flush(self) -> None:
        self._flush_to_db()

    def get_recent(self, limit: int = 100, source: str = None, offset: int = 0) -> List[dict]:
        db = SessionLocal()
        try:
            q = db.query(AICallLog).order_by(AICallLog.created_at.desc())
            if source:
                q = q.filter(AICallLog.source == source)
            rows = q.offset(offset).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "source": r.source,
                    "provider": r.provider,
                    "model": r.model,
                    "status": r.status,
                    "prompt_chars": r.prompt_chars,
                    "response_chars": r.response_chars,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "latency_ms": r.latency_ms,
                    "error_message": r.error_message,
                    "request_summary": r.request_summary,
                    "response_summary": r.response_summary,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            db.close()

    def get_stats(self, days: int = 7) -> Dict:
        db = SessionLocal()
        try:
            from sqlalchemy import text, func as sa_func
            since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            since = since - timedelta(days=days)

            total = db.query(AICallLog).filter(AICallLog.created_at >= since).count()
            success = db.query(AICallLog).filter(AICallLog.created_at >= since, AICallLog.status == "success").count()
            error = db.query(AICallLog).filter(AICallLog.created_at >= since, AICallLog.status == "error").count()

            by_source = db.execute(
                text("SELECT source, COUNT(*) as cnt, AVG(latency_ms) as avg_latency, "
                     "SUM(COALESCE(prompt_tokens,0)) as total_prompt_tokens, "
                     "SUM(COALESCE(completion_tokens,0)) as total_completion_tokens "
                     "FROM ai_call_logs WHERE created_at >= :since GROUP BY source ORDER BY cnt DESC"),
                {"since": since}
            ).fetchall()

            sources = [
                {
                    "source": r[0],
                    "count": r[1],
                    "avg_latency_ms": round(r[2], 1) if r[2] else 0,
                    "total_prompt_tokens": r[3] or 0,
                    "total_completion_tokens": r[4] or 0,
                }
                for r in by_source
            ]

            return {
                "days": days,
                "total_calls": total,
                "success_calls": success,
                "error_calls": error,
                "by_source": sources,
            }
        finally:
            db.close()


ai_call_logger = AICallLogger()


def init_ai_call_log_db() -> None:
    from ..schemas.ai_call_log import AICallLog
    from ..services.resume_db import engine, Base as _Base
    from sqlalchemy import text
    _Base.metadata.create_all(bind=engine, tables=[AICallLog.__tablename__] if hasattr(AICallLog, '__tablename__') else [])
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source VARCHAR(64) NOT NULL,
                provider VARCHAR(128) NOT NULL DEFAULT '',
                model VARCHAR(128) NOT NULL DEFAULT '',
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                prompt_chars INTEGER,
                response_chars INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                latency_ms FLOAT,
                error_message TEXT,
                request_summary TEXT,
                response_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_call_logs_source ON ai_call_logs (source)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_call_logs_created_at ON ai_call_logs (created_at)"))
