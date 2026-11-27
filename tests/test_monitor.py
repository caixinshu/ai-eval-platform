"""线上监控、反馈归类、badcase 回流测试（Day 24）"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor.badcase_reflow import (load_cases, merge_into_file, reflow_cases,
                                     save_cases, stats, verify_case)
from monitor.feedback_collector import BadcaseCollector
from monitor.online_sampler import OnlineSampler
from scripts.run_eval import load_cases as load_eval_cases


def test_sampler_is_stable_and_respects_rate():
    sampler = OnlineSampler(sample_rate=0.5, max_per_hour=1000)
    request_id = next(
        "req-%d" % i for i in range(100)
        if OnlineSampler(sample_rate=0.5).should_sample("req-%d" % i, "h1"))
    first = sampler.should_sample(request_id, "h1")
    for _ in range(5):
        assert sampler.should_sample(request_id, "h1") == first


def test_sampler_boundaries_and_hour_limit():
    assert OnlineSampler(1.0, 10).should_sample("r1", "h1") is True
    assert OnlineSampler(0.0, 10).should_sample("r1", "h1") is False
    assert OnlineSampler(1.0, 10).should_sample("", "h1") is False

    sampler = OnlineSampler(sample_rate=1.0, max_per_hour=2)
    assert sampler.should_sample("r1", "h1") is True
    assert sampler.should_sample("r2", "h1") is True
    assert sampler.should_sample("r3", "h1") is False
    # 跨小时重新计数
    assert sampler.should_sample("r3", "h2") is True


def test_sampler_rejects_invalid_config():
    for rate in (-0.1, 1.5):
        try:
            OnlineSampler(sample_rate=rate)
        except ValueError:
            continue
        raise AssertionError("rate=%s 应该报错")


def test_collector_classifies_five_categories():
    collector = BadcaseCollector()
    cases = {
        "回答编造了不存在的政策": "hallucination",
        "答非所问，完全没回答": "irrelevant",
        "信息不完整，漏了退款条件": "incomplete",
        "格式乱了看不懂": "format",
        "语气太生硬": "tone",
        "其他不满意": "other",
    }
    for comment, expected in cases.items():
        assert collector.classify(comment) == expected
    # 用户选的原因也要参与归类
    assert collector.classify("", "编造") == "hallucination"


def test_collector_maps_rows():
    rows = [{
        "id": "fb1", "request_id": "r1", "question": "q", "answer": "a",
        "rating": "bad", "reason": "不相关", "comment": "",
        "issue_category": None, "biz_line": "退款", "created_at": None,
    }]
    item = BadcaseCollector().collect_from_rows(rows)[0]
    assert item["category"] == "irrelevant"
    assert item["biz_line"] == "退款"


def test_reflow_dedupes_and_requires_frequency(tmp_path):
    badcases = [
        {"request_id": "r1", "question": "退款多久到账？", "category": "incomplete",
         "reason": "不完整"},
        {"request_id": "r2", "question": "退款多久到账?", "category": "incomplete",
         "reason": "不完整"},
        {"request_id": "r3", "question": "退款多久到账", "category": "incomplete",
         "reason": "不完整"},
        {"request_id": "r4", "question": "只出现一次的问题", "category": "other",
         "reason": ""},
    ]
    cases = reflow_cases(badcases, min_count=3,
                         now=datetime(2026, 11, 27, 10, 0, 0))
    assert len(cases) == 1
    case = cases[0]
    assert case["id"].startswith("fresh_")
    assert case["verified"] is False
    assert case["ground_truth"] is None
    assert case["source"] == "online_badcase"
    assert case["created_at"] == "2026-11-27"


def test_reflow_skips_existing_questions():
    existing = [{"id": "old", "question": "退款多久到账？"}]
    badcases = [{"question": "退款多久到账", "category": "other"}] * 3
    assert reflow_cases(badcases, existing, min_count=1) == []


def test_merge_verify_and_stats(tmp_path):
    path = str(tmp_path / "fresh_set.json")
    badcases = [{"request_id": "r1", "question": "退款多久到账", "category": "incomplete"}]
    new_cases = reflow_cases(badcases, min_count=1)
    added = merge_into_file(path, new_cases)
    assert len(added) == 1
    # 再合并同一问题不会重复
    assert merge_into_file(path, new_cases) == []

    before = stats(load_cases(path))
    assert before["total"] == 1 and before["pending"] == 1

    case_id = added[0]["id"]
    verified = verify_case(path, case_id, "7 天内原路退回", now=datetime(2026, 11, 27, 12, 0, 0))
    assert verified["verified"] is True
    assert verified["ground_truth"] == "7 天内原路退回"
    assert verified["verified_at"] == "2026-11-27T12:00:00"

    after = stats(load_cases(path))
    assert after["verified"] == 1 and after["pending"] == 0
    assert after["by_category"]["incomplete"]["verified"] == 1


def test_verify_requires_ground_truth_and_existing_case(tmp_path):
    path = str(tmp_path / "fresh_set.json")
    save_cases(path, [{"id": "fresh_x", "question": "q", "verified": False}])
    try:
        verify_case(path, "fresh_x", "  ")
    except ValueError as exc:
        assert "ground_truth" in str(exc)
    else:
        raise AssertionError("空标准答案应该报错")

    try:
        verify_case(path, "missing", "答案")
    except KeyError:
        pass
    else:
        raise AssertionError("不存在的用例应该报错")


def test_run_eval_skips_unverified_reflow_cases(tmp_path):
    path = tmp_path / "fresh_set.json"
    path.write_text(json.dumps([
        {"id": "f1", "question": "q1", "verified": False},
        {"id": "f2", "question": "q2", "verified": True},
        {"id": "f3", "question": "q3"},
    ], ensure_ascii=False), encoding="utf-8")

    cases = load_eval_cases(str(path))
    assert [case["id"] for case in cases] == ["f2", "f3"]


@pytest.fixture()
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import database
    from backend.models import dataset, feedback, prompt, run  # noqa: F401

    engine = create_engine("sqlite:///" + str(tmp_path / "monitor.db"),
                           connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    database.Base.metadata.create_all(engine)

    from backend.services import monitor_service

    monkeypatch.setattr(monitor_service, "FRESH_SET_PATH",
                        str(tmp_path / "fresh_set.json"))

    from backend.main import app

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_db
    client = TestClient(app)
    yield client, TestingSession
    app.dependency_overrides.clear()


def test_feedback_api_and_auto_category(api):
    client, _ = api
    bad = client.post("/api/feedback", json={
        "request_id": "req-1", "question": "退款多久到账",
        "answer": "不知道", "rating": "bad",
        "comment": "回答是编造的，没有依据",
    })
    assert bad.status_code == 201
    assert bad.json()["issue_category"] == "hallucination"

    good = client.post("/api/feedback", json={
        "request_id": "req-2", "question": "怎么退款",
        "answer": "7 天原路退回", "rating": "good",
    })
    assert good.status_code == 201
    assert good.json()["issue_category"] is None

    overview = client.get("/api/monitor/overview").json()
    assert overview["quality"]["feedback_count_24h"] == 2
    assert overview["quality"]["bad_rate_24h"] == 0.5
    assert overview["issues"]["total"] == 1
    assert overview["issues"]["items"][0]["category"] == "hallucination"


def test_sample_api_and_dashboard_aggregation(api):
    client, _ = api
    for score in (90, 70):
        resp = client.post("/api/monitor/samples", json={
            "request_id": "req-%s" % score, "question": "q",
            "answer": "a", "score": score, "biz_line": "退款",
            "latency_ms": 120,
        })
        assert resp.status_code == 201

    overview = client.get("/api/monitor/overview?days=30").json()
    assert overview["quality"]["sample_count_24h"] == 2
    assert overview["quality"]["avg_score_24h"] == 80.0
    assert overview["categories"][0]["biz_line"] == "退款"
    assert overview["categories"][0]["avg_score"] == 80.0
    assert len(overview["trend"]) == 30
    assert len(overview["hourly"]) == 24
    assert overview["reflow"]["total"] == 0


def test_feedback_and_sample_validation(api):
    client, _ = api
    assert client.post("/api/feedback", json={
        "request_id": "r", "question": "q", "rating": "meh"}).status_code == 422
    assert client.post("/api/monitor/samples", json={
        "request_id": "r", "question": "q", "score": 120}).status_code == 422


def test_empty_overview_returns_zero_values(api):
    client, _ = api
    data = client.get("/api/monitor/overview").json()
    assert data["quality"]["avg_score_24h"] is None
    assert data["quality"]["bad_rate_24h"] is None
    assert data["issues"]["items"] == []
    assert data["categories"] == []
    assert data["reflow"]["pending"] == 0
