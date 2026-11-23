"""评测任务、用例结果、指标快照"""
from sqlalchemy import (JSON, Boolean, Column, ForeignKey, Integer, Numeric,
                        String, Text, TIMESTAMP)
from sqlalchemy.sql import func

from backend.database import Base


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(String(36), primary_key=True)
    dataset_id = Column(String(36), ForeignKey("datasets.id"))
    prompt_version = Column(String(20), nullable=False)
    model_name = Column(String(100))
    judge_model = Column(String(100))
    status = Column(String(20), default="pending")     # pending/running/done/failed/cancelled
    cancel_requested = Column(Boolean, default=False)  # 前端点取消置 True，执行循环逐条检查
    progress = Column(Integer, default=0)
    total_cases = Column(Integer)
    total_score = Column(Numeric(5, 2))
    error_message = Column(Text)
    started_at = Column(TIMESTAMP, server_default=func.now())
    finished_at = Column(TIMESTAMP)


class EvalResult(Base):
    __tablename__ = "eval_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("eval_runs.id", ondelete="CASCADE"),
                    nullable=False)
    case_id = Column(String(50))
    question = Column(Text)
    answer = Column(Text)
    contexts = Column(JSON)
    metrics = Column(JSON)
    rule_details = Column(JSON)
    passed = Column(Boolean)
    duration_ms = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("eval_runs.id", ondelete="CASCADE"),
                    nullable=False)
    metric_name = Column(String(50), nullable=False)
    value = Column(Numeric(8, 4), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
