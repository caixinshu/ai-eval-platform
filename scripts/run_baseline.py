"""
基线评测脚本（支持黄金集 / 对抗集 / 边界集）

流程：
1. 加载数据集
2. 一次性收集所有问答结果（每条只调一次 ask，异常单独记录）
3. 黄金集：Ragas 语义评测（4 指标，无 API Key 时规则降级）
4. 对抗集 / 边界集：断言评测（must_contain_any / must_not_contain / status_code）
5. 规则评测（安全/格式/长度/正确性）
6. 综合评分：黄金集用加权综合分；对抗/边界集以断言通过率为准（安全一票否决）
7. 生成基线报告 + badcase 清单

用法:
    python scripts/run_baseline.py                      # 黄金集
    python scripts/run_baseline.py --dataset adversarial
    python scripts/run_baseline.py --dataset edge
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
from evaluation.assertion_eval import run_assertion_eval
from metrics.scorer import compute_composite_score, grade

# 阈值：低于此值标记为 badcase（仅黄金集使用）
BADCASE_THRESHOLDS = {
    "faithfulness": 0.5,
    "answer_relevancy": 0.3,
    "context_precision": 0.3,
    "context_recall": 0.3,
    "safety": 1.0,
    "format": 1.0,
    "correctness": 0.3,
}

# 需要语义评测的数据集（有 ground_truth）
SEMANTIC_DATASETS = {"golden"}


def load_cases(dataset: str) -> list:
    """按名称加载数据集"""
    if dataset == "golden":
        return load_golden()
    if dataset == "adversarial":
        from eval_datasets import load_adversarial
        return load_adversarial()
    if dataset == "edge":
        from eval_datasets import load_edge
        return load_edge()
    raise ValueError(f"未知数据集: {dataset}")


def collect_results(cases: list) -> list:
    """收集所有问答结果；单条异常不中断整体评测，记录到 error 字段"""
    precomputed = []
    for i, case in enumerate(cases, 1):
        if i % 10 == 0:
            print(f"  进度: {i}/{len(cases)}")
        try:
            result = ask(case["question"])
            precomputed.append({
                "question": case["question"],
                "answer": result["answer"],
                "contexts": result["contexts"],
                "ground_truth": case.get("ground_truth", ""),
                "error": None,
            })
        except Exception as e:
            print(f"  [ERROR] {case.get('id')} 调用异常: {e}")
            precomputed.append({
                "question": case["question"],
                "answer": "",
                "contexts": [],
                "ground_truth": case.get("ground_truth", ""),
                "error": f"{type(e).__name__}: {e}",
            })
    return precomputed


def run_baseline(dataset: str = "golden", limit: int = None) -> dict:
    """
    跑一轮基线评测。

    Args:
        dataset: 数据集名称 (golden/adversarial/edge)
        limit: 限制用例数量（None 表示全部）
    """
    # 1. 加载数据集
    cases = load_cases(dataset)
    if limit:
        cases = cases[:limit]

    print(f"加载 {dataset} 集: {len(cases)} 条")
    stats = get_collection_stats()
    print(f"知识库: {stats['count']} 片段, embedding={stats['embedding_model']}, llm={stats['llm_model']}")

    # 2. 收集所有问答结果（只调用一次 ask）
    print(f"\n收集问答结果 ({len(cases)} 条)...")
    start = time.time()
    precomputed = collect_results(cases)
    print(f"  收集完成, 耗时: {time.time() - start:.1f}s")
    error_count = sum(1 for item in precomputed if item["error"])
    if error_count:
        print(f"  应用异常: {error_count} 条")

    # 3. 语义评测（仅黄金集，需要 ground_truth）
    ragas_result = None
    if dataset in SEMANTIC_DATASETS:
        print("\n运行语义评测...")
        start = time.time()
        ragas_result = run_ragas_eval(cases, precomputed=precomputed)
        print(f"  引擎: {ragas_result['engine']}, 耗时: {time.time() - start:.1f}s")
        for key in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            print(f"  {key}={ragas_result[key]:.4f}")

    # 4. 断言评测（对抗集 / 边界集）
    assertion_result = None
    if dataset not in SEMANTIC_DATASETS:
        print("\n运行断言评测...")
        assertion_result = run_assertion_eval(cases, precomputed)
        print(f"  通过率: {assertion_result['pass_rate']:.4f} "
              f"({assertion_result['passed']}/{assertion_result['total']})")
        for category, bucket in assertion_result["by_category"].items():
            print(f"  {category}: {bucket['passed']}/{bucket['total']} = {bucket['pass_rate']:.4f}")

    # 5. 规则评测
    print("\n运行规则评测...")
    start = time.time()
    rule_result = run_rule_eval(cases, precomputed=precomputed)
    print(f"  耗时: {time.time() - start:.1f}s")
    for key, value in rule_result.items():
        print(f"  {key}={value:.4f}")

    # 6. 综合评分
    if dataset in SEMANTIC_DATASETS:
        metrics = {
            "faithfulness": ragas_result["faithfulness"],
            "answer_relevance": ragas_result["answer_relevancy"],
            "context_precision": ragas_result["context_precision"],
            "context_recall": ragas_result["context_recall"],
            "correctness": rule_result["correctness"],
            "safety": rule_result["safety"],
            "format": rule_result["format"],
        }
        total_score = compute_composite_score(metrics, preset="default")["total"]
    else:
        metrics = {
            "assertion_pass_rate": assertion_result["pass_rate"],
            "safety": rule_result["safety"],
            "format": rule_result["format"],
            "length": rule_result["length"],
        }
        # 对抗/边界集：安全一票否决，通过率为核心得分
        total_score = 0.0 if rule_result["safety"] < 1.0 else round(assertion_result["pass_rate"] * 100, 2)

    # 7. badcase 分析
    print("\n分析 badcase...")
    badcases = analyze_badcases(cases, precomputed=precomputed, assertion_result=assertion_result)

    # 8. 组装报告（字段对齐执行计划 Table：run_at / prompt_version / model / dataset / metrics / total_score / badcase_ids）
    report = {
        "run_at": datetime.now().isoformat(),
        "prompt_version": "v1.2.0",
        "model": stats["llm_model"],
        "embedding_model": stats["embedding_model"],
        "dataset": f"{dataset}_set v1",
        "case_count": len(cases),
        "engine": ragas_result["engine"] if ragas_result else "assertion",
        "knowledge_base": stats,
        "metrics": {k: round(v, 4) for k, v in metrics.items()},
        "total_score": total_score,
        "grade": grade(total_score),
        "app_error_count": error_count,
        "badcase_count": len(badcases),
        "badcase_ids": [bc["id"] for bc in badcases],
        "badcases": badcases,
    }
    if assertion_result:
        report["assertion"] = {
            "pass_rate": assertion_result["pass_rate"],
            "passed": assertion_result["passed"],
            "failed": assertion_result["failed"],
            "total": assertion_result["total"],
            "by_category": assertion_result["by_category"],
        }

    # 9. 保存报告
    report_path = Path("reports") / f"baseline_{dataset}_v1.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n综合得分: {report['total_score']}/100  {report['grade']}")
    print(f"Badcase 数: {len(badcases)}")
    print(f"报告已保存: {report_path}")

    return report


def analyze_badcases(cases: list, precomputed: list = None,
                     assertion_result: dict = None) -> list:
    """
    分析 badcase。

    - 有 assertion_result（对抗/边界集）：断言未通过即为 badcase
    - 否则（黄金集）：指标低于阈值即为 badcase
    """
    if precomputed is None:
        precomputed = collect_results(cases)

    badcases = []

    # 对抗集 / 边界集：按断言结果生成
    if assertion_result:
        for detail in assertion_result["details"]:
            if detail["passed"]:
                continue
            item = next((p for p in precomputed if p["question"] == detail["question"]), {})
            badcases.append({
                "id": detail["id"],
                "category": detail["category"],
                "question": detail["question"],
                "expected_behavior": detail["expected_behavior"],
                "answer": item.get("answer", "")[:200],
                "reason": detail["reason"],
            })
        return badcases

    # 黄金集：按指标阈值
    for i, (case, item) in enumerate(zip(cases, precomputed), 1):
        if i % 10 == 0:
            print(f"  分析中... {i}/{len(cases)}")

        answer = item["answer"]
        contexts = item["contexts"]
        gt = item.get("ground_truth", "")
        question = item["question"]

        ragas_scores = run_ragas_eval_single(question, answer, contexts, gt)
        rule_scores = run_rule_eval_single(answer, gt, question)

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

    parser = argparse.ArgumentParser(description="跑基线评测")
    parser.add_argument("--dataset", default="golden",
                        choices=["golden", "adversarial", "edge"],
                        help="评测数据集")
    parser.add_argument("--limit", type=int, default=None,
                        help="限制用例数量")
    args = parser.parse_args()

    run_baseline(dataset=args.dataset, limit=args.limit)
