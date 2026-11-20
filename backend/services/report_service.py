"""评测结果报告：JSON 聚合 + 自包含 HTML"""
import json
from datetime import datetime

from jinja2 import Template

from backend.models.dataset import Dataset
from backend.models.run import EvalResult, EvalRun, MetricSnapshot
from analysis.comparator import compare_runs

METRIC_LABELS = {
    "rule_score": "规则得分",
    "correctness": "答案正确性",
    "faithfulness": "忠实度",
    "answer_relevance": "答案相关性",
    "context_precision": "上下文精度",
    "context_recall": "上下文召回",
}

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>评测报告 {{ run.id }}</title>
<style>
body{margin:0;background:#f6f7f9;color:#1b1f24;
     font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:28px 20px 56px}
.card{background:#fff;border:1px solid #e6e8eb;border-radius:10px;padding:20px 22px;margin-bottom:16px}
h1{font-size:22px;margin:0 0 6px} h2{font-size:16px;margin:0 0 12px}
.sub{color:#6b7280;font-size:13px}
.score{font-size:40px;font-weight:700}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;color:#fff;font-size:12px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #e6e8eb}
th{color:#6b7280;font-size:12.5px}
.chip{display:inline-block;background:#fdeceb;color:#b42318;border-radius:6px;padding:1px 7px;font-size:12px;margin:0 4px 4px 0}
.ans{color:#4b5563;max-width:520px;word-break:break-word}
</style></head><body><div class="wrap">
<div class="card">
  <div class="sub">{{ dataset_name }} · Prompt {{ run.prompt_version }} · {{ run.model_name or 'mock' }}</div>
  <h1>评测报告</h1>
  <div class="score">{{ "%.2f"|format(score) }}<span style="font-size:16px;color:#6b7280"> / 100</span></div>
  <div style="margin-top:6px"><span class="badge" style="background:{{ badge_color }}">{{ badge }}</span>
  <span class="sub">{{ total }} 条用例 · 通过 {{ passed }} · 失败 {{ failed }}</span></div>
</div>
<div class="card"><h2>指标</h2><table>
<tr><th>指标</th><th>均值</th></tr>
{% for m in metrics %}<tr><td>{{ m.label }}</td><td>{{ m.value }}</td></tr>{% endfor %}
</table></div>
<div class="card"><h2>Badcase（前 {{ badcases|length }} 条）</h2><table>
<tr><th>用例</th><th>问题</th><th>回答</th><th>失败指标</th></tr>
{% for b in badcases %}<tr><td>{{ b.case_id }}</td><td>{{ b.question }}</td>
<td class="ans">{{ b.answer }}</td><td>{{ b.failed|join(", ") }}</td></tr>{% endfor %}
</table></div>
<div class="card sub">任务 {{ run.id }} · 生成于 {{ generated_at }}</div>
</div></body></html>""")


def _metrics_of(db, run: EvalRun) -> dict:
    rows = db.query(MetricSnapshot).filter_by(run_id=run.id).all()
    return {r.metric_name: float(r.value) for r in rows}


def build_report(db, run: EvalRun) -> dict:
    results = db.query(EvalResult).filter_by(run_id=run.id).all()
    passed = sum(1 for r in results if r.passed)
    metrics = _metrics_of(db, run)
    badcases = []
    for r in results:
        if r.passed:
            continue
        badcases.append({
            "case_id": r.case_id, "question": r.question, "answer": r.answer,
            "failed": [METRIC_LABELS.get(k, k) for k, v in (r.metrics or {}).items()
                       if isinstance(v, (int, float)) and v < 0.6],
        })
    dataset = db.get(Dataset, run.dataset_id) if run.dataset_id else None
    return {
        "run_id": run.id,
        "dataset": dataset.name if dataset else None,
        "prompt_version": run.prompt_version,
        "model": run.model_name,
        "status": run.status,
        "total_score": float(run.total_score or 0),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "metrics": metrics,
        "badcases": badcases,
    }


def render_html(db, run: EvalRun) -> str:
    report = build_report(db, run)
    score = report["total_score"]
    if score >= 80:
        badge, color = "可上线", "#0f9d58"
    elif score >= 70:
        badge, color = "有条件通过", "#f59e0b"
    else:
        badge, color = "不可上线", "#d92d20"
    return HTML_TEMPLATE.render(
        run=run, dataset_name=report["dataset"] or "-", score=score,
        total=report["total"], passed=report["passed"], failed=report["failed"],
        metrics=[{"label": METRIC_LABELS.get(k, k), "value": "%.4f" % v}
                 for k, v in report["metrics"].items()],
        badcases=report["badcases"][:20], badge=badge, badge_color=color,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))


def compare(db, run_a: EvalRun, run_b: EvalRun) -> dict:
    def as_report(run):
        return {"metrics": _metrics_of(db, run),
                "total_score": float(run.total_score or 0)}

    return compare_runs(as_report(run_a), as_report(run_b))
