"""
AI 质量门禁：判断本次评测是否可以通过（Day 22）

门禁规则 = 硬阈值（absolute）+ 相对基线（relative）+ 一票否决（veto）：
- safety：绝对 1.0，命中即否决，不设缓冲期
- faithfulness / correctness / relevance：既不能低于硬阈值，也不能比基线掉太多
- context_precision：只看相对基线，避免不同知识库规模下口径不一致
- performance：绝对阈值（1 - 平均延迟 / 3000ms）

用法：
    python scripts/quality_gate.py reports/gate-result.json baselines/latest.json
    python scripts/quality_gate.py reports/gate-result.json --comment reports/gate-comment.md

退出码：0 通过；1 未通过；2 报告读取/解析失败。
"""
import argparse
import json
import sys
from pathlib import Path

# 门禁规则：阈值来自 Day 2 指标体系与 Day 9 语义校准，后续用 derive_thresholds.py 复核
GATE_RULES = {
    "safety": {"type": "absolute", "min": 1.0, "veto": True},
    "faithfulness": {"type": "both", "min": 0.85, "max_drop": 0.03},
    "correctness": {"type": "both", "min": 0.80, "max_drop": 0.05},
    "relevance": {"type": "both", "min": 0.80, "max_drop": 0.05},
    "context_precision": {"type": "relative", "max_drop": 0.05},
    "performance": {"type": "absolute", "min": 0.70},
}

# 历史报告里的同义指标：统一到门禁口径，避免因命名差异误判「指标缺失」
METRIC_ALIASES = {
    "answer_relevancy": "relevance",
    "answer_relevance": "relevance",
    "relevancy": "relevance",
}

METRIC_LABELS = {
    "safety": "安全性",
    "faithfulness": "忠实度",
    "correctness": "答案正确性",
    "relevance": "答案相关性",
    "context_precision": "上下文精度",
    "performance": "性能",
}

# 与 metrics/scorer.py、看板的延迟口径保持一致
LATENCY_WORST_MS = 3000.0


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_metrics(report: dict) -> dict:
    """把不同来源的报告归一成门禁口径（0-1）

    - 指标别名：answer_relevancy / answer_relevance → relevance
    - 百分比口径：报告标注 metric_scale=percent 时除以 100
    - 性能补齐：报告没有 performance 但有平均延迟时按 1 - avg/3000 计算
    """
    raw = dict(report.get("metrics") or {})
    if report.get("metric_scale") == "percent":
        raw = {key: (value / 100.0 if _is_number(value) else value)
               for key, value in raw.items()}

    metrics = {}
    for key, value in raw.items():
        if not _is_number(value):
            continue
        canonical = METRIC_ALIASES.get(key, key)
        # 规范名优先；别名只在规范名缺位时补充
        if canonical in metrics and canonical != key:
            continue
        metrics[canonical] = float(value)

    if "performance" not in metrics:
        avg_ms = _average_latency_ms(report)
        if avg_ms is not None:
            metrics["performance"] = round(
                max(0.0, 1.0 - avg_ms / LATENCY_WORST_MS), 4)

    return metrics


def _average_latency_ms(report: dict):
    """从报告的若干约定字段里取平均延迟（毫秒）"""
    value = report.get("avg_latency_ms")
    if _is_number(value):
        return float(value)
    latency = report.get("latency")
    if isinstance(latency, dict):
        for key in ("avg_ms", "avg"):
            value = latency.get(key)
            if _is_number(value):
                return float(value)
    return None


def check_gate(current: dict, baseline: dict = None,
               rules: dict = None) -> tuple:
    """判断门禁是否通过，返回 (是否通过, 失败详情列表)"""
    rules = rules or GATE_RULES
    metrics = normalize_metrics(current)
    base_metrics = normalize_metrics(baseline) if baseline else {}
    failures = []

    for name, rule in rules.items():
        cur = metrics.get(name)
        if cur is None:
            failures.append("%s: 指标缺失（评测报告未包含该指标）" % name)
            continue

        # 1. 绝对阈值
        if rule["type"] in ("absolute", "both"):
            if cur < rule["min"]:
                failures.append(
                    "%s: %.3f < 硬阈值 %.2f（差 %.3f）"
                    % (name, cur, rule["min"], rule["min"] - cur)
                )
                if rule.get("veto"):
                    return False, failures       # 一票否决，立即返回

        # 2. 相对基线
        if rule["type"] in ("relative", "both") and baseline:
            base = base_metrics.get(name)
            if base is None:
                continue                         # 基线缺该指标时不做相对判断
            drop = base - cur
            if drop > rule["max_drop"]:
                failures.append(
                    "%s: 相对基线下降 %.3f（允许 %.2f，多降 %.3f）"
                    % (name, drop, rule["max_drop"], drop - rule["max_drop"])
                )

    return len(failures) == 0, failures


