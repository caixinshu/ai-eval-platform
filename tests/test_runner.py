"""执行引擎单元测试（并发/重试/缓存/断点续跑）"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.checkpoint import Checkpoint
from engine.runner import EvalRunner

CASES = [{"id": "c1", "question": "q1"}, {"id": "c2", "question": "q2"},
         {"id": "c3", "question": "q3"}]


def _tmpdir() -> str:
    return tempfile.mkdtemp(prefix="eval_engine_")


def test_concurrency_keeps_input_order():
    calls = []

    def qa(case):
        calls.append(case["id"])
        return {"answer": case["id"]}

    runner = EvalRunner(concurrency=3, cache_dir=_tmpdir())
    results = asyncio.run(runner.run(CASES, qa, "v1"))
    assert [r.case_id for r in results] == ["c1", "c2", "c3"]
    assert all(r.success for r in results)
    assert sorted(calls) == ["c1", "c2", "c3"]


def test_cache_hit_on_second_run():
    calls = []

    def qa(case):
        calls.append(case["id"])
        return {"answer": "a"}

    cache = _tmpdir()
    runner = EvalRunner(concurrency=2, cache_dir=cache)
    asyncio.run(runner.run(CASES, qa, "v1"))
    assert len(calls) == 3

    asyncio.run(runner.run(CASES, qa, "v1"))
    assert len(calls) == 3, "第二次应该全部命中缓存，不再调用被测应用"
    summary = EvalRunner.summarize(asyncio.run(runner.run(CASES, qa, "v1")))
    assert summary["cached"] == 3


def test_version_change_invalidates_cache():
    calls = []

    def qa(case):
        calls.append(case["id"])
        return {"answer": "a"}

    runner = EvalRunner(concurrency=2, cache_dir=_tmpdir())
    asyncio.run(runner.run(CASES, qa, "v1"))
    asyncio.run(runner.run(CASES, qa, "v2"))
    assert len(calls) == 6, "Prompt 版本变化应使缓存失效"


def test_retry_then_success():
    attempts = {"n": 0}

    def flaky(case):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 rate limited")
        return {"answer": "ok"}

    runner = EvalRunner(concurrency=1, max_retries=3,
                        cache_dir=_tmpdir(), backoff_base=0.01)
    results = asyncio.run(runner.run([CASES[0]], flaky, "v1"))
    assert results[0].success is True
    assert attempts["n"] == 3


def test_retry_exhausted_records_error():
    def always_fail(case):
        raise ValueError("boom")

    runner = EvalRunner(concurrency=1, max_retries=2,
                        cache_dir=_tmpdir(), backoff_base=0.01)
    results = asyncio.run(runner.run([CASES[0]], always_fail, "v1"))
    assert results[0].success is False
    assert "boom" in results[0].error


def test_one_failure_does_not_block_others():
    def half_fail(case):
        if case["id"] == "c2":
            raise RuntimeError("bad")
        return {"answer": "ok"}

    runner = EvalRunner(concurrency=2, max_retries=1,
                        cache_dir=_tmpdir(), backoff_base=0.01)
    results = asyncio.run(runner.run(CASES, half_fail, "v1"))
    summary = EvalRunner.summarize(results)
    assert summary["success"] == 2
    assert summary["failed_ids"] == ["c2"]


def test_checkpoint_resume_skips_done():
    workdir = _tmpdir()
    ckpt = Checkpoint("run1", path=os.path.join(workdir, "ckpt"))
    ckpt.mark_done("c1")

    calls = []

    def qa(case):
        calls.append(case["id"])
        return {"answer": "a"}

    runner = EvalRunner(concurrency=2, cache_dir=os.path.join(workdir, "cache"))
    results = asyncio.run(runner.run(CASES, qa, "v1", checkpoint=ckpt))
    assert calls == ["c2", "c3"], "已完成的 c1 不应重复调用"
    assert results[0].skipped is True
    assert EvalRunner.summarize(results)["skipped"] == 1
    assert ckpt.count == 3

    shutil.rmtree(workdir, ignore_errors=True)
