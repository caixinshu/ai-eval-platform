"""
Prompt 版本差异 CLI（Day 23）

用法：
    python scripts/prompt_diff.py reports/baseline.json reports/current.json
    python scripts/prompt_diff.py base.json cur.json --threshold 0.05 \
        --json reports/prompt-diff.json --markdown reports/prompt-diff.md

输入可以是：
- run_eval.py 的输出（含 case_results）
- 平台 /api/runs/{id}/results 的 JSON（含 items）
- 直接的逐用例列表
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.prompt_diff import (diff_results, load_cases, render_markdown,
                                  risk_note, summarize_categories)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description="对比两个 Prompt 版本的逐用例结果")
    parser.add_argument("baseline", help="基线版本用例结果 JSON")
    parser.add_argument("current", help="当前版本用例结果 JSON")
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="显著变化阈值（0-1，默认 0.05 即 5 分）")
    parser.add_argument("--label-baseline", default="baseline")
    parser.add_argument("--label-current", default="current")
    parser.add_argument("--json", default=None, help="差异结果 JSON 输出路径")
    parser.add_argument("--markdown", default=None, help="差异报告 Markdown 输出路径")
    args = parser.parse_args(argv)

    try:
        baseline = load_cases(args.baseline)
        current = load_cases(args.current)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("[ERROR] 结果读取失败: %s" % exc)
        return 2

    diff = diff_results(current, baseline, args.threshold)
    stats = summarize_categories(diff)
    note = risk_note(diff, stats)

    print("=" * 58)
    print("Prompt 版本差异：%s → %s" % (args.label_baseline, args.label_current))
    print("=" * 58)
    print("基线 %d 条 / 当前 %d 条 / 基线独有 %d 条"
          % (len(baseline), len(current),
             len({row["case_id"] for row in baseline}
                 - {row["case_id"] for row in current})))
    print("提升 %d / 退化 %d / 未变 %d / 净变化 %+d"
          % (diff["summary"]["improved_count"],
             diff["summary"]["degraded_count"],
             diff["unchanged_count"], diff["summary"]["net_change"]))
    print("风险提示: %s" % note)
    print("-" * 58)
    for category, item in stats.items():
        print("  %-16s 提升 %d / 退化 %d / 平均 %+.2f"
              % (category, item["improved"], item["degraded"],
                 item["avg_delta"]))

    if diff["degraded"]:
        print("-" * 58)
        print("退化明细（前 10 条）：")
        for item in diff["degraded"][:10]:
            print("  %-8s %-10s %+.2f  %s"
                  % (item["case_id"], item["category"], item["delta"],
                     item["question"][:32]))

    payload = {
        "generated_at": datetime.now().isoformat(),
        "baseline_label": args.label_baseline,
        "current_label": args.label_current,
        "baseline_path": args.baseline,
        "current_path": args.current,
        "summary": diff["summary"],
        "threshold": diff["threshold"],
        "risk_note": note,
        "categories": stats,
        "improved": diff["improved"],
        "degraded": diff["degraded"],
        "unchanged_count": diff["unchanged_count"],
    }

    if args.json:
        output = Path(args.json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print("差异 JSON 已保存: %s" % output)

    if args.markdown:
        output = Path(args.markdown)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_markdown(diff, args.label_current, args.label_baseline),
            encoding="utf-8")
        print("差异报告已保存: %s" % output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
