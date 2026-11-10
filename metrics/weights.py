"""
指标权重配置 (Metric Weights)
定义各指标在综合评分中的权重，以及不同场景的权重预设。
"""

# ==================== 单指标权重 ====================
# 所有指标权重之和应为 1.0
# 可根据业务场景调整

DEFAULT_WEIGHTS: dict[str, float] = {
    # 准确性 (30%)
    "accuracy": 0.10,
    "exact_match": 0.05,
    "f1": 0.15,

    # 语义相似度 (15%)
    "bert_score": 0.08,
    "cosine_similarity": 0.07,

    # RAG 专项 (30%)
    "faithfulness": 0.10,
    "context_precision": 0.07,
    "context_recall": 0.07,
    "answer_relevance": 0.06,

    # 安全合规 (10%)
    "toxicity": 0.05,
    "jailbreak": 0.05,

    # 效率 (10%)
    "latency_p95": 0.04,
    "tokens_per_request": 0.03,
    "cost_per_request": 0.03,

    # 格式 (5%)
    "format_valid": 0.05,
}

# ==================== 场景权重预设 ====================
# 不同评测场景使用不同的权重组合

# 知识问答场景：重视准确性和忠实度
WEIGHTS_QA: dict[str, float] = {
    "accuracy": 0.12,
    "f1": 0.18,
    "bert_score": 0.10,
    "faithfulness": 0.15,
    "context_recall": 0.12,
    "answer_relevance": 0.10,
    "context_precision": 0.08,
    "format_valid": 0.05,
    "toxicity": 0.05,
    "latency_p95": 0.03,
    "tokens_per_request": 0.01,
    "cost_per_request": 0.01,
}

# 生成场景：重视相关性和格式
WEIGHTS_GENERATION: dict[str, float] = {
    "answer_relevance": 0.18,
    "bert_score": 0.15,
    "cosine_similarity": 0.10,
    "faithfulness": 0.12,
    "format_valid": 0.12,
    "toxicity": 0.10,
    "jailbreak": 0.08,
    "latency_p95": 0.05,
    "tokens_per_request": 0.05,
    "cost_per_request": 0.05,
}

# 安全优先场景：安全指标权重最高
WEIGHTS_SAFETY: dict[str, float] = {
    "toxicity": 0.25,
    "jailbreak": 0.25,
    "answer_relevance": 0.10,
    "faithfulness": 0.10,
    "format_valid": 0.08,
    "accuracy": 0.05,
    "f1": 0.05,
    "latency_p95": 0.05,
    "tokens_per_request": 0.04,
    "cost_per_request": 0.03,
}

# 性能优先场景：效率指标权重最高
WEIGHTS_PERFORMANCE: dict[str, float] = {
    "latency_p95": 0.25,
    "tokens_per_request": 0.20,
    "cost_per_request": 0.15,
    "answer_relevance": 0.10,
    "faithfulness": 0.08,
    "format_valid": 0.07,
    "accuracy": 0.05,
    "f1": 0.05,
    "toxicity": 0.03,
    "jailbreak": 0.02,
}


# ==================== 预设映射 ====================
WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "default": DEFAULT_WEIGHTS,
    "qa": WEIGHTS_QA,
    "generation": WEIGHTS_GENERATION,
    "safety": WEIGHTS_SAFETY,
    "performance": WEIGHTS_PERFORMANCE,
}


def get_weights(preset: str = "default") -> dict[str, float]:
    """获取指定场景的权重配置"""
    if preset not in WEIGHT_PRESETS:
        raise KeyError(f"未知预设: {preset}，可用: {list(WEIGHT_PRESETS.keys())}")
    return WEIGHT_PRESETS[preset].copy()


def validate_weights(weights: dict[str, float], tolerance: float = 0.01) -> bool:
    """验证权重之和是否为 1.0"""
    total = sum(weights.values())
    return abs(total - 1.0) < tolerance


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """将权重归一化到 1.0"""
    total = sum(weights.values())
    if total == 0:
        raise ValueError("权重总和不能为 0")
    return {k: v / total for k, v in weights.items()}


if __name__ == "__main__":
    for name, weights in WEIGHT_PRESETS.items():
        total = sum(weights.values())
        status = "✓" if validate_weights(weights) else "✗"
        print(f"[{status}] {name}: 权重和 = {total:.4f} ({len(weights)} 个指标)")
