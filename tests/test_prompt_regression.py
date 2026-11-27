"""Prompt 回归、灰度路由与回滚测试（Day 23）"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.prompt_diff import (diff_results, normalize_case,
                                  normalize_cases, render_markdown, risk_note,
                                  score_from_metrics, summarize_categories)
from app.ab_router import PromptRouter
from app.gray_guard import GrayReleaseGuard
from scripts.prompt_diff import main as diff_main


def _cases(*rows):
    return [
        {"case_id": case_id, "question": "问题%s" % case_id,
         "category": category, "total_score": score}
        for case_id, category, score in rows
    ]


def test_diff_buckets_and_summary():
    baseline = _cases(("c1", "退款", 100), ("c2", "物流", 80),
                      ("c3", "退款", 60), ("c4", "物流", 50))
    current = _cases(("c1", "退款", 100), ("c2", "物流", 90),
                     ("c3", "退款", 50), ("c4", "物流", 52))
    diff = diff_results(current, baseline)

    assert [i["case_id"] for i in diff["improved"]] == ["c2"]
    assert [i["case_id"] for i in diff["degraded"]] == ["c3"]
    assert diff["unchanged_count"] == 2
    assert diff["summary"] == {
        "improved_count": 1, "degraded_count": 1, "net_change": 0}


def test_diff_threshold_boundary():
    baseline = _cases(("c1", "x", 80), ("c2", "x", 80))
    current = _cases(("c1", "x", 85), ("c2", "x", 75))
    diff = diff_results(current, baseline, threshold=0.05)
    # 正好 ±5 分都算显著变化
    assert diff["summary"]["improved_count"] == 1
    assert diff["summary"]["degraded_count"] == 1
    assert diff["unchanged_count"] == 0


def test_normalize_case_from_metrics():
    case = normalize_case({
        "case_id": "c1", "question": "q",
        "metrics": {"rule_score": 0.8, "correctness": 0.6, "f1": 0.0},
    })
    assert case["total_score"] == 70.0       # 只取白名单指标 (0.8+0.6)/2
    assert case["category"] == "unknown"


def test_normalize_report_shapes():
    rows = [{"case_id": "c1", "total_score": 80, "category": "退款"}]
    assert normalize_cases({"case_results": rows})[0]["total_score"] == 80.0
    assert normalize_cases({"items": rows})[0]["case_id"] == "c1"
    assert normalize_cases(rows)[0]["category"] == "退款"


def test_score_from_empty_metrics():
    assert score_from_metrics({}) == 0.0
    assert score_from_metrics({"f1": 0.9}) == 0.0


def test_category_summary_and_risk_note():
    baseline = _cases(("c1", "退款", 90), ("c2", "退款", 90),
                      ("c3", "退款", 90), ("c4", "物流", 80))
    current = _cases(("c1", "退款", 70), ("c2", "退款", 70),
                     ("c3", "退款", 70), ("c4", "物流", 90))
    diff = diff_results(current, baseline)
    stats = summarize_categories(diff)

    assert stats["退款"]["degraded"] == 3
    assert stats["退款"]["avg_delta"] == -20.0
    # 净变化为负，但退化集中在退款，必须点出来
    assert "退款" in risk_note(diff, stats) or "均值" in risk_note(diff, stats)


def test_markdown_contains_actionable_details():
    baseline = _cases(("c1", "退款", 90), ("c2", "物流", 80))
    current = _cases(("c1", "退款", 70), ("c2", "物流", 82))
    diff = diff_results(current, baseline)
    markdown = render_markdown(diff, "v1.3.0", "v1.2.0")

    assert "Prompt 版本差异分析" in markdown
    assert "`v1.3.0`" in markdown and "`v1.2.0`" in markdown
    assert "退化用例" in markdown and "c1" in markdown
    assert "分类归因" in markdown


def test_prompt_diff_cli(tmp_path):
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(json.dumps(_cases(("c1", "退款", 90))), encoding="utf-8")
    current.write_text(json.dumps(_cases(("c1", "退款", 70))), encoding="utf-8")

    code = diff_main([
        str(baseline), str(current),
        "--json", str(tmp_path / "diff.json"),
        "--markdown", str(tmp_path / "diff.md"),
    ])
    assert code == 0
    payload = json.loads((tmp_path / "diff.json").read_text(encoding="utf-8"))
    assert payload["summary"]["degraded_count"] == 1
    assert "c1" in (tmp_path / "diff.md").read_text(encoding="utf-8")


def test_router_is_stable_per_user():
    router = PromptRouter("v1.3.0", ratio=0.05)
    first = router.pick_version("user-42", "v1.2.0")
    assert first == router.pick_version("user-42", "v1.2.0")
    assert first in ("v1.2.0", "v1.3.0")


def test_router_ratio_boundaries():
    assert PromptRouter("new", ratio=0).pick_version("u1", "old") == "old"
    assert PromptRouter("new", ratio=1).pick_version("u1", "old") == "new"
    assert PromptRouter("new").pick_version("", "old") == "old"


def test_router_distribution_near_ratio():
    router = PromptRouter("new", ratio=0.05)
    hits = sum(1 for i in range(10000)
               if router.pick_version("user-%d" % i, "old") == "new")
    assert 350 <= hits <= 650


def test_router_rejects_invalid_ratio():
    for ratio in (-0.1, 1.1):
        try:
            PromptRouter("new", ratio=ratio)
        except ValueError:
            continue
        raise AssertionError("ratio=%s 应该报错" % ratio)


def _snapshot(**overrides):
    data = {
        "online_score": 0.85,
        "negative_feedback_rate": 0.10,
        "refusal_rate": 0.10,
        "latency_p95_ms": 1200,
        "token_cost": 100.0,
    }
    data.update(overrides)
    return data


def test_guard_passes_when_metrics_normal():
    result = GrayReleaseGuard().evaluate(_snapshot(), _snapshot(
        online_score=0.84, negative_feedback_rate=0.11,
        refusal_rate=0.11, latency_p95_ms=1500, token_cost=110.0))
    assert result["rollback"] is False
    assert result["reasons"] == []
    assert len(result["checks"]) == 5


def test_guard_rolls_back_on_score_drop():
    result = GrayReleaseGuard().evaluate(_snapshot(), _snapshot(online_score=0.80))
    assert result["rollback"] is True
    assert any("在线评测分数" in reason for reason in result["reasons"])


def test_guard_rolls_back_on_negative_feedback():
    result = GrayReleaseGuard().evaluate(
        _snapshot(negative_feedback_rate=0.10),
        _snapshot(negative_feedback_rate=0.14))       # +40% > 30%
    assert result["rollback"] is True
    assert any("负反馈" in reason for reason in result["reasons"])


def test_guard_rolls_back_on_refusal_rate():
    result = GrayReleaseGuard().evaluate(
        _snapshot(refusal_rate=0.10), _snapshot(refusal_rate=0.13))  # +30% > 20%
    assert result["rollback"] is True
    assert any("拒答率" in reason for reason in result["reasons"])


def test_guard_rolls_back_on_latency_and_cost():
    result = GrayReleaseGuard().evaluate(
        _snapshot(), _snapshot(latency_p95_ms=3500, token_cost=140.0))
    assert result["rollback"] is True
    assert any("延迟 P95" in reason for reason in result["reasons"])
    assert any("Token 成本" in reason for reason in result["reasons"])


def test_guard_zero_baseline_rate():
    result = GrayReleaseGuard().evaluate(
        _snapshot(negative_feedback_rate=0.0),
        _snapshot(negative_feedback_rate=0.01))
    assert result["rollback"] is True
    zero = GrayReleaseGuard().evaluate(
        _snapshot(negative_feedback_rate=0.0),
        _snapshot(negative_feedback_rate=0.0))
    assert zero["rollback"] is False


def test_guard_validates_snapshot():
    try:
        GrayReleaseGuard().evaluate({"online_score": 0.9}, _snapshot())
    except ValueError as exc:
        assert "缺少指标" in str(exc)
    else:
        raise AssertionError("缺少指标应该报错")

    try:
        GrayReleaseGuard().evaluate(_snapshot(online_score=85), _snapshot())
    except ValueError as exc:
        assert "[0, 1]" in str(exc)
    else:
        raise AssertionError("越界分数应该报错")
