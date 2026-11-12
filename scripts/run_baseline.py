"""
首轮基线评测脚本

流程：
1. 加载黄金集
2. 对每条用例调用被测 RAG 应用
3. 运行 Ragas 语义评测（4 指标）
4. 运行规则评测（安全/格式/长度/正确性）
5. 用 metrics.scorer 计算综合得分
6. 生成基线报告 + badcase 清单

用法:
    python scripts/run_baseline.py
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from eval_datasets import load_golden
from app.rag import ask, get_collection_stats
from evaluation.ragas_eval import run_ragas_eval, run_ragas_eval_single
from evaluation.rule_eval import run_rule_eval, run_rule_eval_single
from metrics.scorer import compute_composite_score, grade

# 阈值：低于此值标记为 badcase
BADCASE_THRESHOLDS = {
    "faithfulness": 0.5,
    "answer_relevancy": 0.3,
    "context_precision": 0.3,
    "context_recall": 0.3,
    "safety": 1.0,
    "format": 1.0,
    "correctness": 0.3,
}


def run_baseline(dataset: str = "golden", limit: int = None) -> dict:
    """
    跑首轮基线评测。

    Args:
        dataset: 数据集名称 (golden/adversarial/edge)
        limit: 限制用例数量（None 表示全部）
    """
    # 1. 加载数据集
    if dataset == "golden":
        cases = load_golden()
    elif dataset == "adversarial":
        from eval_datasets import load_adversarial
        cases = load_adversarial()
    elif dataset == "edge":
        from eval_datasets import load_edge
        cases = load_edge()
    else:
        raise ValueError(f"未知数据集: {dataset}")

    if limit:
        cases = cases[:limit]

    print(f"加载 {dataset} 集: {len(cases)} 条")
    stats = get_collection_stats()
    print(f"知识库: {stats['count']} 片段, embedding={stats['embedding_model']}, llm={stats['llm_model']}")

    # 2. 收集所有问答结果（只调用一次 ask，避免重复检索）
    print(f"\n收集问答结果 ({len(cases)} 条)...")
    start = time.time()
    precomputed = []
    for i, case in enumerate(cases, 1):
        if i % 10 == 0:
            print(f"  进度: {i}/{len(cases)}")
        result = ask(case["question"])
        precomputed.append({
            "question": case["question"],
            "answer": result["answer"],
            "contexts": result["contexts"],
            "ground_truth": case.get("ground_truth", ""),
        })
    collect_time = time.time() - start
    print(f"  收集完成, 耗时: {collect_time:.1f}s")

    # 3. 运行语义评测（Ragas 或规则降级）
    print("\n运行语义评测...")
    start = time.time()
    ragas_result = run_ragas_eval(cases, precomputed=precomputed)
    ragas_time = time.time() - start
    print(f"  引擎: {ragas_result['engine']}, 耗时: {ragas_time:.1f}s")
    print(f"  faithfulness={ragas_result['faithfulness']:.4f}")
    print(f"  answer_relevancy={ragas_result['answer_relevancy']:.4f}")
    print(f"  context_precision={ragas_result['context_precision']:.4f}")
    print(f"  context_recall={ragas_result['context_recall']:.4f}")

    # 4. 运行规则评测
    print("\n运行规则评测...")
    start = time.time()
    rule_result = run_rule_eval(cases, precomputed=precomputed)
    rule_time = time.time() - start
    print(f"  耗时: {rule_time:.1f}s")
    for k, v in rule_result.items():
        print(f"  {k}={v:.4f}")

    # 4. 综合评分
    metrics = {
        "faithfulness": ragas_result["faithfulness"],
        "answer_relevance": ragas_result["answer_relevancy"],
        "context_precision": ragas_result["context_precision"],
        "context_recall": ragas_result["context_recall"],
        "correctness": rule_result["correctness"],
        "safety": rule_result["safety"],
        "format": rule_result["format"],
    }

    score_result = compute_composite_score(metrics, preset="default")

    # 5. badcase 分析
    print("\n分析 badcase...")
    badcases = analyze_badcases(cases, precomputed=precomputed)

    # 6. 组装报告
    report = {
        "run_at": datetime.now().isoformat(),
        "prompt_version": "v1.2.0",
        "dataset": f"{dataset}_set v1",
        "case_count": len(cases),
        "engine": ragas_result["engine"],
        "knowledge_base": stats,
        "metrics": {
            **{k: round(v, 4) for k, v in ragas_result.items() if k != "engine"},
            **rule_result,
        },
        "total_score": score_result["total"],
        "grade": grade(score_result["total"]),
        "badcase_count": len(badcases),
        "badcases": badcases,
    }

    # 7. 保存报告
    report_path = Path("reports") / f"baseline_{dataset}_v1.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n综合得分: {report['total_score']}/100  {report['grade']}")
    print(f"Badcase 数: {len(badcases)}")
    print(f"报告已保存: {report_path}")

    return report


def analyze_badcases(cases: list, precomputed: list = None) -> list:
    """
    分析 badcase：逐条评测，标记低于阈值的指标。

    Args:
        cases: 评测用例列表
        precomputed: 预收集的问答结果列表（避免重复调用 ask）
    """
    badcases = []

    if precomputed is None:
        # 兼容：未传 precomputed 时现场收集
        precomputed = []
        for case in cases:
            result = ask(case["question"])
            precomputed.append({
                "question": case["question"],
                "answer": result["answer"],
                "contexts": result["contexts"],
                "ground_truth": case.get("ground_truth", ""),
            })

    for i, (case, item) in enumerate(zip(cases, precomputed), 1):
        if i % 10 == 0:
            print(f"  分析中... {i}/{len(cases)}")

        answer = item["answer"]
        contexts = item["contexts"]
        gt = item.get("ground_truth", "")
        question = item["question"]

        # 单条评测
        ragas_scores = run_ragas_eval_single(
            question, answer, contexts, gt
        )
        rule_scores = run_rule_eval_single(answer, gt, question)

        # 检查哪些指标低于阈值
        failed_metrics = []
        all_scores = {**ragas_scores, **rule_scores}
        for metric, threshold in BADCASE_THRESHOLDS.items():
            score = all_scores.get(metric)
            if score is not None and score < threshold:
                failed_metrics.append({
                    "metric": metric,
                    "score": round(score, 4),
                    "threshold": threshold,
                })

        if failed_metrics:
            badcases.append({
                "id": case.get("id", f"case_{i}"),
                "question": question,
                "answer": answer[:200],
                "ground_truth": gt[:200] if gt else "",
                "context_count": len(contexts),
                "failed_metrics": failed_metrics,
            })

    return badcases


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="跑首轮基线评测")
    parser.add_argument("--dataset", default="golden",
                        choices=["golden", "adversarial", "edge"],
                        help="评测数据集")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制用例数量")
    args = parser.parse_args()

    run_baseline(dataset=args.dataset, limit=args.limit)
