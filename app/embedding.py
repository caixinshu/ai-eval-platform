"""
Embedding 函数工厂

优先级：
1. sentence-transformers (bge-small-zh-v1.5) — 中文语义检索，效果最好
2. 本地字符 n-gram TF-IDF — 无需模型，稳定可靠，作为降级方案

注意：优先使用 sentence-transformers (bge-small-zh)，
加载失败则降级到本地字符 n-gram embedding。
"""
import hashlib
import os
from typing import List

import numpy as np


# ==================== 本地降级 embedding ====================

class LocalEmbeddingFunction:
    """
    基于字符 n-gram + 哈希的本地 embedding。
    无需下载模型，稳定可靠。
    对中文有一定效果（字符级匹配），但语义理解弱于 transformer 模型。
    """
    def __init__(self, dim: int = 256, ngram_range: tuple = (2, 3)):
        self.dim = dim
        self.ngram_range = ngram_range

    def _char_ngrams(self, text: str) -> list:
        """提取字符 n-gram"""
        text = text.strip()
        grams = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for i in range(len(text) - n + 1):
                grams.append(text[i:i + n])
        return grams

    def _embed_one(self, text: str) -> List[float]:
        """对单条文本生成 embedding"""
        vec = np.zeros(self.dim, dtype=np.float32)
        grams = self._char_ngrams(text)
        if not grams:
            return vec.tolist()

        # 词频统计
        from collections import Counter
        counts = Counter(grams)
        total = sum(counts.values())

        for gram, count in counts.items():
            # 哈希到固定维度
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            tf = count / total
            vec[idx] += tf

        # L2 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def __call__(self, input: List[str]) -> List[List[float]]:
        """chromadb EmbeddingFunction 接口"""
        return [self._embed_one(t) for t in input]

    def name(self) -> str:
        """chromadb 要求的标识方法"""
        return "local-ngram"


# ==================== 获取 embedding 函数 ====================

def get_embedding_function():
    """
    返回 chromadb 兼容的 embedding function。
    优先 sentence-transformers (bge-small-zh)，失败则用本地 embedding。
    """
    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

    # 环境变量强制使用本地
    if os.getenv("USE_LOCAL_EMBEDDING", "").lower() in ("1", "true", "yes"):
        print("[INFO] 使用本地 embedding（环境变量指定）")
        return LocalEmbeddingFunction(), "local-ngram"

    # 尝试 sentence-transformers
    try:
        from chromadb.utils import embedding_functions
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        print(f"[INFO] 尝试加载 sentence-transformers: {model_name}")
        return (
            embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name
            ),
            model_name,
        )
    except Exception as e:
        print(f"[WARN] 加载 sentence-transformers 失败: {e}，降级到本地 embedding")
        return LocalEmbeddingFunction(), "local-ngram"
