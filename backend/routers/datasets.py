"""数据集与用例接口"""
import json
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.dataset import Dataset, TestCase
from backend.routers._common import api_error, paginate
from backend.schemas.dataset import CaseIn, CaseOut, DatasetCreate, DatasetOut, UploadResult

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("")
def list_datasets(type: str = None, page: int = 1, page_size: int = 20,
                  db: Session = Depends(get_db)):
    query = db.query(Dataset)
    if type:
        query = query.filter(Dataset.type == type)
    result = paginate(query.order_by(Dataset.created_at.desc()), page, page_size)
    result["items"] = [DatasetOut.model_validate(d) for d in result["items"]]
    return result


@router.post("", status_code=201, response_model=DatasetOut)
def create_dataset(payload: DatasetCreate, db: Session = Depends(get_db)):
    exists = db.query(Dataset).filter_by(name=payload.name, version=payload.version).first()
    if exists:
        api_error(409, "VERSION_CONFLICT",
                  "数据集 %s@%s 已存在" % (payload.name, payload.version))
    ds = Dataset(id="ds_" + uuid.uuid4().hex[:12], name=payload.name,
                 type=payload.type, description=payload.description,
                 version=payload.version, case_count=0)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return DatasetOut.model_validate(ds)


@router.get("/{dataset_id}/cases")
def list_cases(dataset_id: str, category: str = None, page: int = 1,
               page_size: int = 20, db: Session = Depends(get_db)):
    if db.get(Dataset, dataset_id) is None:
        api_error(404, "NOT_FOUND", "数据集不存在: %s" % dataset_id)
    query = db.query(TestCase).filter_by(dataset_id=dataset_id)
    if category:
        query = query.filter(TestCase.category == category)
    result = paginate(query.order_by(TestCase.id), page, page_size)
    result["items"] = [CaseOut.model_validate(c) for c in result["items"]]
    return result


@router.post("/upload", response_model=UploadResult)
async def upload_cases(dataset_id: str = Query(...), file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        api_error(404, "NOT_FOUND", "数据集不存在: %s" % dataset_id)
    try:
        raw = json.loads((await file.read()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        api_error(422, "DATASET_INVALID", "文件不是合法 JSON")

    items = raw.get("cases", raw.get("items", [])) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        api_error(422, "DATASET_INVALID", "数据集应为数组或 {cases: [...]}")

    imported = skipped = 0
    seen = set()                      # 同一批文件内的重复 ID（尚未 flush 到库）
    for item in items:
        try:
            case = CaseIn(**item)
        except Exception:
            skipped += 1
            continue
        if case.id in seen or db.get(TestCase, case.id) is not None:
            skipped += 1
            continue
        seen.add(case.id)
        db.add(TestCase(
            id=case.id, dataset_id=dataset_id, question=case.question,
            ground_truth=case.ground_truth, category=case.category,
            difficulty=case.difficulty, tags=case.tags,
            expected_behavior=case.expected_behavior,
            expected_context=case.expected_context,
        ))
        imported += 1

    db.flush()                        # 让本批新增对 count 可见
    dataset.case_count = db.query(TestCase).filter_by(dataset_id=dataset_id).count()
    db.commit()
    return UploadResult(dataset_id=dataset_id, imported=imported, skipped=skipped,
                        case_count=dataset.case_count)
