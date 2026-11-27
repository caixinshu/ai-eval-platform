"""线上监控接口契约（Day 24）"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackIn(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1)
    answer: str = ""
    rating: Literal["good", "bad"]
    reason: Optional[str] = Field(default=None, max_length=50)
    comment: Optional[str] = Field(default=None, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=64)
    biz_line: Optional[str] = Field(default=None, max_length=50)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    rating: str
    reason: Optional[str] = None
    comment: Optional[str] = None
    issue_category: Optional[str] = None
    biz_line: Optional[str] = None
    created_at: Optional[datetime] = None


class SampleIn(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1)
    answer: str = ""
    score: float = Field(ge=0, le=100)
    biz_line: Optional[str] = Field(default=None, max_length=50)
    latency_ms: Optional[int] = Field(default=None, ge=0)


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_id: str
    score: float
    biz_line: Optional[str] = None
    sampled_at: Optional[datetime] = None
