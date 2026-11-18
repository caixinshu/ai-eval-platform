"""
Badcase 聚类：找出高频问题模式

用 bge 向量 + KMeans 把相似问题聚成一类，再给每类自动打标签（高频二元组）。
标签只用于人工快速浏览，不代表真实语义分类。
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.semantic_evaluator import get_model

STOPWORDS = {"你们", "我们", "可以", "什么", "怎么", "如何", "是否", "请问",
             "吗", "呢", "的", "是", "有", "能", "么", "怎", "吗？"}


def _top_terms(texts: list, k: int = 3) -> list:
    """取高频中文二元组作为簇标签"""
    counter = Counter()
    for text in texts:
        chars = re.sub(r"[\s，。！？、,.!?：:；;「」\"'（）()]", "", text or "")
        for i in range(len(chars) - 1):
            bg = chars[i:i + 2]
            if any(s in bg for s in STOPWORDS) or len(bg) != 2:
                continue
            counter[bg] += 1
    return [term for term, _ in counter.most_common(k)]


def cluster_badcases(badcases: list, n_clusters: int = 5) -> list:
    """对 badcase 的问题做聚类，返回按簇大小降序的列表"""
    if not badcases:
        return []
    if len(badcases) < n_clusters:
        return [{"cluster_id": 0, "size": len(badcases), "label": "全部",
                 "sample_questions": [b["question"] for b in badcases],
                 "cases": badcases}]

    from sklearn.cluster import KMeans

    texts = [b["question"] for b in badcases]
    vecs = get_model().encode(texts, normalize_embeddings=True)
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=42).fit_predict(vecs)

    clusters = []
    for k in range(n_clusters):
        members = [b for b, l in zip(badcases, labels) if l == k]
        if not members:
            continue
        clusters.append({
            "cluster_id": k,
            "size": len(members),
            "label": " / ".join(_top_terms([m["question"] for m in members])),
            "sample_questions": [m["question"] for m in members][:3],
            "case_ids": [m["id"] for m in members],
            "cases": members,
        })
    return sorted(clusters, key=lambda x: -x["size"])
