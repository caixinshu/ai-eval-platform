"""
AI 评测指标包 (Metrics Package)
统一导出所有指标计算函数。
"""
from .dictionary import (
    METRICS,
    MetricCategory,
    MetricDefinition,
    MetricType,
    get_metric,
    list_by_category,
    list_metrics,
)
from .weights import (
    DEFAULT_WEIGHTS,
    WEIGHTS_GENERATION,
    WEIGHTS_PERFORMANCE,
    WEIGHTS_QA,
    WEIGHTS_SAFETY,
    WEIGHT_PRESETS,
    get_weights,
    normalize_weights,
    validate_weights,
)
from .accuracy import accuracy, exact_match, exact_match_batch, f1_score, f1_score_batch
from .similarity import bert_score, bert_score_batch, cosine_similarity, cosine_similarity_batch
from .rag import answer_relevance, context_precision, context_recall, faithfulness
from .safety import jailbreak, jailbreak_batch, toxicity, toxicity_batch
from .efficiency import (
    cost_per_request,
    format_valid,
    format_valid_batch,
    latency_avg,
    latency_p95,
    percentile,
    tokens_per_request,
)
from .scorer import compute_composite_score, grade, normalize_score

__all__ = [
    # dictionary
    "METRICS",
    "MetricCategory",
    "MetricDefinition",
    "MetricType",
    "get_metric",
    "list_by_category",
    "list_metrics",
    # weights
    "DEFAULT_WEIGHTS",
    "WEIGHTS_GENERATION",
    "WEIGHTS_PERFORMANCE",
    "WEIGHTS_QA",
    "WEIGHTS_SAFETY",
    "WEIGHT_PRESETS",
    "get_weights",
    "normalize_weights",
    "validate_weights",
    # accuracy
    "accuracy",
    "exact_match",
    "exact_match_batch",
    "f1_score",
    "f1_score_batch",
    # similarity
    "bert_score",
    "bert_score_batch",
    "cosine_similarity",
    "cosine_similarity_batch",
    # rag
    "answer_relevance",
    "context_precision",
    "context_recall",
    "faithfulness",
    # safety
    "jailbreak",
    "jailbreak_batch",
    "toxicity",
    "toxicity_batch",
    # efficiency
    "cost_per_request",
    "format_valid",
    "format_valid_batch",
    "latency_avg",
    "latency_p95",
    "percentile",
    "tokens_per_request",
    # scorer
    "compute_composite_score",
    "grade",
    "normalize_score",
]
