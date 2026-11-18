"""
生成 HTML 评测报告 v1

要求（对应执行计划）：
- 第一屏是结论区：能否上线 + 一句话主因 + 1-3 条行动项
- 指标卡 + 进度条
- 三类数据集横向对比
- badcase 按类别分布 + 可展开明细
- 原始数据可下载（data URI，报告自包含、可离线打开）

用法:
    python scripts/generate_report.py
"""
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinja2 import Template

REPORT_DIR = Path("reports")
OUT_PATH = REPORT_DIR / "report_v1.html"
TEMPLATE_PATH = Path("templates/report.html")
PASS_GATE = 80

METRIC_LABELS = {
    "faithfulness": "忠实度",
    "answer_relevance": "答案相关性",
    "context_precision": "上下文精度",
    "context_recall": "上下文召回",
    "correctness": "正确性",
    "safety": "安全性",
    "format": "格式合规",
    "length": "长度合规",
}

# 指标偏低时的业务含义，用于生成「一句话主因」
METRIC_MEANING = {
    "answer_relevance": "答案与问题不相关（答非所问）",
    "context_precision": "检索结果噪声高（无关片段占比大）",
    "context_recall": "关键知识没被召回（漏召回）",
    "faithfulness": "答案缺乏上下文依据（幻觉）",
    "correctness": "答案内容不正确",
    "length": "答案长度不符合要求",
    "format": "输出格式不符合要求",
    "safety": "存在安全风险",
}


def _pct(value: float) -> int:
    """指标值统一按百分制换算成进度条宽度"""
    if value <= 1.0:
        return max(0, min(100, round(value * 100)))
    return max(0, min(100, round(value)))


def build_metrics(metrics: dict) -> list:
    rows = []
    for key, val in metrics.items():
        rows.append({
            "key": key,
            "label": METRIC_LABELS.get(key, key),
            "value": ("%.4f" % val) if isinstance(val, float) and val <= 1 else ("%.2f" % val),
            "ratio": _pct(val),
        })
    return rows


def build_verdict(report: dict, metrics: dict, suggestions: list) -> dict:
    score = report.get("total_score", 0)
    if score >= PASS_GATE:
        cls, label = "pass", "可上线"
    elif score >= 70:
        cls, label = "warn", "有条件通过"
    else:
        cls, label = "fail", "不可上线"

    # 取两个最差指标解释主因
    worst = sorted(metrics.items(), key=lambda kv: kv[1])[:2]
    parts = ["%s（%s）" % (METRIC_MEANING.get(k, k), "%.4f" % v) for k, v in worst]
    cause = "；".join(parts)

    evidence = "本次评测用例 %d 条，badcase %d 条（%.0f%%），平均分 %.2f。" % (
        report.get("case_count", 0), report.get("badcase_count", 0),
        (report.get("badcase_count", 0) / report.get("case_count", 1) * 100),
        score)
    if "mock" in str(report.get("model", "")).lower():
        evidence += " 当前模型为 %s，答案由检索片段直接拼接，分数仅代表链路基线，不代表真实模型能力。" % report["model"]

    actions = [s for s in suggestions if s.get("priority", 99) <= 3][:3]
    if not actions:
        actions = suggestions[:3]
    return {"cls": cls, "label": label, "gate": PASS_GATE, "cause": cause,
            "evidence": evidence, "actions": actions}


def build_categories(category_stats: dict) -> tuple:
    if not category_stats:
        return [], ""
    items = sorted(category_stats.items(), key=lambda kv: -kv[1]["count"])
    peak = max(v["count"] for _, v in items)
    rows = [{"name": cat, "count": v["count"],
             "width": max(6, round(v["count"] / peak * 100))} for cat, v in items]
    spread = items[0][1]["count"] - items[-1][1]["count"]
    note = ("失败最多的「%s」%d 条、最少的「%s」%d 条，相差 %d 条："
            "badcase 基本按业务类别均匀分布，说明问题在通用链路（生成方式 / 检索阈值），"
            "而不是某一类知识缺失。" % (items[0][0], items[0][1]["count"],
                                    items[-1][0], items[-1][1]["count"], spread))
    return rows, note


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> Path:
    golden = load_json(REPORT_DIR / "baseline_golden_v1.json")
    if golden is None:
        raise SystemExit("缺少 reports/baseline_golden_v1.json，请先运行 baseline")
    analysis = load_json(REPORT_DIR / "analysis_golden_v1.json") or {}
    suggestions = analysis.get("suggestions", [])

    datasets = []
    for name, fname in (("黄金集", "baseline_golden_v1.json"),
                        ("对抗集", "baseline_adversarial_v1.json"),
                        ("边界集", "baseline_edge_v1.json")):
        d = load_json(REPORT_DIR / fname)
        if d:
            datasets.append({"name": name, "case_count": d.get("case_count", 0),
                             "total_score": d.get("total_score", 0),
                             "grade": d.get("grade", ""),
                             "badcase_count": d.get("badcase_count", 0)})

    categories, category_note = build_categories(analysis.get("category_stats", {}))

    badcases = golden.get("badcases", [])[:20]
    for b in badcases:
        text = b.get("answer", "")
        b["answer"] = text if len(text) <= 600 else text[:600] + "\n...（已截断）"

    raw = json.dumps(golden, ensure_ascii=False, indent=2)
    raw_uri = "data:application/json;charset=utf-8;base64," + \
              base64.b64encode(raw.encode("utf-8")).decode()

    metrics = build_metrics(golden.get("metrics", {}))
    context = {
        "report": golden,
        "metrics": metrics,
        "verdict": build_verdict(golden, golden.get("metrics", {}), suggestions),
        "datasets": datasets,
        "categories": categories,
        "category_note": category_note,
        "badcases": badcases,
        "raw_data_uri": raw_uri,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    html = Template(TEMPLATE_PATH.read_text(encoding="utf-8")).render(**context)
    OUT_PATH.write_text(html, encoding="utf-8")

    print("报告已生成: %s（%.1f KB）" % (OUT_PATH, OUT_PATH.stat().st_size / 1024))
    print("结论: %s | 总分 %.2f | 主因: %s" % (
        context["verdict"]["label"], golden.get("total_score", 0),
        context["verdict"]["cause"]))
    print("行动项 %d 条 | 数据集 %d 个 | 类别 %d 个 | badcase 展示 %d 条"
          % (len(context["verdict"]["actions"]), len(datasets),
             len(categories), len(badcases)))
    return OUT_PATH


if __name__ == "__main__":
    main()
