"""
版本对比：指标 diff + 显著性判断

LLM 评测天然有 ±2 分波动，3 个百分点以内视为噪声，避免团队过度解读。
"""

SIGNIFICANCE_THRESHOLD = 0.03


def compare_runs(current: dict, baseline: dict,
                 threshold: float = SIGNIFICANCE_THRESHOLD) -> dict:
    """
    对比两次评测（同一数据集、不同 Prompt/模型版本）

    Args:
        current: 新版本报告（需含 metrics / total_score）
        baseline: 基准版本报告
        threshold: 显著变化阈值（绝对值）
    """
    diffs = {}
    for metric, cur_val in current.get("metrics", {}).items():
        base_val = baseline.get("metrics", {}).get(metric, 0)
        delta = cur_val - base_val
        diffs[metric] = {
            "current": round(cur_val, 4),
            "baseline": round(base_val, 4),
            "delta": round(delta, 4),
            "delta_pct": round(delta / base_val * 100, 2) if base_val else 0,
            "improved": delta > 0,
            "significant": abs(delta) >= threshold,
        }

    cur_total = current.get("total_score", 0)
    base_total = baseline.get("total_score", 0)
    return {
        "total": {
            "current": cur_total,
            "baseline": base_total,
            "delta": round(cur_total - base_total, 2),
            "improved": cur_total > base_total,
            "significant": abs(cur_total - base_total) >= threshold * 100,
        },
        "metrics": diffs,
        "regressions": [m for m, d in diffs.items()
                        if d["significant"] and not d["improved"]],
        "improvements": [m for m, d in diffs.items()
                         if d["significant"] and d["improved"]],
    }
