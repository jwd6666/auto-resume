"""简历 Agent SQLAlchemy 模型（复制自 one_jd_one_resume/backend/models.py）。"""
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..services.resume_db import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    resumes = relationship("Resume", back_populates="job", cascade="all, delete-orphan")
    interview_questions = relationship(
        "JobInterviewQuestion",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    structured = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=True, default=True)
    file_type = Column(String(16), nullable=True)
    file_size = Column(Integer, nullable=True)
    version = Column(Integer, default=1)
    background_profile_id = Column(
        Integer,
        ForeignKey("user_backgrounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    angle = Column(String(200), nullable=True)
    rendered_html = Column(Text, nullable=True)
    current_template = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    job = relationship("Job", back_populates="resumes")
    conversations = relationship("Conversation", back_populates="resume", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    messages = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    resume = relationship("Resume", back_populates="conversations")


class JobConversation(Base):
    __tablename__ = "job_conversations"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    messages = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    job = relationship("Job")


class EvaluationReport(Base):
    __tablename__ = "evaluation_reports"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True)
    report_type = Column(String(50), nullable=False, default="scorecard")
    content_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class JobInterviewQuestion(Base):
    __tablename__ = "job_interview_questions"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True, index=True)
    background_profile_id = Column(
        Integer,
        ForeignKey("user_backgrounds.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    category = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="interview_questions")


class UserBackground(Base):
    __tablename__ = "user_backgrounds"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, default="默认")
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

