"""评测任务契约"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    dataset_id: str
    prompt_version: str
    model: Optional[str] = None
    judge_model: Optional[str] = None
    concurrency: int = Field(default=3, ge=1, le=20)


class RunCreated(BaseModel):
    run_id: str
    status: str
    total_cases: int


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: Optional[str] = None
    prompt_version: str
    model_name: Optional[str] = None
    status: str
    progress: int
    total_cases: Optional[int] = None
    total_score: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class RunStatus(BaseModel):
    status: str
    progress: int
    processed: int
    total: int
    failed: int


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    question: Optional[str] = None
    answer: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    passed: Optional[bool] = None
    duration_ms: Optional[int] = None
    ground_truth: Optional[str] = None


class CompareRequest(BaseModel):
    run_id_a: str
    run_id_b: str


class CompareOut(BaseModel):
    total: Dict[str, Any]
    metrics: Dict[str, Dict[str, Any]]
    regressions: List[str]
    improvements: List[str]
