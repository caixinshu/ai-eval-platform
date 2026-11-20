"""数据集与用例模型"""
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from backend.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)          # golden / edge / adversarial
    description = Column(Text)
    case_count = Column(Integer, default=0)
    version = Column(String(20), default="v1")
    created_at = Column(TIMESTAMP, server_default=func.now())


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(String(50), primary_key=True)
    dataset_id = Column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"),
                        nullable=False)
    question = Column(Text, nullable=False)
    ground_truth = Column(Text)
    category = Column(String(50))
    difficulty = Column(String(20))
    tags = Column(JSON)
    expected_behavior = Column(JSON)
    expected_context = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())
