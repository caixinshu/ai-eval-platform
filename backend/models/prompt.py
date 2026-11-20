"""Prompt 版本模型：版本只增不改，保证历史评测可复现"""
from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from backend.database import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    version = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