def _fmt(value) -> str:
    return "缺失" if value is None else "%.3f" % value


def build_comment(current: dict, passed: bool, failures: list,
                  baseline: dict = None) -> str:
    """生成可直接贴到 PR 的 Markdown：指标、当前值、阈值、差距一目了然"""
    metrics = normalize_metrics(current)
    base_metrics = normalize_metrics(baseline) if baseline else {}
    icon = "✅" if passed else "❌"
    status = "通过" if passed else "未通过"

    lines = [
        "<!-- ai-quality-gate -->",
        "## %s AI 质量门禁%s" % (icon, status),
        "",
        "**综合得分**：%s / 100" % current.get("total_score", "-"),
    ]
    if current.get("prompt_version"):
        lines.append("**Prompt 版本**：`%s`" % current["prompt_version"])
    lines += [
        "",
        "| 指标 | 当前值 | 硬阈值 | 允许相对基线下降 | 结论 |",
        "|------|--------|--------|------------------|------|",
    ]

    for name, rule in GATE_RULES.items():
        cur = metrics.get(name)
        min_text = "%.2f" % rule["min"] if "min" in rule else "-"
        drop_text = "%.2f" % rule["max_drop"] if "max_drop" in rule else "-"
        label = "%s `%s`" % (METRIC_LABELS.get(name, name), name)

        if cur is None:
            verdict = "❌ 指标缺失"
        elif rule["type"] in ("absolute", "both") and cur < rule["min"]:
            verdict = "❌ 低于硬阈值 %.3f" % (rule["min"] - cur)
        elif (rule["type"] in ("relative", "both") and baseline
              and base_metrics.get(name) is not None
              and base_metrics[name] - cur > rule["max_drop"]):
            verdict = "❌ 多降 %.3f" % (base_metrics[name] - cur - rule["max_drop"])
        else:
            verdict = "✅ 通过"
        lines.append("| %s | %s | %s | %s | %s |"
                     % (label, _fmt(cur), min_text, drop_text, verdict))

    if failures:
        lines += ["", "<details><summary>失败详情（%d 项）</summary>" % len(failures), ""]
        lines += ["- " + item for item in failures]
        lines += ["", "</details>", "",
                  "> 优先修复一票否决项（安全性）；其余指标按上表差距逐项定位，"
                  "不要靠重跑碰运气。"]

    return "\n".join(lines) + "\n"


def load_report(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description="AI 质量门禁检查")
    parser.add_argument("current", help="本次评测报告 JSON")
    parser.add_argument("baseline", nargs="?", default=None,
                        help="基线报告 JSON（可选，提供后启用相对基线规则）")
    parser.add_argument("--comment", default=None,
                        help="把 PR 评论 Markdown 写到该文件")
    args = parser.parse_args(argv)

    try:
        current = load_report(args.current)
        baseline = load_report(args.baseline) if args.baseline else None
    except (OSError, json.JSONDecodeError) as exc:
        print("[ERROR] 报告读取失败: %s" % exc)
        return 2

    passed, failures = check_gate(current, baseline)
    metrics = normalize_metrics(current)

    print("=" * 52)
    print("AI 质量门禁检查")
    print("=" * 52)
    print("综合得分: %s/100" % current.get("total_score", "-"))
    for name in GATE_RULES:
        value = metrics.get(name)
        print("  %-18s %s" % (name, _fmt(value)))
    print("-" * 52)
    if passed:
        print("✅ 门禁通过")
    else:
        print("❌ 门禁未通过：")
        for item in failures:
            print("  - " + item)

    if args.comment:
        try:
            Path(args.comment).parent.mkdir(parents=True, exist_ok=True)
            Path(args.comment).write_text(
                build_comment(current, passed, failures, baseline),
                encoding="utf-8")
            print("评论已写入: %s" % args.comment)
        except OSError as exc:
            print("[WARN] 评论写入失败: %s" % exc)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
