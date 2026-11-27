"""线上反馈与抽样评测记录（Day 24）"""
from sqlalchemy import Column, Index, Integer, Numeric, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from backend.database import Base


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id = Column(String(36), primary_key=True)
    request_id = Column(String(64), nullable=False, index=True)
    question = Column(Text)
    answer = Column(Text)
    rating = Column(String(10), nullable=False)          # good / bad
    reason = Column(String(50))                          # 不准确/不相关/太啰嗦/有害
    comment = Column(Text)
    issue_category = Column(String(30))                  # 5 类自动归类 + other
    user_id = Column(String(64))
    biz_line = Column(String(50))
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_feedback_rating_created", "rating", "created_at"),
    )


class OnlineSample(Base):
    __tablename__ = "online_samples"

    id = Column(String(36), primary_key=True)
    request_id = Column(String(64), nullable=False, index=True)
    question = Column(Text)
    answer = Column(Text)
    score = Column(Numeric(5, 2), nullable=False)        # 0-100
    biz_line = Column(String(50))
    latency_ms = Column(Integer)
    sampled_at = Column(TIMESTAMP, server_default=func.now(), index=True)
