"""质量门禁与评测入口测试（Day 22）"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.derive_thresholds import derive
from scripts.quality_gate import (build_comment, check_gate, main,
                                  normalize_metrics)
from scripts.run_eval import build_report


def _report(**overrides):
    metrics = {
        "safety": 1.0,
        "faithfulness": 0.90,
        "correctness": 0.86,
        "answer_relevance": 0.88,
        "context_precision": 0.80,
        "performance": 0.92,
    }
    metrics.update(overrides)
    return {"total_score": 88.0, "prompt_version": "v1.2.0", "metrics": metrics}


def test_gate_pass_without_baseline():
    passed, failures = check_gate(_report())
    assert passed is True
    assert failures == []


def test_gate_absolute_threshold_failure():
    passed, failures = check_gate(_report(faithfulness=0.80))
    assert passed is False
    assert "faithfulness" in failures[0]


def test_gate_safety_veto_short_circuits():
    passed, failures = check_gate(_report(safety=0.0, faithfulness=0.1))
    assert passed is False
    # 一票否决立即返回，不再罗列后续指标
    assert len(failures) == 1 and "safety" in failures[0]


def test_gate_relative_baseline_drop():
    baseline = _report(context_precision=0.90)
    passed, failures = check_gate(_report(context_precision=0.80), baseline)
    assert passed is False
    assert any("context_precision" in item and "下降" in item for item in failures)


def test_gate_missing_metric_fails():
    report = _report()
    del report["metrics"]["performance"]
    passed, failures = check_gate(report)
    assert passed is False
    assert any("performance" in item and "缺失" in item for item in failures)


def test_metric_alias_and_performance_derivation():
    metrics = normalize_metrics({
        "metrics": {"safety": 1.0, "answer_relevancy": 0.9},
        "avg_latency_ms": 600,
    })
    assert metrics["relevance"] == 0.9
    assert "answer_relevancy" not in metrics
    assert metrics["performance"] == 0.8          # 1 - 600 / 3000


def test_percent_scale_report():
    metrics = normalize_metrics({
        "metric_scale": "percent",
        "metrics": {"safety": 100, "faithfulness": 90, "performance": 80},
    })
    assert metrics == {"safety": 1.0, "faithfulness": 0.9, "performance": 0.8}


def test_comment_contains_actionable_details():
    baseline = _report(faithfulness=0.95)
    passed, failures = check_gate(_report(faithfulness=0.80), baseline)
    comment = build_comment(_report(faithfulness=0.80), passed, failures, baseline)
    assert "AI 质量门禁未通过" in comment
    assert "当前值" in comment and "硬阈值" in comment
    assert "0.800" in comment
    assert "失败详情" in comment


def test_cli_exit_codes_and_comment_file(tmp_path):
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    comment = tmp_path / "comment.md"
    good.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    bad.write_text(json.dumps(_report(safety=0.5), ensure_ascii=False),
                   encoding="utf-8")

    assert main([str(good)]) == 0
    assert main([str(bad), "--comment", str(comment)]) == 1
    assert "AI 质量门禁未通过" in comment.read_text(encoding="utf-8")


def test_run_eval_golden_report_shape(monkeypatch):
    # 单元测试不打真实网络：check_correctness 默认会加载/下载 embedding 模型
    import evaluation.rule_eval as rule_eval

    monkeypatch.setattr(rule_eval, "check_correctness",
                        lambda answer, ground_truth: 1.0)

    cases = [{
        "id": "g001",
        "question": "退款政策是什么",
        "ground_truth": "支持7天无理由退款",
    }]
    precomputed = [{
        "question": "退款政策是什么",
        "answer": "支持7天无理由退款，请放心购买并保留凭证。",
        "contexts": ["支持7天无理由退款，商品不影响二次销售。"],
        "ground_truth": "支持7天无理由退款",
        "error": None,
        "duration_ms": 150.0,
    }]
    report = build_report(cases, precomputed, "golden", "v1.2.0")
    assert report["case_count"] == 1
    assert report["metrics"]["performance"] == round(1 - 150 / 3000, 4)
    assert {"faithfulness", "answer_relevance", "context_precision",
            "correctness", "safety"} <= set(report["metrics"])
    assert 0 <= report["total_score"] <= 100
    assert len(report["case_results"]) == 1
    assert report["case_results"][0]["case_id"] == "g001"
    assert 0 <= report["case_results"][0]["total_score"] <= 100


def test_run_eval_assertion_report():
    cases = [{
        "id": "a001",
        "question": "能退款吗",
        "category": "退款",
        "assertion": "must_contain_any",
        "assertion_value": ["退款"],
    }]
    precomputed = [{
        "question": "能退款吗",
        "answer": "支持7天无理由退款，请保留凭证。",
        "contexts": [],
        "ground_truth": "",
        "error": None,
        "duration_ms": 120.0,
    }]
    report = build_report(cases, precomputed, "adversarial", "v1",
                          use_semantic=False)
    assert report["metrics"]["assertion_pass_rate"] == 1.0
    assert report["metrics"]["correctness"] == 1.0
    assert report["assertion"]["passed"] == 1
    assert report["total_score"] == 100.0
    assert report["case_results"][0]["total_score"] == 100.0


def test_derive_thresholds_from_history(tmp_path):
    paths = []
    for index, value in enumerate((0.86, 0.88, 0.90)):
        path = tmp_path / ("run_%d.json" % index)
        path.write_text(json.dumps(_report(faithfulness=value)),
                        encoding="utf-8")
        paths.append(str(path))

    result = derive(paths)
    info = result["metrics"]["faithfulness"]
    assert info["samples"] == 3
    assert info["suggested_min"] is not None
    assert info["unstable"] is False
    assert result["metrics"]["safety"]["suggested_min"] == 1.0


def test_derive_flags_unstable_metric(tmp_path):
    paths = []
    for index, value in enumerate((0.95, 0.60, 0.25)):
        path = tmp_path / ("perf_%d.json" % index)
        path.write_text(json.dumps(_report(performance=value)),
                        encoding="utf-8")
        paths.append(str(path))

    info = derive(paths)["metrics"]["performance"]
    assert info["unstable"] is True
    assert "波动" in info["note"]
