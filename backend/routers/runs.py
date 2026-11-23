"""评测任务接口"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.dataset import Dataset, TestCase
from backend.models.run import EvalResult, EvalRun
from backend.routers._common import api_error, paginate
from backend.schemas.run import (CompareOut, CompareRequest, ResultOut, RunCreate,
                                 RunCreated, RunOut, RunStatus)
from backend.services import report_service
from backend.services.eval_service import execute_eval

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", status_code=201, response_model=RunCreated)
def create_run(payload: RunCreate, background_tasks: BackgroundTasks,
               db: Session = Depends(get_db)):
    dataset = db.get(Dataset, payload.dataset_id)
    if dataset is None:
        api_error(404, "NOT_FOUND", "数据集不存在: %s" % payload.dataset_id)

    running = db.query(EvalRun).filter(
        EvalRun.dataset_id == payload.dataset_id,
        EvalRun.prompt_version == payload.prompt_version,
        EvalRun.status.in_(["pending", "running"]),
    ).first()
    if running:
        api_error(409, "RUNNING_CONFLICT",
                  "同一数据集 + Prompt 已有运行中任务: %s" % running.id)

    total = db.query(TestCase).filter_by(dataset_id=payload.dataset_id).count()
    run = EvalRun(id="run_" + uuid.uuid4().hex[:12], dataset_id=payload.dataset_id,
                  prompt_version=payload.prompt_version, model_name=payload.model,
                  judge_model=payload.judge_model, total_cases=total,
                  status="pending", progress=0)
    db.add(run)
    db.commit()

    # 立即返回，评测在后台跑
    background_tasks.add_task(execute_eval, run.id)
    return RunCreated(run_id=run.id, status=run.status, total_cases=total)


@router.get("")
def list_runs(status: str = None, page: int = 1, page_size: int = 20,
              db: Session = Depends(get_db)):
    query = db.query(EvalRun)
    if status:
        query = query.filter(EvalRun.status == status)
    result = paginate(query.order_by(EvalRun.started_at.desc()), page, page_size)
    result["items"] = [RunOut.model_validate(r) for r in result["items"]]
    return result


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    return RunOut.model_validate(run)


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    """请求取消：只置标记，执行循环处理下一条时自行中止"""
    run = db.get(EvalRun, run_id)
    if run is None:
        api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    if run.status not in ("pending", "running"):
        api_error(400, "INVALID_PARAM", "任务已结束，无法取消: %s" % run.status)
    run.cancel_requested = True
    db.commit()
    return {"run_id": run_id, "status": run.status, "cancel_requested": True}


@router.get("/{run_id}/status", response_model=RunStatus)
def get_status(run_id: str, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    results = db.query(EvalResult).filter_by(run_id=run_id).all()
    return RunStatus(status=run.status, progress=run.progress or 0,
                     processed=len(results), total=run.total_cases or 0,
                     failed=sum(1 for r in results if r.passed is False))


@router.get("/{run_id}/results")
def list_results(run_id: str, passed: bool = Query(default=None), page: int = 1,
                 page_size: int = 20, db: Session = Depends(get_db)):
    if db.get(EvalRun, run_id) is None:
        api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    query = db.query(EvalResult).filter_by(run_id=run_id)
    if passed is not None:
        query = query.filter(EvalResult.passed == passed)
    result = paginate(query.order_by(EvalResult.case_id), page, page_size)

    # 标准答案存在用例表，按 case_id 批量补齐，便于前端展示 badcase 对照
    case_ids = [r.case_id for r in result["items"]]
    truths = dict(db.query(TestCase.id, TestCase.ground_truth)
                  .filter(TestCase.id.in_(case_ids)).all()) if case_ids else {}
    result["items"] = [
        ResultOut.model_validate(r).model_copy(
            update={"ground_truth": truths.get(r.case_id)})
        for r in result["items"]
    ]
    return result


@router.get("/{run_id}/report")
def get_report(run_id: str, format: str = "json", db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    if format == "html":
        return Response(report_service.render_html(db, run), media_type="text/html")
    if format != "json":
        api_error(400, "INVALID_PARAM", "format 仅支持 json / html")
    return report_service.build_report(db, run)


@router.post("/compare", response_model=CompareOut)
def compare_runs_api(payload: CompareRequest, db: Session = Depends(get_db)):
    run_a = db.get(EvalRun, payload.run_id_a)
    run_b = db.get(EvalRun, payload.run_id_b)
    for run_id, run in ((payload.run_id_a, run_a), (payload.run_id_b, run_b)):
        if run is None:
            api_error(404, "NOT_FOUND", "任务不存在: %s" % run_id)
    if run_a.dataset_id != run_b.dataset_id:
        api_error(400, "INVALID_PARAM", "只能对比同一数据集上的两次评测")
    return report_service.compare(db, run_a, run_b)
