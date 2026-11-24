"""后端 API 集成测试（临时 SQLite，不依赖 PostgreSQL 与真实模型）"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import database
    from backend.models import dataset, prompt, run  # noqa: F401  注册表

    engine = create_engine("sqlite:///" + str(tmp_path / "test.db"),
                           connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False)
    database.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSession)

    from backend.main import app

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = override_db
    client = TestClient(app)          # 不用 with，避免触发 startup 建生产库
    yield client, TestingSession
    app.dependency_overrides.clear()


def _create_dataset(client, name="黄金集"):
    return client.post("/api/datasets", json={
        "name": name, "type": "golden", "description": "测试用"}).json()


def _upload(client, dataset_id, cases):
    payload = json.dumps(cases, ensure_ascii=False).encode("utf-8")
    return client.post("/api/datasets/upload?dataset_id=" + dataset_id,
                       files={"file": ("cases.json", payload, "application/json")})


def test_health(api):
    client, _ = api
    assert client.get("/api/health").json()["status"] == "ok"


def test_dataset_create_and_list(api):
    client, _ = api
    created = _create_dataset(client)
    assert created["case_count"] == 0
    listing = client.get("/api/datasets?type=golden").json()
    assert listing["total"] == 1
    assert listing["items"][0]["name"] == "黄金集"


def test_dataset_duplicate_conflict(api):
    client, _ = api
    _create_dataset(client)
    resp = client.post("/api/datasets", json={"name": "黄金集", "type": "golden"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "VERSION_CONFLICT"


def test_upload_and_list_cases(api):
    client, _ = api
    ds = _create_dataset(client)
    resp = _upload(client, ds["id"], [
        {"id": "g001", "question": "退款政策是什么", "category": "退款"},
        {"id": "g002", "question": "多久到账", "category": "退款"},
        {"id": "g001", "question": "重复 ID"},
    ])
    assert resp.status_code == 200
    assert resp.json() == {"dataset_id": ds["id"], "imported": 2,
                           "skipped": 1, "case_count": 2}
    cases = client.get("/api/datasets/%s/cases?category=退款" % ds["id"]).json()
    assert cases["total"] == 2


def test_upload_invalid_json(api):
    client, _ = api
    ds = _create_dataset(client)
    resp = client.post("/api/datasets/upload?dataset_id=" + ds["id"],
                       files={"file": ("bad.json", b"not json", "application/json")})
    assert resp.status_code == 422
    assert resp.json()["code"] == "DATASET_INVALID"


def test_prompt_create_and_conflict(api):
    client, _ = api
    body = {"name": "客服问答", "version": "v1.2.0", "content": "你是客服助手"}
    assert client.post("/api/prompts", json=body).status_code == 201
    assert client.post("/api/prompts", json=body).status_code == 409
    assert client.get("/api/prompts").json()["total"] == 1


def test_run_create_dataset_not_found(api):
    client, _ = api
    resp = client.post("/api/runs", json={"dataset_id": "ds_missing",
                                          "prompt_version": "v1"})
    assert resp.status_code == 404


def test_run_conflict_when_running(api):
    client, Session = api
    ds = _create_dataset(client)
    db = Session()
    from backend.models.run import EvalRun
    db.add(EvalRun(id="run_pending", dataset_id=ds["id"], prompt_version="v1",
                   status="pending", progress=0))
    db.commit()
    db.close()

    resp = client.post("/api/runs", json={"dataset_id": ds["id"], "prompt_version": "v1"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "RUNNING_CONFLICT"


def test_run_end_to_end(api, monkeypatch):
    client, _ = api
    from backend.services import eval_service

    monkeypatch.setattr(eval_service, "ask_question",
                        lambda case: {"answer": "支持7天无理由退款，请放心购买。",
                                      "contexts": ["退款政策"]})
    ds = _create_dataset(client)
    _upload(client, ds["id"], [{"id": "g001", "question": "退款政策是什么"},
                               {"id": "g002", "question": "多久到账"}])

    created = client.post("/api/runs", json={"dataset_id": ds["id"],
                                             "prompt_version": "v1"}).json()
    assert created["total_cases"] == 2

    status = client.get("/api/runs/%s/status" % created["run_id"]).json()
    assert status["status"] == "done"
    assert status["progress"] == 100
    assert status["processed"] == 2

    results = client.get("/api/runs/%s/results" % created["run_id"]).json()
    assert results["total"] == 2

    report = client.get("/api/runs/%s/report" % created["run_id"]).json()
    assert report["total"] == 2 and report["metrics"]["rule_score"] == 1.0

    html = client.get("/api/runs/%s/report?format=html" % created["run_id"])
    assert html.status_code == 200
    assert "评测报告" in html.text


def test_compare_two_runs(api, monkeypatch):
    client, _ = api
    from backend.services import eval_service

    answers = {"current": "支持7天无理由退款，请放心购买。"}

    def fake_ask(case):
        return {"answer": answers["current"], "contexts": []}

    monkeypatch.setattr(eval_service, "ask_question", fake_ask)
    ds = _create_dataset(client)
    _upload(client, ds["id"], [{"id": "g001", "question": "退款政策是什么"}])

    run_a = client.post("/api/runs", json={"dataset_id": ds["id"],
                                           "prompt_version": "v1"}).json()["run_id"]
    answers["current"] = ""      # 第二次评测：空回答
    run_b = client.post("/api/runs", json={"dataset_id": ds["id"],
                                           "prompt_version": "v2"}).json()["run_id"]

    diff = client.post("/api/runs/compare", json={"run_id_a": run_b,
                                                  "run_id_b": run_a}).json()
    assert diff["total"]["improved"] is False
    assert "rule_score" in diff["regressions"]


# ---------------- Day 17：异步任务调度 ----------------

def _insert_run(Session, run_id, dataset_id, **kwargs):
    from backend.models.run import EvalRun

    fields = {"status": "pending", "progress": 0}
    fields.update(kwargs)
    db = Session()
    db.add(EvalRun(id=run_id, dataset_id=dataset_id, prompt_version="v1",
                   **fields))
    db.commit()
    db.close()


def test_single_case_failure_isolated(api, monkeypatch):
    """单条应用异常不影响整批：任务仍 done，其他用例正常出分"""
    client, _ = api
    from backend.services import eval_service

    def fake_ask(case):
        if case["question"] == "坏问题":
            raise RuntimeError("模型超时")
        return {"answer": "支持7天无理由退款，请放心购买。", "contexts": []}

    monkeypatch.setattr(eval_service, "ask_question", fake_ask)
    ds = _create_dataset(client)
    _upload(client, ds["id"], [{"id": "g001", "question": "退款政策是什么"},
                               {"id": "g002", "question": "坏问题"}])

    created = client.post("/api/runs", json={"dataset_id": ds["id"],
                                             "prompt_version": "v1"}).json()
    status = client.get("/api/runs/%s/status" % created["run_id"]).json()
    assert status["status"] == "done"
    assert status["failed"] == 1

    results = client.get("/api/runs/%s/results" % created["run_id"]).json()
    answers = {item["case_id"]: item["answer"] for item in results["items"]}
    assert answers["g002"].startswith("[应用异常]")
    assert answers["g001"].startswith("支持")


def test_run_cancel_marks_cancelled(api, monkeypatch):
    """预置取消标记后执行：一条都不调用，终态 cancelled"""
    client, Session = api
    from backend.services import eval_service

    ds = _create_dataset(client)
    _upload(client, ds["id"], [{"id": "g001", "question": "退款政策是什么"},
                               {"id": "g002", "question": "多久到账"}])
    _insert_run(Session, "run_cancel", ds["id"], cancel_requested=True,
                total_cases=2)

    from backend.models.run import EvalRun

    called = []
    monkeypatch.setattr(eval_service, "ask_question",
                        lambda case: called.append(case["id"]) or {"answer": "x"})
    asyncio.run(eval_service.execute_eval("run_cancel"))

    assert called == [], "取消后不应再调用被测应用"
    db = Session()
    run = db.get(EvalRun, "run_cancel")
    assert run.status == "cancelled"
    db.close()

    status = client.get("/api/runs/run_cancel/status").json()
    assert status["status"] == "cancelled"


def test_cancel_api(api):
    """取消接口：pending/running 可取消，已结束返回 400"""
    client, Session = api
    ds = _create_dataset(client)
    _insert_run(Session, "run_pending", ds["id"])

    from backend.models.run import EvalRun

    resp = client.post("/api/runs/run_pending/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancel_requested"] is True
    db = Session()
    assert db.get(EvalRun, "run_pending").cancel_requested is True
    db.close()

    _insert_run(Session, "run_done", ds["id"], status="done", progress=100)
    resp = client.post("/api/runs/run_done/cancel")
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_PARAM"


def test_run_timeout_marks_failed(api, monkeypatch):
    """整体超时（这里把阈值调成 0）→ failed，错误信息提示超时"""
    client, Session = api
    from backend.services import eval_service

    ds = _create_dataset(client)
    _upload(client, ds["id"], [{"id": "g001", "question": "退款政策是什么"}])
    _insert_run(Session, "run_timeout", ds["id"], total_cases=1)

    from backend.models.run import EvalRun

    monkeypatch.setattr(eval_service.config, "EVAL_TIMEOUT_SECONDS", 0)
    asyncio.run(eval_service.execute_eval(
        "run_timeout", qa_func=lambda case: {"answer": "x"}))

    db = Session()
    run = db.get(EvalRun, "run_timeout")
    assert run.status == "failed"
    assert "超时" in run.error_message
    assert run.finished_at is not None
    db.close()


def test_recover_stale_running_runs(api):
    """服务重启恢复：残留 running 任务统一置 failed，提示重跑"""
    client, Session = api
    from backend.services.eval_service import recover_stale_runs

    ds = _create_dataset(client)
    _insert_run(Session, "run_stale", ds["id"], status="running", progress=40)
    _insert_run(Session, "run_done_ok", ds["id"], status="done", progress=100)

    from backend.models.run import EvalRun

    assert recover_stale_runs() == 1

    db = Session()
    stale = db.get(EvalRun, "run_stale")
    assert stale.status == "failed"
    assert "重启" in stale.error_message
    assert db.get(EvalRun, "run_done_ok").status == "done"
    db.close()


# ---------------- Day 18：前端页面 ----------------

def test_frontend_pages_served(api):
    """静态页由后端统一托管：首页看板、页面、样式与脚本都可访问"""
    client, _ = api
    index = client.get("/")
    assert index.status_code == 200
    assert "质量概览" in index.text
    assert "/vendor/echarts.min.js" in index.text

    for path, text in (("/pages/datasets.html", "数据集管理"),
                       ("/pages/new-run.html", "发起评测"),
                       ("/pages/tasks.html", "任务列表"),
                       ("/pages/run-detail.html", "评测结果")):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert text in resp.text

    assert client.get("/assets/app.css").status_code == 200
    js = client.get("/assets/api.js")
    assert js.status_code == 200
    # Windows 注册表可能把 .js 映射成 text/plain，浏览器会拒绝执行 ES module
    assert "javascript" in js.headers["content-type"]
    assert client.get("/poll.js").status_code == 200
    assert client.get("/vendor/echarts.min.js").status_code == 200
    assert client.get("/charts/radar.js").status_code == 200


def test_results_include_ground_truth(api, monkeypatch):
    """结果列表补齐标准答案，供 badcase 展开对照"""
    client, _ = api
    from backend.services import eval_service

    monkeypatch.setattr(eval_service, "ask_question",
                        lambda case: {"answer": "支持7天无理由退款"})
    monkeypatch.setattr(eval_service, "_semantic_score", lambda answer, truth: 1.0)

    ds = _create_dataset(client)
    _upload(client, ds["id"], [{
        "id": "g001", "question": "退款政策是什么",
        "ground_truth": "支持7天无理由退款",
    }])
    run_id = client.post("/api/runs", json={"dataset_id": ds["id"],
                                            "prompt_version": "v1"}).json()["run_id"]

    results = client.get("/api/runs/%s/results" % run_id).json()
    assert results["items"][0]["ground_truth"] == "支持7天无理由退款"


# ---------------- Day 19：质量概览看板 ----------------

def _dashboard_dataset(client):
    ds = _create_dataset(client, name="看板集")
    _upload(client, ds["id"], [
        {"id": "c001", "question": "退款政策是什么", "category": "退款",
         "ground_truth": "支持7天无理由退款"},
        {"id": "c002", "question": "多久到账", "category": "物流",
         "ground_truth": "1-3个工作日到账",
         "expected_behavior": {"must_contain": ["到账"]}},
    ])
    return ds


def test_dashboard_aggregates_latest_run(api, monkeypatch):
    """看板聚合：最近评测、雷达缺失值、趋势顺序、分类短板、基线对比"""
    client, _ = api
    from backend.services import eval_service

    monkeypatch.setattr(eval_service, "_semantic_score", lambda answer, truth: 1.0)
    answer = {"current": "支持7天无理由退款，请放心购买并保留凭证。"}

    def fake_ask(case):
        return {"answer": answer["current"], "contexts": []}

    monkeypatch.setattr(eval_service, "ask_question", fake_ask)
    ds = _dashboard_dataset(client)

    run_v1 = client.post("/api/runs", json={"dataset_id": ds["id"],
                                            "prompt_version": "v1"}).json()["run_id"]
    data = client.get("/api/dashboard?dataset_id=" + ds["id"]).json()

    assert data["latest"]["run_id"] == run_v1
    assert data["latest"]["total"] == 2
    assert data["latest"]["failed"] == 1
    assert data["badcase_count"] == 1
    assert len(data["trend"]) == 1
    assert data["compare"] is None
    # 分类按通过率升序，最差的排前面
    assert data["categories"][0]["category"] == "物流"
    assert data["categories"][0]["pass_rate"] == 0.0
    # 未采集的指标返回 null，不伪造 0
    assert "忠实度" in data["radar"]["missing"]
    assert "安全性" in data["radar"]["missing"]
    values = {item["key"]: item["value"] for item in data["radar"]["indicators"]}
    assert values["correctness"] == 1.0
    assert values["performance"] is not None

    answer["current"] = "支持7天无理由退款，1-3个工作日到账。"
    run_v2 = client.post("/api/runs", json={"dataset_id": ds["id"],
                                            "prompt_version": "v2"}).json()["run_id"]
    data = client.get("/api/dashboard?dataset_id=" + ds["id"]).json()

    assert data["latest"]["run_id"] == run_v2
    assert data["latest"]["total_score"] == 100.0
    assert [point["label"] for point in data["trend"]] == ["v1", "v2"]
    assert data["compare"]["baseline_version"] == "v1"
    assert data["compare"]["metrics"]["rule_score"]["baseline"] == 0.9


def test_dashboard_empty(api):
    """没有任何完成任务时返回空看板，而不是报错"""
    client, _ = api
    data = client.get("/api/dashboard").json()
    assert data["latest"] is None
    assert data["trend"] == []
    assert data["categories"] == []
    assert data["compare"] is None


# ---------------- Day 20-21：联调 ----------------

def test_long_run_progress_and_pagination(api, monkeypatch):
    """长任务：120 条用例跑完进度 100，分页不重复不遗漏"""
    client, _ = api
    from backend.services import eval_service

    monkeypatch.setattr(eval_service, "ask_question",
                        lambda case: {"answer": "支持7天无理由退款，请放心购买。"})
    ds = _create_dataset(client, name="长任务集")
    cases = [{"id": "L%03d" % i, "question": "退款问题 %d" % i}
             for i in range(1, 121)]
    assert _upload(client, ds["id"], cases).status_code == 200

    run_id = client.post("/api/runs", json={"dataset_id": ds["id"],
                                            "prompt_version": "v1"}).json()["run_id"]
    status = client.get("/api/runs/%s/status" % run_id).json()
    assert status["status"] == "done"
    assert status["progress"] == 100
    assert status["processed"] == 120

    collected = []
    for page in (1, 2, 3):
        data = client.get("/api/runs/%s/results?page=%d&page_size=50"
                          % (run_id, page)).json()
        assert data["total"] == 120
        collected.extend(item["case_id"] for item in data["items"])
    assert len(collected) == 120
    assert len(set(collected)) == 120


def test_concurrent_runs_do_not_interfere(api):
    """并发：两个任务同时执行，结果各自落库、互不串数据"""
    client, Session = api
    from backend.services import eval_service
    import time

    ds_a = _create_dataset(client, name="并发A")
    ds_b = _create_dataset(client, name="并发B")
    _upload(client, ds_a["id"], [{"id": "A%02d" % i, "question": "A 问题 %d" % i}
                                 for i in range(1, 7)])
    _upload(client, ds_b["id"], [{"id": "B%02d" % i, "question": "B 问题 %d" % i}
                                 for i in range(1, 7)])
    _insert_run(Session, "run_conc_a", ds_a["id"], total_cases=6)
    _insert_run(Session, "run_conc_b", ds_b["id"], total_cases=6)

    def make_ask(tag):
        def ask(case):
            time.sleep(0.005)      # 让两个任务真正交错执行
            return {"answer": "支持7天无理由退款，请放心购买。"}
        return ask

    async def run_both():
        await asyncio.gather(
            eval_service.execute_eval("run_conc_a", qa_func=make_ask("A")),
            eval_service.execute_eval("run_conc_b", qa_func=make_ask("B")),
        )

    asyncio.run(run_both())

    from backend.models.run import EvalResult, EvalRun

    db = Session()
    try:
        for run_id, prefix in (("run_conc_a", "A"), ("run_conc_b", "B")):
            run = db.get(EvalRun, run_id)
            assert run.status == "done"
            case_ids = [r.case_id for r in db.query(EvalResult).filter_by(
                run_id=run_id).all()]
            assert len(case_ids) == 6
            assert all(cid.startswith(prefix) for cid in case_ids)
    finally:
        db.close()
