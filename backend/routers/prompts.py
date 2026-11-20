"""Prompt 版本接口"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.prompt import PromptVersion
from backend.routers._common import api_error, paginate
from backend.schemas.prompt import PromptCreate, PromptOut

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
def list_prompts(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    result = paginate(
        db.query(PromptVersion).order_by(PromptVersion.created_at.desc()),
        page, page_size)
    result["items"] = [PromptOut.model_validate(p) for p in result["items"]]
    return result


@router.post("", status_code=201, response_model=PromptOut)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)):
    exists = db.query(PromptVersion).filter_by(
        name=payload.name, version=payload.version).first()
    if exists:
        api_error(409, "VERSION_CONFLICT",
                  "Prompt %s@%s 已存在，版本不可覆盖，请新建版本号"
                  % (payload.name, payload.version))
    prompt = PromptVersion(
        id="pv_" + uuid.uuid4().hex[:12], name=payload.name,
        version=payload.version, content=payload.content,
        description=payload.description)
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return PromptOut.model_validate(prompt)
