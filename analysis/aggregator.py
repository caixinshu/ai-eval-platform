"""
分组统计

- `aggregate(results, cases)`：按 category 统计均分、通过率、核心指标
- `group_badcases(badcases, cases)`：按 category 统计 badcase 分布与主要失败指标
"""
from collections import Counter, defaultdict


def aggregate(results: list, cases: list) -> dict:
    """按 category 分组统计（结果需带 total_score / passed / metrics）"""
    case_map = {c["id"]: c for c in cases}
    groups = defaultdict(list)

    for r in results:
        case = case_map.get(r["case_id"])
        if case:
            groups[case.get("category", "unknown")].append(r)

    stats = {}
    for cat, items in groups.items():
        n = len(items)
        stats[cat] = {
            "count": n,
            "avg_score": round(sum(i["total_score"] for i in items) / n, 2),
            "pass_rate": round(sum(1 for i in items if i["passed"]) / n, 3),
            "avg_faithfulness": round(
                sum(i.get("metrics", {}).get("faithfulness", 0) for i in items) / n, 3),
        }

    # 按平均分升序：最差的排最前
    return dict(sorted(stats.items(), key=lambda x: x[1]["avg_score"]))


def group_badcases(badcases: list, cases: list) -> dict:
    """按 category 统计 badcase 分布（兼容只有 badcase 明细的报告）"""
    if not badcases:
        return {}
    case_map = {c["id"]: c for c in cases}
    groups = defaultdict(list)

    for b in badcases:
        case = case_map.get(b["id"], {})
        groups[case.get("category", "unknown")].append(b)

    stats = {}
    for cat, items in groups.items():
        metric_counter = Counter(
            m["metric"] for i in items for m in i.get("failed_metrics", []))
        stats[cat] = {
            "count": len(items),
            "share": round(len(items) / len(badcases), 3),
            "sample_ids": [i["id"] for i in items][:3],
            "top_failed_metrics": metric_counter.most_common(3),
        }
    return dict(sorted(stats.items(), key=lambda x: -x[1]["count"]))
