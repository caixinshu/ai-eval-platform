"""
RAG 专项指标 (RAG Metrics)
- faithfulness: 忠实度（回答是否基于上下文）
- context_precision: 上下文精度（检索结果相关性）
- context_recall: 上下文召回率（上下文覆盖答案信息）
- answer_relevance: 答案相关性（回答是否针对问题）

这些指标本质上需要 LLM-as-Judge，本模块提供：
1. 基于规则的降级实现（无需 LLM，用于快速验证框架）
2. 可接入 LLM 的接口（llm_judge 参数）
"""
import re
from typing import Callable, Optional


def _split_sentences(text: str) -> list[str]:
    """按句号、问号、感叹号切分句子"""
    sentences = re.split(r"[。！？.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]


def _split_claims(text: str) -> list[str]:
    """将回答拆分为声明（句子级）"""
    return _split_sentences(text)


def faithfulness(
    answer: str,
    contexts: list[str],
    llm_judge: Optional[Callable] = None,
) -> float:
    """
    忠实度：回答中的声明有多少能从上下文中得到支持。

    Args:
        answer: 模型回答
        contexts: 检索到的上下文列表
        llm_judge: 可选的 LLM 评分函数 (claim, contexts) -> float

    Returns:
        0-1 的忠实度分数
    """
    claims = _split_claims(answer)
    if not claims:
        return 1.0

    context_text = " ".join(contexts)

    if llm_judge:
        scores = [llm_judge(claim, contexts) for claim in claims]
        return sum(scores) / len(scores)

    # 降级规则实现：声明中的关键词是否出现在上下文中
    supported = 0
    for claim in claims:
        keywords = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", claim)]
        if not keywords:
            supported += 1
            continue
        hit = sum(1 for kw in keywords if kw in context_text)
        if hit / len(keywords) >= 0.5:  # 50% 关键词命中算支持
            supported += 1
    return supported / len(claims)


def context_precision(
    question: str,
    contexts: list[str],
    llm_judge: Optional[Callable] = None,
) -> float:
    """
    上下文精度：检索到的上下文中有多少与问题相关。

    Args:
        question: 用户问题
        contexts: 检索到的上下文列表
        llm_judge: 可选 LLM 评分 (question, context) -> float
    """
    if not contexts:
        return 0.0

    if llm_judge:
        scores = [llm_judge(question, ctx) for ctx in contexts]
        return sum(s >= 0.5 for s in scores) / len(contexts)

    # 降级规则：问题中的关键词是否出现在上下文中
    q_keywords = set(re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", question))
    if not q_keywords:
        return 1.0

    relevant = 0
    for ctx in contexts:
        hits = sum(1 for kw in q_keywords if kw in ctx)
        if hits / len(q_keywords) >= 0.3:
            relevant += 1
    return relevant / len(contexts)


def context_recall(
    gold_answer: str,
    contexts: list[str],
    llm_judge: Optional[Callable] = None,
) -> float:
    """
    上下文召回率：黄金答案中的信息有多少能在上下文中找到。

    Args:
        gold_answer: 黄金答案
        contexts: 检索到的上下文列表
        llm_judge: 可选 LLM 评分 (gold_fact, contexts) -> float
    """
    facts = _split_claims(gold_answer)
    if not facts:
        return 1.0

    context_text = " ".join(contexts)

    if llm_judge:
        scores = [llm_judge(fact, contexts) for fact in facts]
        return sum(s >= 0.5 for s in scores) / len(facts)

    # 降级规则：黄金答案中的关键词是否出现在上下文中
    covered = 0
    for fact in facts:
        keywords = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", fact)]
        if not keywords:
            covered += 1
            continue
        hits = sum(1 for kw in keywords if kw in context_text)
        if hits / len(keywords) >= 0.5:
            covered += 1
    return covered / len(facts)


def answer_relevance(
    question: str,
    answer: str,
    llm_judge: Optional[Callable] = None,
) -> float:
    """
    答案相关性：回答是否针对问题。

    Args:
        question: 用户问题
        answer: 模型回答
        llm_judge: 可选 LLM 评分 (question, answer) -> float
    """
    if not answer:
        return 0.0

    if llm_judge:
        return llm_judge(question, answer)

    # 降级规则：问题关键词在回答中的覆盖率
    q_keywords = set(re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", question))
    if not q_keywords:
        return 1.0

    hits = sum(1 for kw in q_keywords if kw in answer)
    return hits / len(q_keywords)


if __name__ == "__main__":
    # 自测
    question = "什么是机器学习？"
    answer = "机器学习是人工智能的一个分支，通过数据训练模型来做预测。"
    contexts = [
        "机器学习是人工智能的核心技术之一，它使计算机能够从数据中学习。",
        "深度学习是机器学习的子领域，使用多层神经网络。",
    ]
    gold = "机器学习是人工智能的一个分支，利用算法从数据中学习规律并进行预测。"

    print(f"faithfulness: {faithfulness(answer, contexts):.4f}")
    print(f"context_precision: {context_precision(question, contexts):.4f}")
    print(f"context_recall: {context_recall(gold, contexts):.4f}")
    print(f"answer_relevance: {answer_relevance(question, answer):.4f}")
