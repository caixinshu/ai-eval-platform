"""
门禁阈值推导（Day 22）

门禁阈值不能拍脑袋。这个脚本扫描历史评测报告，按指标统计分布，给出建议阈值：
- 硬阈值下限：mean - 2σ（安全固定 1.0）
- 允许相对下降：2σ，夹在 [0.03, 0.10]
- σ > 0.03（3 分）标记为「波动大」，应先解决稳定性再设门禁

用法：
    python scripts/derive_thresholds.py
    python scripts/derive_thresholds.py --glob "reports/baseline_golden_*.json"
    python scripts/derive_thresholds.py --write baselines/thresholds.json

注意：样本数 < 3 时只做参考，不自动改 GATE_RULES。
"""
import argparse
import glob
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.quality_gate import GATE_RULES, normalize_metrics

DEFAULT_GLOBS = ["reports/*.json", "baselines/*.json"]
UNSTABLE_STD = 0.03
MIN_SAMPLES = 3


def collect_values(paths: list) -> tuple:
    """返回 ({metric: [values]}, 实际读取成功的文件列表)"""
    values = {name: [] for name in GATE_RULES}
    sources = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        metrics = normalize_metrics(report)
        hit = {name: metrics[name] for name in GATE_RULES if name in metrics}
        if not hit:
            continue
        for name, value in hit.items():
            values[name].append(value)
        sources.append(str(path))
    return values, sources


def _round(value, digits=3):
    return round(float(value), digits)


def suggest_rule(name: str, samples: list) -> dict:
    """按历史样本给出建议阈值；样本不足时沿用当前规则并标注"""
    current = GATE_RULES[name]
    if name == "safety":
        return {
            "samples": len(samples),
            "suggested_min": 1.0,
            "suggested_max_drop": None,
            "unstable": False,
            "note": "安全一票否决，永远 1.0，不参与统计放宽",
        }

    if not samples:
        return {
            "samples": 0,
            "suggested_min": current.get("min"),
            "suggested_max_drop": current.get("max_drop"),
            "unstable": False,
            "note": "无历史样本，沿用当前规则",
        }

    mean = statistics.mean(samples)
    std = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    if len(samples) < MIN_SAMPLES:
        return {
            "samples": len(samples),
            "mean": _round(mean),
            "std": _round(std),
            "suggested_min": current.get("min"),
            "suggested_max_drop": current.get("max_drop"),
            "unstable": std > UNSTABLE_STD,
            "note": "样本 < %d，仅作参考，沿用当前规则" % MIN_SAMPLES,
        }

    suggested_min = None
    if "min" in current:
        # 硬阈值是质量目标，只能维持或收紧，不能因为当前分数低就下调
        suggested_min = _round(max(current["min"], mean - 2 * std), 2)
    suggested_drop = None
    if "max_drop" in current:
        suggested_drop = _round(min(0.10, max(0.03, 2 * std)), 3)

    unstable = std > UNSTABLE_STD
    if unstable:
        note = "波动 σ=%.3f > %.2f，先解决稳定性再收紧门禁" % (std, UNSTABLE_STD)
    elif "min" in current and mean < current["min"]:
        note = "当前均值低于质量目标，先提升再谈门禁，不要下调阈值"
    else:
        note = "分布稳定，可按建议值设置"
    return {
        "samples": len(samples),
        "mean": _round(mean),
        "std": _round(std),
        "min": _round(min(samples)),
        "max": _round(max(samples)),
        "suggested_min": suggested_min,
        "suggested_max_drop": suggested_drop,
        "unstable": unstable,
        "note": note,
    }


def derive(paths: list) -> dict:
    values, sources = collect_values(paths)
    result = {
        "generated_at": datetime.now().isoformat(),
        "sources": sources,
        "metrics": {name: suggest_rule(name, values[name])
                    for name in GATE_RULES},
    }
    return result


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description="基于历史报告推导门禁阈值")
    parser.add_argument("--glob", action="append", default=None,
                        help="报告文件通配符，可重复；默认 reports/*.json + baselines/*.json")
    parser.add_argument("--write", default=None,
                        help="把推导结果写成 JSON")
    args = parser.parse_args(argv)

    patterns = args.glob or DEFAULT_GLOBS
    paths = []
    for pattern in patterns:
        paths.extend(sorted(glob.glob(pattern)))
    result = derive(paths)

    print("=" * 78)
    print("门禁阈值推导（历史报告统计）")
    print("=" * 78)
    print("%-18s %6s %8s %8s %10s %12s  %s"
          % ("指标", "样本", "均值", "σ", "建议硬阈值", "建议max_drop", "备注"))
    for name, info in result["metrics"].items():
        print("%-18s %6d %8s %8s %10s %12s  %s"
              % (name, info["samples"], _fmt(info.get("mean")),
                 _fmt(info.get("std")), _fmt(info.get("suggested_min")),
                 _fmt(info.get("suggested_max_drop")), info["note"]))
    print("-" * 78)
    print("读取到 %d 份含指标的报告" % len(result["sources"]))
    if len(result["sources"]) < 3:
        print("[WARN] 报告样本偏少，建议先积累同一套评测集的历史结果")

    if args.write:
        output = Path(args.write)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print("推导结果已保存: %s" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
