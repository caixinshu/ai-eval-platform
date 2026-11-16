"""
语义相似度阈值校准脚本

用人工标注的 50 组「答案 / 标准答案 / 是否等价」样本，
网格搜索使 F1 最大的相似度阈值。

用法:
    python scripts/calibrate_threshold.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from evaluation.semantic_evaluator import batch_similarity

DATA_PATH = Path("eval_datasets/calibration_set.json")
REPORT_PATH = Path("reports/calibration_v1.json")


def load_samples(path: Path = DATA_PATH) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def grid_search(sims: list, labels: list, low: int = 40, high: int = 95) -> list:
    """
    在 [low/100, high/100] 上以 0.01 为步长搜索阈值，返回每个阈值的 PRF。

    判定口径：相似度 >= 阈值 视为「预测等价」，与 label=1 对比。
    """
    rows = []
    for i in range(low, high + 1):
        th = i / 100.0
        tp = sum(1 for s, l in zip(sims, labels) if s >= th and l == 1)
        fp = sum(1 for s, l in zip(sims, labels) if s >= th and l == 0)
        fn = sum(1 for s, l in zip(sims, labels) if s < th and l == 1)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({
            "threshold": round(th, 2),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn,
        })
    return rows


def main() -> dict:
    samples = load_samples()
    pairs = [(s["answer"], s["ground_truth"]) for s in samples]
    labels = [s["label"] for s in samples]

    sims = batch_similarity(pairs)
    pos = [s for s, l in zip(sims, labels) if l == 1]
    neg = [s for s, l in zip(sims, labels) if l == 0]

    print("样本数: %d（正例 %d / 负例 %d）" % (len(samples), len(pos), len(neg)))
    print("正例相似度: 均值 %.4f, 最低 %.4f" % (sum(pos) / len(pos), min(pos)))
    print("负例相似度: 均值 %.4f, 最高 %.4f" % (sum(neg) / len(neg), max(neg)))

    rows = grid_search(sims, labels)
    best = max(rows, key=lambda r: (r["f1"], r["threshold"]))
    print("\n最佳阈值: %.2f, F1: %.3f, Precision: %.3f, Recall: %.3f"
          % (best["threshold"], best["f1"], best["precision"], best["recall"]))

    # 分档统计，说明分档表的实际覆盖情况
    tiers = {"T1(>=0.95)": 0, "T2(0.85-0.95)": 0, "T3(0.70-0.85)": 0, "T4(<0.70)": 0}
    for s in sims:
        if s >= 0.95:
            tiers["T1(>=0.95)"] += 1
        elif s >= 0.85:
            tiers["T2(0.85-0.95)"] += 1
        elif s >= 0.70:
            tiers["T3(0.70-0.85)"] += 1
        else:
            tiers["T4(<0.70)"] += 1
    print("分档分布:", tiers)

    # 误判样本（最佳阈值下）
    errors = []
    for s, label, sim in zip(samples, labels, sims):
        predicted = 1 if sim >= best["threshold"] else 0
        if predicted != label:
            errors.append({
                "id": s["id"],
                "label": label,
                "similarity": round(sim, 4),
                "note": s.get("note", ""),
                "answer": s["answer"][:60],
            })
    print("误判数: %d" % len(errors))
    for e in errors[:10]:
        print("  %s label=%d sim=%.4f %s" % (e["id"], e["label"], e["similarity"], e["note"]))

    report = {
        "sample_count": len(samples),
        "positive_count": len(pos),
        "negative_count": len(neg),
        "positive_mean": round(sum(pos) / len(pos), 4),
        "positive_min": round(min(pos), 4),
        "negative_mean": round(sum(neg) / len(neg), 4),
        "negative_max": round(max(neg), 4),
        "best_threshold": best,
        "tier_distribution": tiers,
        "error_count": len(errors),
        "errors": errors,
        "grid": rows,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n校准报告已保存: %s" % REPORT_PATH)
    return report


if __name__ == "__main__":
    main()
