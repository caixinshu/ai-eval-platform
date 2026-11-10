"""
综合评分器 (Composite Scorer)
将多个指标按权重加权求和，输出 0-100 的评测总分。
"""
from typing import Optional

try:
    from .dictionary import METRICS
    from .weights import get_weights, validate_weights
except ImportError:
    from dictionary import METRICS
    from weights import get_weights, validate_weights


def normalize_score(metric_key: str, raw_value: float) -> float:
    """
    将指标原始值归一化到 0-1 区间。
    对于 higher_is_better=False 的指标，做反转。
    """
    m = METRICS[metric_key]
    low, high = m.range

    # 效率类指标（延迟、Token、成本）：值越小越好
    if not m.higher_is_better:
        if high == float("inf"):
            # 无上限的指标，用经验阈值归一化
            thresholds = {
                "latency_p95": 3000.0,       # 3s 为最差
                "tokens_per_request": 10000.0,  # 10K tokens 为最差
                "cost_per_request": 0.05,    # $0.05 为最差
            }
            threshold = thresholds.get(metric_key, 1.0)
            normalized = max(0.0, 1.0 - raw_value / threshold)
        else:
            normalized = (high - raw_value) / (high - low) if high != low else 0.0
    else:
        if low == -1.0 and high == 1.0:
            # 余弦相似度范围 -1~1，映射到 0~1
            normalized = (raw_value + 1.0) / 2.0
        else:
            normalized = (raw_value - low) / (high - low) if high != low else raw_value

    return max(0.0, min(1.0, normalized))


def compute_composite_score(
    scores: dict[str, float],
    weights: Optional[dict[str, float]] = None,
    preset: str = "default",
) -> dict:
    """
    计算综合评分。

    Args:
        scores: {指标key: 原始值}
        weights: 自定义权重，为 None 时使用 preset
        preset: 权重预设名

    Returns:
        {
            "total": 综合得分 (0-100),
            "breakdown": {指标: {raw, normalized, weight, contribution}},
            "missing": 缺失的指标列表
        }
    """
    if weights is None:
        weights = get_weights(preset)

    if not validate_weights(weights):
        raise ValueError(f"权重和不为 1.0: {sum(weights.values()):.4f}")

    breakdown = {}
    total = 0.0
    missing = []

    for key, weight in weights.items():
        if key not in scores:
            missing.append(key)
            continue

        raw = scores[key]
        normalized = normalize_score(key, raw)
        contribution = normalized * weight
        total += contribution

        breakdown[key] = {
            "raw": raw,
            "normalized": round(normalized, 4),
            "weight": weight,
            "contribution": round(contribution, 4),
        }

    return {
        "total": round(total * 100, 2),
        "breakdown": breakdown,
        "missing": missing,
    }


def grade(score: float) -> str:
    """将综合得分转为等级"""
    if score >= 90:
        return "A (优秀)"
    elif score >= 80:
        return "B (良好)"
    elif score >= 70:
        return "C (合格)"
    elif score >= 60:
        return "D (及格)"
    else:
        return "F (不及格)"


if __name__ == "__main__":
    # 示例：一组模拟指标分数
    scores = {
        "accuracy": 0.85,
        "exact_match": 0.60,
        "f1": 0.78,
        "bert_score": 0.82,
        "cosine_similarity": 0.75,
        "faithfulness": 0.90,
        "context_precision": 0.70,
        "context_recall": 0.65,
        "answer_relevance": 0.88,
        "toxicity": 0.01,
        "jailbreak": 0.0,
        "latency_p95": 800.0,
        "tokens_per_request": 1200.0,
        "cost_per_request": 0.003,
        "format_valid": 0.95,
    }

    result = compute_composite_score(scores, preset="default")
    print(f"综合得分: {result['total']}/100  {grade(result['total'])}")
    print(f"缺失指标: {result['missing']}")
    print("\n各指标贡献:")
    for key, info in result["breakdown"].items():
        print(f"  {key:25s} raw={info['raw']:.4f} norm={info['normalized']:.4f} "
              f"w={info['weight']:.2f} contrib={info['contribution']:.4f}")
