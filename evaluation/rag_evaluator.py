"""
RAG 分段评测器

把「只看最终答案」扩展为「检索质量 + 生成质量」双段评估：
- Context Precision：检索到的文档有多少是相关的（检索噪声）
- Context Recall：该召回的是否都召回了（漏召回）
- Faithfulness：答案是否忠于上下文（幻觉）
- Answer Relevancy：答案是否回答了问题（答非所问）

并提供 4 象限归因矩阵，定位问题在检索段还是生成段。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.faithfulness_judge import judge_faithfulness
from evaluation.semantic_evaluator import batch_similarity, semantic_similarity

PRECISION_THRESHOLD = 0.75

# 归因矩阵：Context Recall × Faithfulness
QUADRANTS = [
    {
        "recall": "高", "faithfulness": "高",
        "diagnosis": "检索准、生成稳",
        "direction": "保持，关注边界场景",
    },
    {
        "recall": "低", "faithfulness": "高",
        "diagnosis": "漏召回，但模型诚实",
        "direction": "优化切分 / 换 Embedding / 加 Rerank",
    },
    {
        "recall": "高", "faithfulness": "低",
        "diagnosis": "召回了却没用上",
        "direction": "优化 Prompt，加强「必须基于上下文」约束",
    },
    {
        "recall": "低", "faithfulness": "低",
        "diagnosis": "检索和生成都有问题",
        "direction": "先修检索，再修生成（有先后顺序）",
    },
]


def eval_context_precision(contexts: list, ground_truth: str,
                           threshold: float = PRECISION_THRESHOLD) -> float:
    """上下文精度：检索结果中与标准答案相关的比例"""
    if not contexts:
        return 0.0
    relevant = sum(1 for ctx in contexts
                   if semantic_similarity(ctx, ground_truth) >= threshold)
    return relevant / len(contexts)


def eval_context_recall(contexts: list, expected_contexts: list,
                        threshold: float = PRECISION_THRESHOLD) -> float:
    """上下文召回：期望文档被检索到的比例"""
    if not expected_contexts:
        return 1.0
    if not contexts:
        return 0.0
    hit = sum(1 for exp in expected_contexts
              if any(semantic_similarity(ctx, exp) >= threshold for ctx in contexts))
    return hit / len(expected_contexts)


def eval_answer_relevancy(question: str, answer: str) -> float:
    """答案相关性：答案与问题的语义接近度"""
    return semantic_similarity(answer, question)


def eval_faithfulness(answer: str, contexts: list) -> dict:
    """忠实度：答案是否忠于上下文（原子论断核查）"""
    return judge_faithfulness(answer, contexts)


def eval_case(case: dict, result: dict,
              threshold: float = PRECISION_THRESHOLD) -> dict:
    """单条用例四维评测（逐条计算，适合调试）"""
    contexts = result.get("contexts", [])
    answer = result.get("answer", "")
    return {
        "case_id": case["id"],
        "category": case.get("category", ""),
        "context_precision": round(eval_context_precision(
            contexts, case.get("ground_truth", ""), threshold), 4),
        "context_recall": round(eval_context_recall(
            contexts, case.get("context", []), threshold), 4),
        "faithfulness": eval_faithfulness(answer, contexts)["score"],
        "answer_relevancy": round(eval_answer_relevancy(
            case["question"], answer), 4),
    }


def _retrieval_sims(cases: list, results: list):
    """一次性编码所有 (片段, 标准答案) 与 (片段, 期望上下文) 对，供各项指标复用"""
    precision_pairs, precision_lens = [], []
    recall_pairs, recall_lens = [], []

    for case, result in zip(cases, results):
        contexts = result.get("contexts", [])
        gt = case.get("ground_truth", "")
        expected = case.get("context", [])

        precision_lens.append(len(contexts))
        for ctx in contexts:
            precision_pairs.append((ctx, gt))

        recall_lens.append(len(expected))
        for exp in expected:
            for ctx in contexts:
                recall_pairs.append((ctx, exp))

    return (batch_similarity(precision_pairs), precision_lens,
            batch_similarity(recall_pairs), recall_lens)


def _precision_recall(cases: list, results: list, threshold: float,
                      p_sims: list, p_lens: list,
                      r_sims: list, r_lens: list) -> list:
    """基于已编码的相似度计算每条用例的 Precision / Recall"""
    pairs = []
    p_i = r_i = 0
    for idx, (case, result) in enumerate(zip(cases, results)):
        contexts = result.get("contexts", [])

        n_ctx = p_lens[idx]
        ctx_sims = p_sims[p_i:p_i + n_ctx]
        p_i += n_ctx
        precision = (sum(1 for s in ctx_sims if s >= threshold) / n_ctx) if n_ctx else 0.0

        n_exp = r_lens[idx]
        expected = case.get("context", [])
        if not expected:
            recall = 1.0
        elif not contexts:
            recall = 0.0
        else:
            block = r_sims[r_i:r_i + n_exp * n_ctx]
            r_i += n_exp * n_ctx
            hit = 0
            for e in range(n_exp):
                row = block[e * n_ctx:(e + 1) * n_ctx]
                if any(s >= threshold for s in row):
                    hit += 1
            recall = hit / n_exp

        pairs.append((precision, recall))
    return pairs


def eval_retrieval_sweep(cases: list, results: list,
                         thresholds: tuple) -> dict:
    """检索段阈值敏感度：同一批检索结果复算多组阈值的 P/R（只编码一次）"""
    p_sims, p_lens, r_sims, r_lens = _retrieval_sims(cases, results)
    sweep = {}
    for th in thresholds:
        pairs = _precision_recall(cases, results, th, p_sims, p_lens, r_sims, r_lens)
        n = len(pairs)
        sweep["%.2f" % th] = {
            "context_precision": round(sum(p for p, _ in pairs) / n, 4),
            "context_recall": round(sum(r for _, r in pairs) / n, 4),
        }
    return sweep


def eval_cases(cases: list, results: list,
               threshold: float = PRECISION_THRESHOLD) -> list:
    """
    批量四维评测：所有相似度一次性批量编码，避免逐条计算（55 条约 300 次编码）。
    """
    p_sims, p_lens, r_sims, r_lens = _retrieval_sims(cases, results)
    pr_pairs = _precision_recall(cases, results, threshold, p_sims, p_lens, r_sims, r_lens)
    relevancy_sims = batch_similarity(
        [((r or {}).get("answer", ""), c["question"]) for c, r in zip(cases, results)])

    scores = []
    for idx, (case, result) in enumerate(zip(cases, results)):
        precision, recall = pr_pairs[idx]
        faithful = eval_faithfulness(result.get("answer", ""), result.get("contexts", []))["score"]

        scores.append({
            "case_id": case["id"],
            "category": case.get("category", ""),
            "context_precision": round(precision, 4),
            "context_recall": round(recall, 4),
            "faithfulness": faithful,
            "answer_relevancy": round(relevancy_sims[idx], 4),
        })
    return scores


def diagnose(context_recall: float, faithfulness: float,
             cut: float = 0.5) -> dict:
    """4 象限归因：Context Recall × Faithfulness"""
    r = "高" if context_recall >= cut else "低"
    f = "高" if faithfulness >= cut else "低"
    for q in QUADRANTS:
        if q["recall"] == r and q["faithfulness"] == f:
            return {"quadrant": "%s召回 × %s忠实" % (r, f), **q}
    return {}


def aggregate(scores: list, cut: float = 0.5) -> dict:
    """汇总四维指标均值 + 归因象限分布"""
    if not scores:
        return {}
    n = len(scores)
    metrics = {
        key: round(sum(s[key] for s in scores) / n, 4)
        for key in ("context_precision", "context_recall",
                    "faithfulness", "answer_relevancy")
    }
    dist = {}
    for s in scores:
        q = diagnose(s["context_recall"], s["faithfulness"], cut)
        q["case_ids"] = []
        dist.setdefault(q["quadrant"], {"count": 0, "diagnosis": q["diagnosis"],
                                        "direction": q["direction"], "case_ids": []})
        dist[q["quadrant"]]["count"] += 1
        dist[q["quadrant"]]["case_ids"].append(s["case_id"])

    return {
        "case_count": n,
        "metrics": metrics,
        "quadrant_distribution": dist,
        "weakest_metric": min(metrics, key=metrics.get),
    }
