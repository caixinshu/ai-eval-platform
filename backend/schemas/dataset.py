"""数据集相关契约"""
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern="^(golden|edge|adversarial)$")
    description: Optional[str] = None
    version: str = "v1"


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    description: Optional[str] = None
    case_count: int
    version: str


class CaseIn(BaseModel):
    id: str
    question: str = Field(min_length=1)
    ground_truth: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    expected_behavior: Optional[Any] = None
    expected_context: Optional[Any] = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    ground_truth: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[Any] = None
    expected_behavior: Optional[Any] = None


class UploadResult(BaseModel):
    dataset_id: str
    imported: int
    skipped: int
    case_count: int
