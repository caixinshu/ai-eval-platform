"""
线上质量监控聚合（Day 24）

5 个面板的数据都在这里算：
1. 质量总览：近 24h 抽样均分 / 差评率 + 小时桶
2. 问题分布：近 7 天差评按 issue category
3. 趋势：近 N 天抽样均分
4. 分类明细：各业务线抽样均分
5. 回流进度：fresh_set 待标注 / 已入集

数据量在本项目规模下优先用 Python 聚合，避免 SQLite / PostgreSQL 日期函数差异；
真实大流量场景应改为数据库聚合 + 预计算表。
"""
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from backend.config import BASE_DIR
from backend.models.feedback import OnlineSample, UserFeedback
from monitor.badcase_reflow import load_cases, stats as reflow_stats
from monitor.feedback_collector import BadcaseCollector

FRESH_SET_PATH = os.getenv(
    "FRESH_SET_PATH",
    os.path.join(BASE_DIR, "eval_datasets", "fresh_set.json"),
)


def _as_dt(value):
    """统一成 naive datetime；SQLite 可能返回字符串，时区值统一去掉 tzinfo"""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _round(value, digits=2):
    return None if value is None else round(float(value), digits)


def _avg(values):
    return _round(sum(values) / len(values), 2) if values else None


def record_feedback(db, payload) -> UserFeedback:
    """落库反馈；差评立即归类，good 不参与问题分布"""
    collector = BadcaseCollector()
    row = UserFeedback(
        id="fb_" + uuid.uuid4().hex[:12],
        request_id=payload.request_id,
        question=payload.question,
        answer=payload.answer,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
        issue_category=(collector.classify(payload.comment, payload.reason)
                        if payload.rating == "bad" else None),
        user_id=payload.user_id,
        biz_line=payload.biz_line,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_sample(db, payload) -> OnlineSample:
    """记录一条抽样评测结果，供线上看板聚合"""
    row = OnlineSample(
        id="os_" + uuid.uuid4().hex[:12],
        request_id=payload.request_id,
        question=payload.question,
        answer=payload.answer,
        score=payload.score,
        biz_line=payload.biz_line,
        latency_ms=payload.latency_ms,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _hourly_panel(samples: list, feedbacks: list, now: datetime) -> list:
    end = now.replace(minute=0, second=0, microsecond=0)
    buckets = {
        (end - timedelta(hours=offset)).strftime("%Y-%m-%d %H:00"): {
            "hour": (end - timedelta(hours=offset)).strftime("%Y-%m-%d %H:00"),
            "scores": [], "feedback_count": 0, "bad_count": 0,
        }
        for offset in range(23, -1, -1)
    }

    for sample in samples:
        sampled_at = _as_dt(sample.sampled_at)
        if sampled_at is None:
            continue
        key = sampled_at.strftime("%Y-%m-%d %H:00")
        if key in buckets:
            buckets[key]["scores"].append(float(sample.score))

    for feedback in feedbacks:
        created_at = _as_dt(feedback.created_at)
        if created_at is None:
            continue
        key = created_at.strftime("%Y-%m-%d %H:00")
        if key in buckets:
            buckets[key]["feedback_count"] += 1
            if feedback.rating == "bad":
                buckets[key]["bad_count"] += 1

    panel = []
    for bucket in buckets.values():
        count = bucket["feedback_count"]
        panel.append({
            "hour": bucket["hour"],
            "avg_score": _avg(bucket["scores"]),
            "sample_count": len(bucket["scores"]),
            "feedback_count": count,
            "bad_rate": _round(bucket["bad_count"] / count, 4) if count else None,
        })
    return panel


def _issue_panel(feedbacks: list, now: datetime, days: int = 7) -> dict:
    since = now - timedelta(days=days)
    collector = BadcaseCollector()
    counts = defaultdict(int)

    for feedback in feedbacks:
        if feedback.rating != "bad":
            continue
        created_at = _as_dt(feedback.created_at)
        if created_at is None or created_at < since:
            continue
        category = (feedback.issue_category
                    or collector.classify(feedback.comment, feedback.reason))
        counts[category] += 1

    total = sum(counts.values())
    items = [
        {"category": category, "count": count,
         "share": _round(count / total, 3) if total else 0}
        for category, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {"days": days, "total": total, "items": items}


def _trend_panel(samples: list, now: datetime, days: int) -> list:
    start = (now - timedelta(days=days - 1)).date()
    buckets = {start + timedelta(days=offset): [] for offset in range(days)}

    for sample in samples:
        sampled_at = _as_dt(sample.sampled_at)
        if sampled_at is None:
            continue
        day = sampled_at.date()
        if day in buckets:
            buckets[day].append(float(sample.score))

    return [
        {"date": day.isoformat(), "avg_score": _avg(scores),
         "sample_count": len(scores)}
        for day, scores in buckets.items()
    ]


def _category_panel(samples: list) -> list:
    buckets = defaultdict(list)
    for sample in samples:
        buckets[sample.biz_line or "未分类"].append(float(sample.score))
    return [
        {"biz_line": name, "sample_count": len(scores),
         "avg_score": _avg(scores)}
        for name, scores in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    ]


def build_overview(db, days: int = 30, now: datetime = None,
                   fresh_path: str = None) -> dict:
    """聚合 5 个面板；空库返回零值而不是 500"""
    now = now or datetime.now()
    days = max(1, min(int(days), 90))
    since = now - timedelta(days=days)

    samples = (db.query(OnlineSample)
               .filter(OnlineSample.sampled_at >= since)
               .order_by(OnlineSample.sampled_at.asc()).all())
    feedbacks = (db.query(UserFeedback)
                 .filter(UserFeedback.created_at >= since)
                 .order_by(UserFeedback.created_at.asc()).all())

    last_24h = now - timedelta(hours=24)
    samples_24h = [s for s in samples
                   if (_as_dt(s.sampled_at) or now) >= last_24h]
    feedbacks_24h = [f for f in feedbacks
                     if (_as_dt(f.created_at) or now) >= last_24h]
    bad_24h = sum(1 for f in feedbacks_24h if f.rating == "bad")

    fresh_cases = load_cases(fresh_path or FRESH_SET_PATH)
    reflow = reflow_stats(fresh_cases)

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": days,
        "quality": {
            "sample_count_24h": len(samples_24h),
            "avg_score_24h": _avg([float(s.score) for s in samples_24h]),
            "feedback_count_24h": len(feedbacks_24h),
            "bad_count_24h": bad_24h,
            "bad_rate_24h": (_round(bad_24h / len(feedbacks_24h), 4)
                             if feedbacks_24h else None),
            "sample_count": len(samples),
            "feedback_count": len(feedbacks),
        },
        "hourly": _hourly_panel(samples, feedbacks, now),
        "issues": _issue_panel(feedbacks, now, days=7),
        "trend": _trend_panel(samples, now, days),
        "categories": _category_panel(samples),
        "reflow": reflow,
    }
