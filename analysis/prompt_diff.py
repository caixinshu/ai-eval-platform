"""
Prompt 版本差异分析（Day 23）

均值会骗人：总分涨 2 分，可能是 10 条提升、15 条下降互相抵消。
这里逐用例对比两次评测，输出 improved / degraded / unchanged 明细，
并按 category 归因，避免「核心业务退化但总分上涨」被放过。

输入两种形态都支持：
- 逐用例列表：[{"case_id": ..., "total_score": ..., "category": ...}, ...]
- 评测报告：run_eval.py 产出的 {"case_results": [...]} 或平台结果 {"results": [...]}
"""
import json
from collections import defaultdict

# 计算单条得分时纳入的指标；f1 / exact_match 属于诊断项，不参与平均
SCORE_METRIC_KEYS = (
    "rule_score", "correctness", "faithfulness", "answer_relevance",
    "relevance", "context_precision", "safety", "format", "length",
)


def score_from_metrics(metrics: dict) -> float:
    """把平台/评测结果的指标字典折算成 0-100 的单条得分"""
    values = [
        float(value) for key, value in (metrics or {}).items()
        if key in SCORE_METRIC_KEYS
        and isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if not values:
        return 0.0
    return round(sum(values) / len(values) * 100, 2)


def normalize_case(row: dict) -> dict:
    """统一成 diff 需要的最小结构，缺 total_score 时按 metrics 折算"""
    case_id = row.get("case_id") or row.get("id")
    if not case_id:
        raise ValueError("用例缺少 case_id: %r" % row)

    score = row.get("total_score")
    if score is None:
        score = score_from_metrics(row.get("metrics") or {})
    return {
        "case_id": str(case_id),
        "question": row.get("question") or "",
        "category": row.get("category") or "unknown",
        "total_score": round(float(score), 2),
    }


def normalize_cases(data) -> list:
    """接受列表或报告字典，返回规范化后的用例列表"""
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = (data.get("case_results") or data.get("results")
                or data.get("items") or [])
    else:
        raise ValueError("不支持的数据类型: %s" % type(data).__name__)
    return [normalize_case(row) for row in rows]


def load_cases(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return normalize_cases(json.load(f))


def diff_results(current: list, baseline: list, threshold: float = 0.05) -> dict:
    """逐用例对比，threshold 为 0-1 的分数比例（0.05 即 5 分）"""
    base_map = {row["case_id"]: row for row in baseline}
    improved, degraded, unchanged = [], [], []
    threshold_points = threshold * 100

    for cur in current:
        base = base_map.get(cur["case_id"])
        if not base:
            continue

        delta = cur["total_score"] - base["total_score"]
        item = {
            "case_id": cur["case_id"],
            "question": cur.get("question", ""),
            "current": round(cur["total_score"], 2),
            "baseline": round(base["total_score"], 2),
            "delta": round(delta, 2),
            "category": cur.get("category") or base.get("category") or "unknown",
        }

        if delta >= threshold_points:
            improved.append(item)
        elif delta <= -threshold_points:
            degraded.append(item)
        else:
            unchanged.append(item)

    return {
        "threshold": threshold,
        "improved": sorted(improved, key=lambda x: -x["delta"]),
        "degraded": sorted(degraded, key=lambda x: x["delta"]),
        "unchanged": unchanged,
        "unchanged_count": len(unchanged),
        "summary": {
            "improved_count": len(improved),
            "degraded_count": len(degraded),
            "net_change": len(improved) - len(degraded),
        },
    }


def summarize_categories(diff: dict) -> dict:
    """按 category 汇总提升/退化数量与平均变化，退化多的排前面"""
    buckets = defaultdict(lambda: {
        "improved": 0, "degraded": 0, "unchanged": 0,
        "delta_sum": 0.0, "count": 0,
    })

    for group in ("improved", "degraded", "unchanged"):
        for item in diff.get(group, []):
            bucket = buckets[item["category"] or "unknown"]
            bucket[group] += 1
            bucket["delta_sum"] += item["delta"]
            bucket["count"] += 1

    result = {}
    for category, bucket in buckets.items():
        result[category] = {
            "count": bucket["count"],
            "improved": bucket["improved"],
            "degraded": bucket["degraded"],
            "unchanged": bucket["unchanged"],
            "avg_delta": round(bucket["delta_sum"] / bucket["count"], 2),
            "net_change": bucket["improved"] - bucket["degraded"],
        }
    return dict(sorted(
        result.items(),
        key=lambda kv: (-kv[1]["degraded"], kv[1]["avg_delta"])))


def risk_note(diff: dict, stats: dict = None) -> str:
    """给出一句话风险提示：是否被均值掩盖、退化是否集中"""
    degraded_count = diff["summary"]["degraded_count"]
    if degraded_count == 0:
        return "无退化用例"

    stats = stats or summarize_categories(diff)
    notes = []
    if diff["summary"]["net_change"] > 0:
        notes.append("净提升 %d 条，但仍有 %d 条退化，均值可能掩盖问题"
                     % (diff["summary"]["net_change"], degraded_count))

    top_category, top = next(iter(stats.items()))
    share = top["degraded"] / degraded_count
    if top["degraded"] and share >= 0.6:
        notes.append("退化集中在「%s」（%d/%d）"
                     % (top_category, top["degraded"], degraded_count))

    return "；".join(notes) if notes else "退化分散在多个分类，需逐条确认"


def _escape(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(diff: dict, current_label: str = "current",
                    baseline_label: str = "baseline") -> str:
    """生成适合 PR / 人工 review 的差异报告"""
    stats = summarize_categories(diff)
    summary = diff["summary"]
    note = risk_note(diff, stats)

    lines = [
        "## Prompt 版本差异分析",
        "",
        "- 当前版本：`%s`" % current_label,
        "- 基线版本：`%s`" % baseline_label,
        "- 变化阈值：±%g 分" % round(diff["threshold"] * 100, 2),
        "",
        "| 提升 | 退化 | 未变 | 净变化 |",
        "|------|------|------|--------|",
        "| %d | %d | %d | %+d |"
        % (summary["improved_count"], summary["degraded_count"],
           diff["unchanged_count"], summary["net_change"]),
        "",
        "> 风险提示：%s" % note,
        "",
        "### 分类归因",
        "",
        "| 分类 | 用例数 | 提升 | 退化 | 未变 | 平均变化 | 净变化 |",
        "|------|--------|------|------|------|----------|--------|",
    ]
    for category, item in stats.items():
        lines.append("| %s | %d | %d | %d | %d | %+.2f | %+d |"
                     % (_escape(category), item["count"], item["improved"],
                        item["degraded"], item["unchanged"],
                        item["avg_delta"], item["net_change"]))

    if diff["degraded"]:
        lines += [
            "",
            "### 退化用例（前 20 条）",
            "",
            "| 用例 | 分类 | 问题 | 当前 | 基线 | 变化 |",
            "|------|------|------|------|------|------|",
        ]
        for item in diff["degraded"][:20]:
            lines.append("| %s | %s | %s | %.2f | %.2f | %+.2f |"
                         % (_escape(item["case_id"]), _escape(item["category"]),
                            _escape(item["question"])[:40], item["current"],
                            item["baseline"], item["delta"]))

    if diff["improved"]:
        lines += [
            "",
            "### 提升用例（前 10 条）",
            "",
            "| 用例 | 分类 | 问题 | 当前 | 基线 | 变化 |",
            "|------|------|------|------|------|------|",
        ]
        for item in diff["improved"][:10]:
            lines.append("| %s | %s | %s | %.2f | %.2f | %+.2f |"
                         % (_escape(item["case_id"]), _escape(item["category"]),
                            _escape(item["question"])[:40], item["current"],
                            item["baseline"], item["delta"]))

    return "\n".join(lines) + "\n"
