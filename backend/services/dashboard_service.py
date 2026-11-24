"""
首页质量概览聚合（Day 19）

一个接口喂饱首页四块内容，避免前端拿列表接口重复拼装：
- latest：最近一次已完成评测的总分、等级与通过情况
- radar：六项能力 vs 目标值（缺失指标返回 null，前端显示空档）
- trend：同一数据集最近 5 次评测总分（按完成时间正序）
- categories：最近一次评测的分类通过率（最差排前面）
- compare：与上一次同数据集评测的指标差异（不足两次为 null）
"""
from collections import defaultdict

from sqlalchemy import func

from backend.models.dataset import Dataset, TestCase
from backend.models.run import EvalResult, EvalRun, MetricSnapshot
from backend.services import report_service
from metrics.scorer import grade

# 雷达六维：键与报告指标对齐；目标值来自 Day 2 指标体系与 Day 9 语义阈值
RADAR_INDICATORS = [
    {"key": "faithfulness", "label": "忠实度", "target": 0.85},
    {"key": "correctness", "label": "答案正确性", "target": 0.84},
    {"key": "answer_relevance", "label": "答案相关性", "target": 0.85},
    {"key": "context_precision", "label": "上下文精度", "target": 0.70},
    {"key": "safety", "label": "安全性", "target": 0.95},
    {"key": "performance", "label": "性能", "target": 0.85},
]

TREND_LIMIT = 5
# 与 metrics/scorer.py 的延迟经验阈值一致：3 秒视为最差
LATENCY_WORST_MS = 3000.0


def _metrics_of(db, run: EvalRun) -> dict:
    rows = db.query(MetricSnapshot).filter_by(run_id=run.id).all()
    return {r.metric_name: float(r.value) for r in rows}


def _category_stats(rows: list) -> list:
    """按分类统计通过率，最差分类排前面"""
    groups = defaultdict(lambda: {"total": 0, "passed": 0})
    for result, category in rows:
        group = groups[category or "未分类"]
        group["total"] += 1
        if result.passed:
            group["passed"] += 1
    stats = [
        {
            "category": name,
            "total": group["total"],
            "passed": group["passed"],
            "pass_rate": round(group["passed"] / group["total"] * 100, 1),
        }
        for name, group in groups.items()
    ]
    return sorted(stats, key=lambda item: item["pass_rate"])


def _empty(dataset) -> dict:
    return {
        "dataset": {"id": dataset.id, "name": dataset.name} if dataset else None,
        "latest": None,
        "radar": {"indicators": [{**spec, "value": None} for spec in RADAR_INDICATORS],
                  "missing": [spec["label"] for spec in RADAR_INDICATORS]},
        "trend": [],
        "categories": [],
        "compare": None,
        "badcase_count": 0,
    }


def build_dashboard(db, dataset_id: str = None) -> dict:
    query = db.query(EvalRun).filter(EvalRun.status == "done")
    if dataset_id:
        query = query.filter(EvalRun.dataset_id == dataset_id)
    latest = query.order_by(EvalRun.finished_at.desc()).first()
    if latest is None:
        return _empty(db.get(Dataset, dataset_id) if dataset_id else None)

    dataset = db.get(Dataset, latest.dataset_id) if latest.dataset_id else None
    rows = (
        db.query(EvalResult, TestCase.category)
        .outerjoin(TestCase, TestCase.id == EvalResult.case_id)
        .filter(EvalResult.run_id == latest.id)
        .all()
    )
    failed = sum(1 for result, _ in rows if not result.passed)

    metrics = _metrics_of(db, latest)
    avg_ms = db.query(func.avg(EvalResult.duration_ms)).filter(
        EvalResult.run_id == latest.id).scalar()
    if avg_ms is not None:
        metrics["performance"] = round(
            max(0.0, 1.0 - float(avg_ms) / LATENCY_WORST_MS), 4)

    indicators = []
    missing = []
    for spec in RADAR_INDICATORS:
        value = metrics.get(spec["key"])
        if value is None:
            missing.append(spec["label"])
        indicators.append({**spec, "value": round(value, 4) if value is not None else None})

    trend_rows = (
        db.query(EvalRun)
        .filter(EvalRun.dataset_id == latest.dataset_id, EvalRun.status == "done")
        .order_by(EvalRun.finished_at.desc())
        .limit(TREND_LIMIT)
        .all()
    )
    trend = [
        {
            "run_id": run.id,
            "label": run.prompt_version,
            "score": round(float(run.total_score or 0), 2),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
        for run in reversed(trend_rows)
    ]

    previous = None
    if latest.finished_at is not None:
        previous = (
            db.query(EvalRun)
            .filter(EvalRun.dataset_id == latest.dataset_id,
                    EvalRun.status == "done",
                    EvalRun.id != latest.id,
                    EvalRun.finished_at < latest.finished_at)
            .order_by(EvalRun.finished_at.desc())
            .first()
        )
    compare = None
    if previous is not None:
        compare = report_service.compare(db, latest, previous)
        compare["baseline_run_id"] = previous.id
        compare["baseline_version"] = previous.prompt_version

    score = float(latest.total_score or 0)
    return {
        "dataset": {"id": dataset.id, "name": dataset.name} if dataset else None,
        "latest": {
            "run_id": latest.id,
            "dataset_id": latest.dataset_id,
            "dataset": dataset.name if dataset else None,
            "prompt_version": latest.prompt_version,
            "model": latest.model_name,
            "total_score": round(score, 2),
            "grade": grade(score),
            "total": len(rows),
            "passed": len(rows) - failed,
            "failed": failed,
            "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
        },
        "radar": {"indicators": indicators, "missing": missing},
        "trend": trend,
        "categories": _category_stats(rows),
        "compare": compare,
        "badcase_count": failed,
    }
