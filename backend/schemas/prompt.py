"""Prompt 版本契约"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1)
    description: Optional[str] = None


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    description: Optional[str] = None
    content: str
