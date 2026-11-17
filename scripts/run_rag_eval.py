"""
RAG 四维评测 + 检索参数调优实验

对黄金集跑分段评测，并对比不同 top_k 下的检索质量：
- Context Precision / Context Recall：评检索段
- Faithfulness / Answer Relevancy：评生成段

用法:
    python scripts/run_rag_eval.py                 # 默认 top_k = 2,3,5
    python scripts/run_rag_eval.py --top-k 1 5
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from app.rag import generate, get_collection_stats, retrieve
from eval_datasets import load_golden
from evaluation.rag_evaluator import aggregate, eval_cases, eval_retrieval_sweep

REPORT_PATH = Path("reports/rag_eval_v1.json")
METRIC_KEYS = ("context_precision", "context_recall",
               "faithfulness", "answer_relevancy")


def run_config(cases: list, top_k: int, thresholds: list) -> dict:
    """固定其它变量，只改 top_k，跑一轮四维评测（附带相似度阈值敏感度）"""
    results = []
    for case in cases:
        contexts = retrieve(case["question"], top_k=top_k)
        results.append({"contexts": contexts, "answer": generate(case["question"], contexts)})

    scores = eval_cases(cases, results)
    agg = aggregate(scores)
    # 按类别聚合，便于定位哪类问题检索差
    by_category = {}
    for s in scores:
        by_category.setdefault(s["category"], []).append(s)
    category_metrics = {
        cat: {k: round(sum(x[k] for x in items) / len(items), 4) for k in METRIC_KEYS}
        for cat, items in by_category.items()
    }

    # 阈值敏感度：复用同一批检索结果，只编码一次
    sweep = eval_retrieval_sweep(cases, results, tuple(thresholds))

    return {
        "top_k": top_k,
        "metrics": agg["metrics"],
        "weakest_metric": agg["weakest_metric"],
        "quadrant_distribution": {
            k: {"count": v["count"], "diagnosis": v["diagnosis"], "direction": v["direction"]}
            for k, v in agg["quadrant_distribution"].items()
        },
        "category_metrics": category_metrics,
        "threshold_sweep": sweep,
        "cases": scores,
    }


def main() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, nargs="+", default=[2, 3, 5])
    parser.add_argument("--thresholds", type=float, nargs="+",
                        default=[0.65, 0.70, 0.75])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cases = load_golden()
    if args.limit:
        cases = cases[:args.limit]

    stats = get_collection_stats()
    print("黄金集: %d 条 | 知识库: %d 片段 | embedding=%s"
          % (len(cases), stats["count"], stats["embedding_model"]))

    configs = []
    for k in args.top_k:
        print("\n[top_k=%d] 检索 + 生成 + 四维评测..." % k)
        cfg = run_config(cases, k, args.thresholds)
        configs.append(cfg)
        m = cfg["metrics"]
        print("  Precision=%.4f Recall=%.4f Faithfulness=%.4f Relevancy=%.4f"
              % (m["context_precision"], m["context_recall"],
                 m["faithfulness"], m["answer_relevancy"]))
        print("  最弱指标: %s" % cfg["weakest_metric"])
        for name, q in cfg["quadrant_distribution"].items():
            print("  %s: %d 条 -> %s" % (name, q["count"], q["direction"]))
        print("  阈值敏感度: " + " | ".join(
            "th=%s P=%.3f R=%.3f" % (th, v["context_precision"], v["context_recall"])
            for th, v in cfg["threshold_sweep"].items()))

    # 参数-指标曲线（控制台版）
    print("\n参数-指标对比")
    header = "top_k  " + "  ".join("%-12s" % k for k in METRIC_KEYS)
    print(header)
    for cfg in configs:
        print("%-6d " % cfg["top_k"] +
              "  ".join("%-12.4f" % cfg["metrics"][k] for k in METRIC_KEYS))

    # 选召回优先的最优配置（分段评测常见口径：先保证不遗漏）
    best = max(configs, key=lambda c: (c["metrics"]["context_recall"],
                                       c["metrics"]["context_precision"]))
    print("\n推荐配置: top_k=%d（Recall 优先，兼顾 Precision）" % best["top_k"])

    report = {
        "run_at": datetime.now().isoformat(),
        "dataset": "golden_set v1",
        "case_count": len(cases),
        "embedding_model": stats["embedding_model"],
        "model": stats["llm_model"],
        "configs": configs,
        "recommended_top_k": best["top_k"],
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("报告已保存: %s" % REPORT_PATH)
    return report


if __name__ == "__main__":
    main()
