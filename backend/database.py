"""数据库连接与会话管理"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import DATABASE_URL

if DATABASE_URL.startswith("sqlite"):
    os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")), exist_ok=True)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求一个会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """开发期自动建表；生产用 sql/schema.sql 迁移"""
    from backend.models import dataset, feedback, prompt, run  # noqa: F401  注册模型
    Base.metadata.create_all(engine)
    _migrate_sqlite()


def _migrate_sqlite():
    """SQLite 开发库轻量迁移：create_all 不会给已有表加列，这里补齐新增字段"""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(eval_runs)")]
        if "cancel_requested" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE eval_runs ADD COLUMN cancel_requested BOOLEAN DEFAULT 0")
