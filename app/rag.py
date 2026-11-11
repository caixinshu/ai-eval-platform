"""
RAG 应用核心：检索 + 生成 两段链路

依赖：
- chromadb: 向量数据库
- sentence-transformers: 中文 embedding (bge-small-zh-v1.5)
- openai: LLM 调用

降级策略（无 API Key / 无模型时）：
- embedding: 优先 bge-small-zh，失败则用 chromadb 默认 all-MiniLM-L6-v2
- LLM: 优先调用真实 API，无 key 时用 mock_llm 基于上下文生成
"""
import os
from typing import Optional

# ==================== 向量数据库 ====================

from chromadb import PersistentClient

from app.embedding import get_embedding_function

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_base")
TOP_K = int(os.getenv("TOP_K", "3"))

chroma = PersistentClient(path=CHROMA_PATH)
embed_fn, embed_model = get_embedding_function()
collection = chroma.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embed_fn,
)


# ==================== LLM 调用 ====================

from openai import OpenAI

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

_llm_client: Optional[OpenAI] = None
if LLM_API_KEY:
    _llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def mock_llm_answer(question: str, contexts: list) -> str:
    """
    无 API Key 时的降级生成器。
    基于检索到的上下文拼接答案，模拟「基于资料回答」的行为。
    """
    if not contexts:
        return "抱歉，参考资料中没有找到与您问题相关的信息，无法回答。"

    # 取前 2 个上下文片段，截断后拼接
    parts = []
    for ctx in contexts[:2]:
        # 每个片段取前 150 字
        parts.append(ctx[:150])
    answer = "。".join(parts)
    if len(answer) > 200:
        answer = answer[:200] + "..."
    return answer


def generate(question: str, contexts: list) -> str:
    """基于上下文生成答案。有 API Key 调真实 LLM，否则用 mock。"""
    from prompts.qa_prompt import build_messages

    context_text = "\n\n---\n\n".join(contexts) if contexts else "（无相关资料）"

    if _llm_client is not None:
        messages = build_messages(context_text, question)
        try:
            resp = _llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[WARN] LLM 调用失败，降级到 mock: {e}")
            return mock_llm_answer(question, contexts)
    else:
        return mock_llm_answer(question, contexts)


# ==================== 检索 ====================

def retrieve(question: str, top_k: int = TOP_K) -> list:
    """检索相关文档片段"""
    result = collection.query(query_texts=[question], n_results=top_k)
    docs = result.get("documents", [[]])[0]
    return docs


# ==================== 完整问答链路 ====================

def ask(question: str) -> dict:
    """完整问答链路：检索 -> 生成"""
    contexts = retrieve(question)
    answer = generate(question, contexts)
    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "context_count": len(contexts),
    }


# ==================== 工具函数 ====================

def get_collection_stats() -> dict:
    """获取知识库统计信息"""
    return {
        "collection": COLLECTION_NAME,
        "count": collection.count(),
        "embedding_model": embed_model,
        "llm_model": LLM_MODEL if _llm_client else "mock (no API key)",
    }
