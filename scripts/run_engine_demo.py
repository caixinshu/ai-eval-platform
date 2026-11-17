"""
执行引擎演示：串行 vs 并发耗时对比 + 缓存命中 + 断点续跑

用法:
    python scripts/run_engine_demo.py --limit 20 --concurrency 5
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from app.rag import ask
from engine.checkpoint import Checkpoint
from engine.runner import EvalRunner
from eval_datasets import load_golden

REPORT_PATH = Path("reports/engine_perf_v1.json")
BASE_CACHE = ".cache/eval_demo"


def qa(case: dict) -> dict:
    """被测应用适配：case -> 问答结果"""
    r = ask(case["question"])
    return {"answer": r["answer"], "contexts": r["contexts"]}


def fresh_dir(name: str) -> str:
    path = os.path.join(BASE_CACHE, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def run_once(cases, concurrency, cache_dir, checkpoint=None):
    runner = EvalRunner(concurrency=concurrency, cache_dir=cache_dir)
    start = time.time()
    results = asyncio.run(runner.run(cases, qa, "v1.2.0", checkpoint=checkpoint))
    return results, round(time.time() - start, 2)


def main() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    cases = load_golden()[:args.limit]
    print("用例数: %d | 并发数: %d" % (len(cases), args.concurrency))

    # 预热：模型加载 / 向量库连接 / 线程池初始化不计入计时（否则串行会被冷启动放大）
    qa(cases[0])
    print("预热完成")

    # 1. 串行（独立缓存目录，确保不命中）
    _, serial_time = run_once(cases, 1, fresh_dir("serial"))
    print("[串行] %.2fs" % serial_time)

    # 2. 并发（独立缓存目录）
    results, concurrent_time = run_once(cases, args.concurrency, fresh_dir("concurrent"))
    print("[并发 %d] %.2fs" % (args.concurrency, concurrent_time))
    summary = EvalRunner.summarize(results)
    print("  结果: 成功 %d, 失败 %d" % (summary["success"], summary["failed"]))

    # 3. 缓存命中（同一目录再跑一次）
    _, cached_time = run_once(cases, args.concurrency, os.path.join(BASE_CACHE, "concurrent"))
    print("[缓存命中] %.2fs" % cached_time)

    # 4. 断点续跑：标记前 5 条已完成，重新跑
    ckpt = Checkpoint("demo_run", path=fresh_dir("checkpoints"))
    for c in cases[:5]:
        ckpt.mark_done(c["id"])
    resume_results, resume_time = run_once(
        cases, args.concurrency, fresh_dir("resume"), checkpoint=ckpt)
    resume_summary = EvalRunner.summarize(resume_results)
    print("[断点续跑] %.2fs（跳过 %d 条）" % (resume_time, resume_summary["skipped"]))

    # 5. 模拟 IO 密集场景（LLM 调用 300ms）：本地 mock 生成太快，体现不出并发收益
    def slow_qa(case: dict) -> dict:
        time.sleep(0.3)
        return {"answer": "mock", "contexts": []}

    sim_runner_serial = EvalRunner(concurrency=1, cache_dir=fresh_dir("sim_serial"))
    start = time.time()
    asyncio.run(sim_runner_serial.run(cases, slow_qa, "sim"))
    sim_serial = round(time.time() - start, 2)

    sim_runner = EvalRunner(concurrency=args.concurrency, cache_dir=fresh_dir("sim_concurrent"))
    start = time.time()
    asyncio.run(sim_runner.run(cases, slow_qa, "sim"))
    sim_concurrent = round(time.time() - start, 2)
    print("[模拟 300ms IO] 串行 %.2fs -> 并发 %d 路 %.2fs" % (
        sim_serial, args.concurrency, sim_concurrent))

    speedup = round(serial_time / concurrent_time, 2) if concurrent_time else 0
    cache_speedup = round(serial_time / cached_time, 2) if cached_time else 0
    per_case = round(serial_time / len(cases), 3)
    report = {
        "run_at": datetime.now().isoformat(),
        "case_count": len(cases),
        "concurrency": args.concurrency,
        "serial_seconds": serial_time,
        "concurrent_seconds": concurrent_time,
        "cached_seconds": cached_time,
        "resume_seconds": resume_time,
        "speedup": speedup,
        "cache_speedup": cache_speedup,
        "per_case_seconds": per_case,
        "estimated_1000_serial_minutes": round(per_case * 1000 / 60, 1),
        "estimated_1000_concurrent_minutes": round(
            per_case * 1000 / args.concurrency / 60, 1),
        "run_summary": summary,
        "resume_summary": resume_summary,
        "simulated_io_serial_seconds": sim_serial,
        "simulated_io_concurrent_seconds": sim_concurrent,
        "simulated_io_speedup": round(sim_serial / sim_concurrent, 2) if sim_concurrent else 0,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n性能对比")
    print("  串行: %.2fs（单条 %.3fs）" % (serial_time, per_case))
    print("  并发: %.2fs（加速 %.2fx）" % (concurrent_time, speedup))
    print("  缓存: %.2fs（加速 %.2fx）" % (cached_time, cache_speedup))
    print("  断点: %.2fs（跳过 %d 条）" % (resume_time, resume_summary["skipped"]))
    print("  模拟 300ms IO: %.2fs -> %.2fs（加速 %.2fx）"
          % (sim_serial, sim_concurrent, report["simulated_io_speedup"]))
    print("  1000 条估算: 串行 %.1f 分钟 -> 并发 %.1f 分钟"
          % (report["estimated_1000_serial_minutes"],
             report["estimated_1000_concurrent_minutes"]))
    print("报告已保存: %s" % REPORT_PATH)
    return report


if __name__ == "__main__":
    main()
