"""简历 Agent 独立数据库（SQLAlchemy ORM），与主项目 sqlite3 完全隔离。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import RESUME_DB_PATH

engine = create_engine(
    f"sqlite:///{RESUME_DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_resume_db() -> None:
    """建表 + 兼容迁移（复制自 one_jd_one_resume/backend/main.py 的迁移逻辑）。"""
    from ..schemas.resume_models import Base as _Base  # noqa: F401
    _Base.metadata.create_all(bind=engine)

    from sqlalchemy import text
    with engine.begin() as conn:
        # jobs 表补字段
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        cols = [r[1] for r in result]
        if "status" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN status VARCHAR(32) DEFAULT 'pending'"))
        if "job_url" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN job_url VARCHAR(500)"))
        if "salary" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary VARCHAR(128)"))
        if "competency_profile" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN competency_profile VARCHAR(80) DEFAULT 'default'"))
        if "enabled" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN enabled BOOLEAN DEFAULT 1"))
        if "location" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN location VARCHAR(128)"))
        if "job_type" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN job_type VARCHAR(64)"))

        # user_backgrounds 补 name
        result_bg = conn.execute(text("PRAGMA table_info(user_backgrounds)"))
        bg_cols = [r[1] for r in result_bg]
        if "name" not in bg_cols:
            conn.execute(text("ALTER TABLE user_backgrounds ADD COLUMN name VARCHAR(200) DEFAULT '默认'"))
            conn.execute(text("UPDATE user_backgrounds SET name = '默认' WHERE name IS NULL OR name = ''"))

        # job_interview_questions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS job_interview_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                resume_id INTEGER,
                background_profile_id INTEGER,
                category VARCHAR(100) NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """))
        result_q = conn.execute(text("PRAGMA table_info(job_interview_questions)"))
        q_cols = [r[1] for r in result_q]
        if "resume_id" not in q_cols:
            conn.execute(text("ALTER TABLE job_interview_questions ADD COLUMN resume_id INTEGER"))
        if "background_profile_id" not in q_cols:
            conn.execute(text("ALTER TABLE job_interview_questions ADD COLUMN background_profile_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_interview_questions_job_id ON job_interview_questions (job_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_interview_questions_resume_id ON job_interview_questions (resume_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_interview_questions_background_profile_id ON job_interview_questions (background_profile_id)"))

        # job_conversations
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS job_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL UNIQUE,
                messages TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_conversations_job_id ON job_conversations (job_id)"))

        # evaluation_reports
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS evaluation_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                resume_id INTEGER,
                report_type VARCHAR(50) NOT NULL DEFAULT 'scorecard',
                content_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_evaluation_reports_job_id ON evaluation_reports (job_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_evaluation_reports_resume_id ON evaluation_reports (resume_id)"))

        # resumes 补字段
        result_r = conn.execute(text("PRAGMA table_info(resumes)"))
        r_cols = [rr[1] for rr in result_r]
        if "background_profile_id" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN background_profile_id INTEGER"))
        if "angle" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN angle VARCHAR(200)"))
        if "structured" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN structured TEXT"))
        if "enabled" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN enabled BOOLEAN DEFAULT 1"))
        if "file_type" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN file_type VARCHAR(16)"))
        if "file_size" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN file_size INTEGER"))
        if "rendered_html" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN rendered_html TEXT"))
        if "current_template" not in r_cols:
            conn.execute(text("ALTER TABLE resumes ADD COLUMN current_template VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_resumes_background_profile_id ON resumes (background_profile_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_resumes_job_id ON resumes (job_id)"))
