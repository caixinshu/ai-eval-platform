"""
Ragas 语义评测脚本

评测 4 个 RAG 核心指标：
- faithfulness: 忠实度（回答是否基于上下文）
- answer_relevancy: 答案相关性（回答是否针对问题）
- context_precision: 上下文精度（检索结果相关性）
- context_recall: 上下文召回率（上下文覆盖黄金答案）

策略：
- 有 LLM API Key 时，使用 Ragas 官方 LLM-as-Judge 实现
- 无 API Key 时，降级到 metrics.rag 的规则实现（关键词覆盖度）
"""
import os
from typing import Optional

from datasets import Dataset

# 复用已有的规则降级实现
try:
    from metrics.rag import (
        faithfulness as rule_faithfulness,
        context_precision as rule_context_precision,
        context_recall as rule_context_recall,
        answer_relevance as rule_answer_relevance,
    )
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from metrics.rag import (
        faithfulness as rule_faithfulness,
        context_precision as rule_context_precision,
        context_recall as rule_context_recall,
        answer_relevance as rule_answer_relevance,
    )


def _has_llm_api() -> bool:
    """检查是否配置了 LLM API Key"""
    return bool(os.getenv("LLM_API_KEY"))


def run_ragas_eval(cases: list, qa_func=None, precomputed: list = None) -> dict:
    """
    运行 Ragas 评测。

    Args:
        cases: 评测用例列表，每条含 question, ground_truth
        qa_func: 被测应用的问答函数 question -> {answer, contexts}
        precomputed: 预收集的问答结果列表 [{question, answer, contexts, ground_truth}]

    Returns:
        {
            "faithfulness": float,
            "answer_relevancy": float,
            "context_precision": float,
            "context_recall": float,
            "engine": "ragas" | "rule",
        }
    """
    # 收集所有用例的问答结果
    questions, answers, contexts, ground_truths = [], [], [], []

    if precomputed:
        for item in precomputed:
            questions.append(item["question"])
            answers.append(item["answer"])
            contexts.append(item["contexts"])
            ground_truths.append(item.get("ground_truth", ""))
    else:
        for case in cases:
            result = qa_func(case["question"])
            questions.append(case["question"])
            answers.append(result["answer"])
            contexts.append(result["contexts"])
            ground_truths.append(case.get("ground_truth", ""))

    # 有 API Key 时用 Ragas
    if _has_llm_api():
        return _run_with_ragas(questions, answers, contexts, ground_truths)

    # 无 API Key 时用规则降级
    return _run_with_rules(questions, answers, contexts, ground_truths)


def _run_with_ragas(questions, answers, contexts, ground_truths) -> dict:
    """使用 Ragas 官方实现（需要 LLM API Key）"""
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    from langchain_openai.chat_models import ChatOpenAI

    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
    )

    ds = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })

    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm,
    )

    return {
        "faithfulness": float(result["faithfulness"]),
        "answer_relevancy": float(result["answer_relevancy"]),
        "context_precision": float(result["context_precision"]),
        "context_recall": float(result["context_recall"]),
        "engine": "ragas",
    }


def _run_with_rules(questions, answers, contexts, ground_truths) -> dict:
    """使用规则降级实现（无需 LLM）"""
    faith_scores, rel_scores, prec_scores, recall_scores = [], [], [], []

    for q, a, ctxs, gt in zip(questions, answers, contexts, ground_truths):
        faith_scores.append(rule_faithfulness(a, ctxs))
        rel_scores.append(rule_answer_relevance(q, a))
        prec_scores.append(rule_context_precision(q, ctxs))
        recall_scores.append(rule_context_recall(gt, ctxs))

    def _avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "faithfulness": round(_avg(faith_scores), 4),
        "answer_relevancy": round(_avg(rel_scores), 4),
        "context_precision": round(_avg(prec_scores), 4),
        "context_recall": round(_avg(recall_scores), 4),
        "engine": "rule",
    }


def run_ragas_eval_single(question: str, answer: str, contexts: list,
                          ground_truth: str) -> dict:
    """单条用例的 Ragas 评测（用于 badcase 分析）"""
    return {
        "faithfulness": rule_faithfulness(answer, contexts),
        "answer_relevancy": rule_answer_relevance(question, answer),
        "context_precision": rule_context_precision(question, contexts),
        "context_recall": rule_context_recall(ground_truth, contexts),
    }


if __name__ == "__main__":
    # 自测
    cases = [
        {"question": "退款政策是什么？", "ground_truth": "支持7天无理由退款"},
    ]

    def mock_qa(q):
        return {"answer": "支持7天无理由退款，商品需保持完好。",
                "contexts": ["支持7天无理由退款，商品需保持完好，退款3-5个工作日到账"]}

    result = run_ragas_eval(cases, mock_qa)
    print("Ragas 评测结果:")
    for k, v in result.items():
        print(f"  {k}: {v}")
