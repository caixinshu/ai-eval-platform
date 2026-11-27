"""线上监控接口（Day 24）：反馈、抽样记录、5 面板聚合"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.monitor import (FeedbackIn, FeedbackOut, SampleIn,
                                     SampleOut)
from backend.services.monitor_service import (build_overview, record_feedback,
                                              record_sample)
from monitor.feedback_collector import BadcaseCollector

router = APIRouter(prefix="/api", tags=["monitor"])


@router.post("/feedback", status_code=201, response_model=FeedbackOut)
def create_feedback(payload: FeedbackIn, db: Session = Depends(get_db)):
    """用户反馈入口；差评自动归入 5 类问题"""
    return record_feedback(db, payload)


@router.post("/monitor/samples", status_code=201, response_model=SampleOut)
def create_sample(payload: SampleIn, db: Session = Depends(get_db)):
    """线上抽样评测结果落库（由采样器命中后调用）"""
    return record_sample(db, payload)


@router.get("/monitor/overview")
def get_monitor_overview(days: int = Query(30, ge=1, le=90),
                         db: Session = Depends(get_db)):
    """线上质量看板：质量总览 / 问题分布 / 趋势 / 分类 / 回流进度"""
    return build_overview(db, days=days)


@router.get("/monitor/badcases")
def get_badcases(days: int = Query(7, ge=1, le=90),
                 db: Session = Depends(get_db)):
    """近 N 天差评明细，用于回流前预览"""
    items = BadcaseCollector().collect_badcases(days=days, db=db)
    return {"items": items, "total": len(items), "days": days}
