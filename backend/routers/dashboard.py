"""质量概览看板接口（Day 19）"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.dashboard_service import build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(dataset_id: str = None, db: Session = Depends(get_db)):
    """首页概览：最近评测 + 雷达 + 趋势 + 分类 + 基线对比"""
    return build_dashboard(db, dataset_id)
