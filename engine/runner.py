"""
评测执行引擎

四件套：
- 并发：asyncio.Semaphore 控制并发数（IO 密集型任务，并发 5-20 路）
- 重试：失败指数退避重试，单条失败不影响整批
- 缓存：响应内容 + Prompt 版本做 MD5 key，重复跑同一题直接命中
- 断点续跑：配合 Checkpoint，中断后跳已完成用例

用法：
    runner = EvalRunner(concurrency=5)
    results = asyncio.run(runner.run(cases, qa_func, "v1.2.0", checkpoint=ckpt))

长任务扩展（Day 17）：
- on_result：每完成一条（含命中缓存）回调一次，便于实时落库/上报进度
- should_stop：每个 worker 开始前检查一次，返回 True 则剩余用例标记 skipped（取消/超时）
"""
import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field


@dataclass
class TaskResult:
    case_id: str
    success: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0
    cached: bool = False
    skipped: bool = False


class EvalRunner:
    def __init__(self, concurrency: int = 5, max_retries: int = 3,
                 cache_dir: str = ".cache/eval", backoff_base: float = 1.0):
        self.concurrency = max(1, concurrency)
        self.max_retries = max(1, max_retries)
        self.cache_dir = cache_dir
        self.backoff_base = backoff_base
        os.makedirs(cache_dir, exist_ok=True)

    # ---- 缓存 ----
    def _cache_key(self, case: dict, version: str) -> str:
        raw = json.dumps({"q": case["question"], "v": version}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, key + ".json")

    def _get_cache(self, key: str):
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _set_cache(self, key: str, data: dict):
        tmp = self._cache_path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self._cache_path(key))

    # ---- 重试（指数退避）----
    async def _run_with_retry(self, func, case: dict) -> TaskResult:
        last_err = ""
        for attempt in range(self.max_retries):
            try:
                start = time.time()
                data = await asyncio.to_thread(func, case)
                return TaskResult(case["id"], True, data,
                                  duration=round(time.time() - start, 4))
            except Exception as e:
                last_err = "%s: %s" % (type(e).__name__, e)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
        return TaskResult(case["id"], False, error=last_err)

    # ---- 主流程 ----
    async def run(self, cases: list, qa_func, prompt_version: str,
                  checkpoint=None, on_result=None, should_stop=None,
                  use_cache: bool = True) -> list:
        """执行整批用例

        on_result: 可选异步回调，参数为 TaskResult，每完成一条调用一次
        should_stop: 可选同步判断函数，每处理一条前检查，True 则剩余用例跳过
        use_cache: 为 False 时不读不写缓存（评测服务避免跨轮次复用旧回答）
        """
        sem = asyncio.Semaphore(self.concurrency)
        # 预分配保证结果顺序与输入一致
        results = [None] * len(cases)

        async def worker(idx: int, case: dict):
            async with sem:
                case_id = case["id"]

                # 取消/超时：不再发起新调用，标记跳过
                if should_stop is not None and should_stop():
                    results[idx] = TaskResult(case_id, False, skipped=True,
                                              error="已取消")
                    if on_result is not None:
                        await on_result(results[idx])
                    return

                key = self._cache_key(case, prompt_version)

                # 断点续跑：已完成直接复用缓存
                if checkpoint is not None and checkpoint.is_done(case_id):
                    cached = self._get_cache(key) if use_cache else None
                    results[idx] = TaskResult(case_id, True, cached or {},
                                              cached=True, skipped=True)
                    if on_result is not None:
                        await on_result(results[idx])
                    return

                cached = self._get_cache(key) if use_cache else None
                if cached is not None:
                    results[idx] = TaskResult(case_id, True, cached, cached=True)
                    if checkpoint is not None:
                        checkpoint.mark_done(case_id)
                    if on_result is not None:
                        await on_result(results[idx])
                    return

                r = await self._run_with_retry(qa_func, case)
                if r.success:
                    if use_cache:
                        self._set_cache(key, r.data)
                    if checkpoint is not None:
                        checkpoint.mark_done(case_id)
                results[idx] = r
                if on_result is not None:
                    await on_result(r)

        await asyncio.gather(*[worker(i, c) for i, c in enumerate(cases)])
        return results

    # ---- 统计 ----
    @staticmethod
    def summarize(results: list) -> dict:
        total = len(results)
        success = sum(1 for r in results if r.success)
        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "cached": sum(1 for r in results if r.cached and not r.skipped),
            "skipped": sum(1 for r in results if r.skipped),
            "failed_ids": [r.case_id for r in results if not r.success],
        }
