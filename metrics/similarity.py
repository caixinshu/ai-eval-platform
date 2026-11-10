"""
语义相似度指标 (Similarity Metrics)
- cosine_similarity: 余弦相似度（可选 sentence-transformers，降级用 TF-IDF）
- bert_score: BERTScore（可选 bert-score 库，降级用近似实现）
"""
import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """分词：英文按单词，中文按 2-gram 字，混合兼容"""
    # 提取英文单词和中文 2-gram
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fa5]", text)
    # 中文用 2-gram
    for i in range(len(chinese) - 1):
        tokens.append(chinese[i] + chinese[i + 1])
    return tokens


def _tfidf_vectorize(texts: list[str]) -> list[dict[str, float]]:
    """简易 TF-IDF 向量化（无外部依赖），使用平滑 IDF"""
    tokenized = [_tokenize(t) for t in texts]
    doc_count = len(tokenized)
    # IDF with smoothing: log((N+1)/(df+1)) + 1
    idf: dict[str, float] = {}
    for tokens in tokenized:
        for token in set(tokens):
            idf[token] = idf.get(token, 0) + 1
    idf = {k: math.log((doc_count + 1) / (v + 1)) + 1 for k, v in idf.items()}

    vectors = []
    for tokens in tokenized:
        if not tokens:
            vectors.append({})
            continue
        tf = Counter(tokens)
        vec = {k: (v / len(tokens)) * idf[k] for k, v in tf.items()}
        vectors.append(vec)
    return vectors


def cosine_sim(v1: dict[str, float], v2: dict[str, float]) -> float:
    """两个稀疏向量的余弦相似度"""
    common = set(v1.keys()) & set(v2.keys())
    dot = sum(v1[k] * v2[k] for k in common)
    norm1 = math.sqrt(sum(v * v for v in v1.values()))
    norm2 = math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def cosine_similarity(prediction: str, gold: str) -> float:
    """
    余弦相似度。
    优先使用 sentence-transformers（如已安装），否则降级为 TF-IDF + 余弦。
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
        emb1, emb2 = model.encode([prediction, gold])
        dot = sum(a * b for a, b in zip(emb1, emb2))
        norm1 = math.sqrt(sum(a * a for a in emb1))
        norm2 = math.sqrt(sum(b * b for b in emb2))
        return float(dot / (norm1 * norm2))
    except ImportError:
        # 降级：TF-IDF 余弦
        vecs = _tfidf_vectorize([prediction, gold])
        return cosine_sim(vecs[0], vecs[1])


def cosine_similarity_batch(predictions: list[str], golds: list[str]) -> float:
    """批量余弦相似度的平均"""
    if not predictions:
        return 0.0
    return sum(cosine_similarity(p, g) for p, g in zip(predictions, golds)) / len(predictions)


def bert_score(prediction: str, gold: str) -> float:
    """
    BERTScore 近似值。
    优先使用 bert-score 库，否则降级为 token 级字符重叠加权。
    """
    try:
        from bert_score import score
        P, R, F = score([prediction], [gold], lang="zh", verbose=False)
        return float(F.item())
    except ImportError:
        # 降级实现：基于 token 的 F1 作为 BERTScore 的近似
        try:
            from .accuracy import f1_score
        except ImportError:
            from accuracy import f1_score
        return f1_score(prediction, gold)


def bert_score_batch(predictions: list[str], golds: list[str]) -> float:
    """批量 BERTScore 的平均"""
    if not predictions:
        return 0.0
    return sum(bert_score(p, g) for p, g in zip(predictions, golds)) / len(predictions)


if __name__ == "__main__":
    print("余弦相似度 (TF-IDF 降级):")
    print(f"  '今天天气很好' vs '今天天气不错' -> {cosine_similarity('今天天气很好', '今天天气不错'):.4f}")
    print(f"  '巴黎是法国首都' vs '北京是中国首都' -> {cosine_similarity('巴黎是法国首都', '北京是中国首都'):.4f}")
    print(f"  '完全相同的句子' vs '完全相同的句子' -> {cosine_similarity('完全相同的句子', '完全相同的句子'):.4f}")

    print("\nBERTScore (降级为 F1):")
    print(f"  'Paris is capital of France' vs 'The capital of France is Paris' -> {bert_score('Paris is capital of France', 'The capital of France is Paris'):.4f}")
