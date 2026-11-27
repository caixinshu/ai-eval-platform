"""
线上 badcase 回流 CLI（Day 24）

用法：
    # 收集近 7 天差评，同类问题至少出现 3 次才回流，写入待标注
    python scripts/reflow_badcases.py

    # 预览不写入
    python scripts/reflow_badcases.py --dry-run --min-count 1

    # 人工确认：补标准答案后转 verified=true（才能进回归/门禁）
    python scripts/reflow_badcases.py --verify fresh_ab12cd34 --ground-truth "支持7天无理由退款"

    # 查看回流进度
    python scripts/reflow_badcases.py --stats
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import SessionLocal, init_db
from monitor.badcase_reflow import (load_cases, merge_into_file, reflow_cases,
                                     stats as reflow_stats, verify_case)
from monitor.feedback_collector import BadcaseCollector

DEFAULT_OUTPUT = "eval_datasets/fresh_set.json"


def _print_stats(cases: list) -> None:
    info = reflow_stats(cases)
    print("回流用例：共 %d 条 / 待标注 %d / 已入集 %d"
          % (info["total"], info["pending"], info["verified"]))
    for category, bucket in info["by_category"].items():
        print("  %-16s 共 %d / 待标注 %d / 已入集 %d"
              % (category, bucket["total"], bucket["pending"], bucket["verified"]))


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description="线上 badcase 回流与人工确认")
    parser.add_argument("--days", type=int, default=7, help="回看天数")
    parser.add_argument("--min-count", type=int, default=3,
                        help="同类问题至少出现次数（默认 3）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="只预览不写文件")
    parser.add_argument("--stats", action="store_true", help="只查看回流进度")
    parser.add_argument("--verify", default=None, help="人工确认的用例 ID")
    parser.add_argument("--ground-truth", default=None, help="人工补充的标准答案")
    parser.add_argument("--category", default=None, help="人工修正的问题分类")
    args = parser.parse_args(argv)

    if args.stats:
        _print_stats(load_cases(args.output))
        return 0

    if args.verify:
        try:
            case = verify_case(args.output, args.verify,
                               args.ground_truth or "", args.category)
        except (KeyError, ValueError) as exc:
            print("[ERROR] %s" % exc)
            return 2
        print("已确认 %s，verified=true，ground_truth=%s"
              % (case["id"], case["ground_truth"]))
        _print_stats(load_cases(args.output))
        return 0

    init_db()
    session = SessionLocal()
    try:
        badcases = BadcaseCollector().collect_badcases(days=args.days, db=session)
    finally:
        session.close()

    existing = load_cases(args.output)
    new_cases = reflow_cases(badcases, existing, min_count=args.min_count)

    print("近 %d 天差评 %d 条，过滤后待回流 %d 条"
          % (args.days, len(badcases), len(new_cases)))
    if badcases:
        print("差评分类分布: %s"
              % dict(Counter(item["category"] for item in badcases)))
    for case in new_cases:
        print("  %s  [%s] %s" % (case["id"], case["category"], case["question"][:40]))

    if args.dry_run:
        print("[dry-run] 未写入 %s" % args.output)
        return 0

    added = merge_into_file(args.output, new_cases)
    print("已写入 %s，新增 %d 条（verified=false，等待人工补标准答案）"
          % (args.output, len(added)))
    _print_stats(load_cases(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
