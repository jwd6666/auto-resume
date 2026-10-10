"""AI 调用日志 SQLAlchemy ORM 模型：记录所有 LLM API 调用的详细信息。"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.sql import func

from ..services.resume_db import Base


class AICallLog(Base):
    __tablename__ = "ai_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(64), nullable=False, index=True)
    provider = Column(String(128), nullable=False, default="")
    model = Column(String(128), nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending")
    prompt_chars = Column(Integer, nullable=True)
    response_chars = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    request_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
