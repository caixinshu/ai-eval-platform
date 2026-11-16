"""
语义相似度评测器

用本地 Embedding 模型计算「答案」与「标准答案」的语义接近程度。
成本低、无网络依赖，适合大批量粗筛；但不能判断细节事实（否定句、数字），
精细判断交给 LLM Judge（Day 10）。

模型：BAAI/bge-small-zh-v1.5（中文语义，512 维，本地 CPU 可跑）
"""
import os
import sys

import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_model = None

# 相似度分档表：分档 -> (区间说明, 处理策略)
SIMILARITY_TIERS = [
    (0.95, "T1 几乎等价", "可直接判为通过"),
    (0.85, "T2 意思相同/细节有差异", "需 LLM 或人工复核"),
    (0.70, "T3 主题相关但不完全正确", "大概率有问题，重点抽查"),
    (0.00, "T4 基本不相关", "直接判为失败"),
]


def get_model() -> SentenceTransformer:
    """懒加载并缓存 Embedding 模型（避免每次评测重复加载）"""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度，向量为零时返回 0"""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def semantic_similarity(answer: str, ground_truth: str) -> float:
    """单条语义相似度 0-1"""
    if not answer or not ground_truth:
        return 0.0
    model = get_model()
    vecs = model.encode([answer, ground_truth], normalize_embeddings=True)
    return cosine(vecs[0], vecs[1])


def batch_similarity(pairs: list) -> list:
    """批量语义相似度：pairs = [(answer, ground_truth), ...]"""
    if not pairs:
        return []
    model = get_model()
    answers = [p[0] for p in pairs]
    truths = [p[1] for p in pairs]
    va = model.encode(answers, normalize_embeddings=True, batch_size=32)
    vt = model.encode(truths, normalize_embeddings=True, batch_size=32)
    return [float(np.dot(a, t)) for a, t in zip(va, vt)]


def similarity_tier(score: float) -> dict:
    """按分档表给出档位与处理策略"""
    for threshold, name, strategy in SIMILARITY_TIERS:
        if score >= threshold:
            return {"tier": name, "threshold": threshold, "strategy": strategy}
    return {"tier": SIMILARITY_TIERS[-1][1], "threshold": 0.0,
            "strategy": SIMILARITY_TIERS[-1][2]}


class SemanticEvaluator:
    """语义评测器：统一对外入口，供执行引擎调用"""

    def __init__(self, model_name: str = MODEL_NAME, threshold: float = 0.85):
        self.model_name = model_name
        self.threshold = threshold  # 通过阈值，由 calibrate_threshold.py 校准得出

    def similarity(self, answer: str, ground_truth: str) -> float:
        return semantic_similarity(answer, ground_truth)

    def batch(self, pairs: list) -> list:
        return batch_similarity(pairs)

    def evaluate(self, answer: str, ground_truth: str) -> dict:
        """返回相似度、是否通过、分档与处理策略"""
        score = self.similarity(answer, ground_truth)
        return {
            "score": round(score, 4),
            "passed": score >= self.threshold,
            "threshold": self.threshold,
            **similarity_tier(score),
        }


if __name__ == "__main__":
    print("单条:", round(semantic_similarity("支持7天无理由退款", "支持7天无理由退款，商品需保持完好"), 4))
    print("否定句:", round(semantic_similarity("不支持7天无理由退款", "支持7天无理由退款，商品需保持完好"), 4))
    print("批量:", [round(s, 4) for s in batch_similarity([
        ("退款3-5个工作日到账", "退款审核通过后3-5个工作日内原路退回"),
        ("退款需要30个工作日", "退款审核通过后3-5个工作日内原路退回"),
    ])])
    print("分档:", similarity_tier(0.91))
