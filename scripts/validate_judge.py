"""
校验 LLM Judge 与人工打分的一致性

口径：Judge 分数换算回 0-5，与人工分差 ≤1 视为一致。
一致率 <80% 时不能直接用于线上判定，需优化 rubric 或换模型。

用法:
    python scripts/validate_judge.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from evaluation.llm_judge import LLMJudge

DATA_PATH = Path("eval_datasets/judge_validation_set.json")
REPORT_PATH = Path("reports/judge_validation_v1.json")
TOLERANCE = 1


def main() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        samples = json.load(f)

    judge = LLMJudge()
    print("Judge 模式: %s | 模型: %s" % ("llm" if judge.available else "fallback(无 API Key)",
                                        judge.model))

    rows = []
    agreements = []
    abs_errors = []
    for s in samples:
        r = judge.score(s["question"], s["answer"], s["ground_truth"])
        machine = int(round(r["score"] * 5))
        human = int(s["human_score"])
        diff = abs(machine - human)
        ok = diff <= TOLERANCE
        agreements.append(ok)
        abs_errors.append(diff)
        rows.append({
            "id": s["id"],
            "human_score": human,
            "judge_score": machine,
            "judge_raw": round(r["score"], 4),
            "reason": r.get("reason", ""),
            "agreement": ok,
        })

    rate = sum(agreements) / len(agreements)
    print("样本数: %d" % len(samples))
    print("一致率: %.1f%%（允许 1 分误差）" % (rate * 100))
    print("平均绝对误差: %.2f 分" % (sum(abs_errors) / len(abs_errors)))

    bad = [r for r in rows if not r["agreement"]]
    print("不一致样本: %d" % len(bad))
    for b in bad:
        print("  %s 人工=%d Judge=%d %s" % (b["id"], b["human_score"],
                                            b["judge_score"], b["reason"]))

    conclusion = "可用" if rate >= 0.8 else "需优化 rubric"
    if not judge.available:
        conclusion += "（当前为降级模式，接入真实 LLM 后需重新校验）"
    print("结论:", conclusion)

    report = {
        "judge_source": "llm" if judge.available else "fallback",
        "judge_model": judge.model,
        "sample_count": len(samples),
        "tolerance": TOLERANCE,
        "agreement_rate": round(rate, 4),
        "mean_abs_error": round(sum(abs_errors) / len(abs_errors), 4),
        "conclusion": conclusion,
        "rows": rows,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("报告已保存: %s" % REPORT_PATH)
    return report


if __name__ == "__main__":
    main()
