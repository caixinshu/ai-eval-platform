"""
结果分析：分组统计 + badcase 聚类 + 优化建议

用法:
    python scripts/run_analysis.py --run reports/baseline_golden_v1.json --dataset golden
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from analysis.aggregator import group_badcases
from analysis.badcase import cluster_badcases
from eval_datasets import load_golden

REPORT_PATH = Path("reports/analysis_golden_v1.json")


def build_suggestions(report: dict, metric_counter: Counter,
                      category_stats: dict, clusters: list) -> list:
    """把数据结论翻译成可执行建议（每条都带证据）"""
    suggestions = []

    model = str(report.get("model", ""))
    if "mock" in model.lower():
        suggestions.append({
            "priority": 1,
            "action": "接入真实 LLM 后重跑基线",
            "evidence": "当前 model=%s，答案由检索片段拼接，正确性不具参考性" % model,
        })

    worst = [m for m, _ in metric_counter.most_common(2)]
    if any(m in ("context_precision", "context_recall") for m in worst):
        suggestions.append({
            "priority": 2,
            "action": "把 CP/CR 相关性阈值从 0.75 校准到 0.65-0.70",
            "evidence": "Day 11 实测：阈值 0.65 时 Recall 0.855，0.75 时仅 0.382；"
                        "期望片段与检索片段最大相似度均值仅 0.7223",
        })

    kb = report.get("knowledge_base", {}).get("count", 0)
    if kb and kb < 50:
        suggestions.append({
            "priority": 3,
            "action": "扩充知识库到 50+ 片段，并补充同义问法",
            "evidence": "当前仅 %d 个片段，top-2 已覆盖全部可召回内容，检索能力无提升空间" % kb,
        })

    if category_stats:
        worst_cat = max(category_stats.items(), key=lambda kv: kv[1]["count"])
        suggestions.append({
            "priority": 4,
            "action": "优先修复「%s」类问题（%d 条，占 badcase %.1f%%）"
                      % (worst_cat[0], worst_cat[1]["count"], worst_cat[1]["share"] * 100),
            "evidence": "该类失败最多，主要失败指标: %s"
                        % ", ".join("%s×%d" % (m, c)
                                    for m, c in worst_cat[1]["top_failed_metrics"]),
        })

    if clusters:
        biggest = clusters[0]
        suggestions.append({
            "priority": 5,
            "action": "针对最大 badcase 簇「%s」设计专项用例" % biggest["label"],
            "evidence": "该簇 %d 条，示例问题: %s"
                        % (biggest["size"], "；".join(biggest["sample_questions"][:2])),
        })

    return suggestions


def main() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="reports/baseline_golden_v1.json")
    parser.add_argument("--dataset", default="golden", choices=["golden"])
    parser.add_argument("--clusters", type=int, default=5)
    args = parser.parse_args()

    with open(args.run, encoding="utf-8") as f:
        report = json.load(f)
    cases = load_golden()

    badcases = report.get("badcases", [])
    print("报告: %s | 用例 %d | badcase %d"
          % (args.run, report.get("case_count", 0), len(badcases)))

    # 1. 按 category 分组
    category_stats = group_badcases(badcases, cases)
    print("\n[按类别分布]")
    for cat, s in category_stats.items():
        print("  %-10s %2d 条 (%.0f%%) 主要失败指标: %s"
              % (cat, s["count"], s["share"] * 100,
                 ", ".join("%s×%d" % (m, c) for m, c in s["top_failed_metrics"])))

    # 2. badcase 聚类
    clusters = cluster_badcases(badcases, args.clusters)
    print("\n[badcase 聚类]")
    for c in clusters:
        print("  簇%d %-18s %2d 条 | 例: %s"
              % (c["cluster_id"], c["label"], c["size"],
                 c["sample_questions"][0][:24]))

    # 3. 失败指标频次
    metric_counter = Counter(
        m["metric"] for b in badcases for m in b.get("failed_metrics", []))
    print("\n[失败指标频次] " + ", ".join("%s×%d" % kv for kv in metric_counter.most_common()))

    # 4. 优化建议
    suggestions = build_suggestions(report, metric_counter, category_stats, clusters)
    print("\n[优化建议]")
    for s in suggestions:
        print("  P%d %s\n      依据: %s" % (s["priority"], s["action"], s["evidence"]))

    result = {
        "run_at": datetime.now().isoformat(),
        "source_report": args.run,
        "case_count": report.get("case_count"),
        "badcase_count": len(badcases),
        "total_score": report.get("total_score"),
        "category_stats": category_stats,
        "clusters": [{k: v for k, v in c.items() if k != "cases"} for c in clusters],
        "failed_metric_counter": dict(metric_counter),
        "suggestions": suggestions,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n分析结果已保存: %s" % REPORT_PATH)
    return result


if __name__ == "__main__":
    main()
