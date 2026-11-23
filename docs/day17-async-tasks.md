# Day 17：异步任务调度

> 项目三第 3 周 · 让长评测跑在后台：并发执行、进度上报、取消、超时、重启恢复，五件事一次补齐。

## 一、为什么必须异步

一次评测要逐条调用被测应用，几百条用例串行跑几十分钟。放在 HTTP 请求里会直接超时（浏览器 30s、网关 60s），用户只看到「转圈 → 报错」，连任务有没有跑都不知道。

Day 16 已经把「建任务立即返回 + 前端轮询」的骨架搭好了，Day 17 补的是后台这一侧真正把任务跑对：

```
POST /api/runs  →  201 {run_id}        （立即返回）
      │
      └─ BackgroundTasks → execute_eval
                          ├─ EvalRunner 并发执行（Semaphore）
                          ├─ 每完成一条：评分 → 写 eval_results → 推进度
                          ├─ 每 5 条提交一次事务
                          └─ 终态：done / cancelled / failed
GET /api/runs/{id}/status  ←  前端每 2s 轮询一次
```

## 二、五个关键机制

### 1. 并发 + 进度上报

`EvalRunner` 从 Day 12 就支持并发/重试/缓存，这次给它加了两个可选钩子，保持默认行为不变：

- `on_result`：每完成一条（含命中缓存）回调一次，服务层在这里评分、落库
- `should_stop`：每个 worker 开始前检查一次，返回 True 则剩余用例标记 `skipped`

进度按「已落库条数 / 总数」计算，**每 5 条提交一次**（`COMMIT_EVERY`）。逐条提交在 SQLite 上是无谓的刷盘，全部攒到最后又会让进度条长时间不动，5 条是两者之间的折中。

指标汇总（`metric_snapshots`）在整批结束后一次性写入，不在逐条路径上。

### 2. 取消：标记位 + 逐条检查

取消不能直接 kill 线程（Python 线程无法安全中断），采用**协作式取消**：

1. 前端调 `POST /api/runs/{id}/cancel`
2. 接口只把 `eval_runs.cancel_requested` 置 True，立即返回
3. 执行循环每处理一条前读一次该字段（用独立的短会话读，不干扰主会话里未提交的进度）
4. 命中则剩余用例全部跳过，终态 `status=cancelled`

为什么逐条检查而不是立刻中断：正在执行的那 1~N 条（N=并发数）已经发出请求，强行丢弃只会让结果和进度对不上；让它们跑完、后续不再发新请求，数据才自洽。

### 3. 整体超时

`EVAL_TIMEOUT_SECONDS`（默认 1800 秒）是**整批**的兜底：数据源卡死、被测应用某个请求永远不返回时，靠单条重试是救不回来的。

每处理一条检查一次 `time.time() >= deadline`，超时后终态 `status=failed`，`error_message` 明确写「评测超时，请缩小数据集或调大 EVAL_TIMEOUT_SECONDS 后重跑」。前端看到 failed 就能停止轮询。

### 4. 重启恢复：别让前端永远转圈

服务进程被 kill / 崩溃时，数据库里会留下 `status=running` 的任务，但执行线程已经不在了。前端每次轮询都拿到「还在跑」，进度条永远卡住。

做法：应用启动（`lifespan`）时调用 `recover_stale_runs()`，把所有 `running` 任务统一置 `failed`，`error_message` 写「服务重启导致任务中断，请重新发起评测」。宁可明确失败，也不要假装还在跑。

### 5. 单条失败隔离

单条用例抛异常只影响自己：`EvalRunner` 返回 `TaskResult(success=False, error=...)`，服务层仍然写一条 `passed=False` 的结果，回答前缀 `[应用异常]` 保留原因。整批继续跑，终态仍是 `done`，失败条数体现在 `/status` 的 `failed` 字段里。

## 三、前端轮询的正确姿势

`frontend/poll.js` 提供两个函数：

```js
import { pollRunStatus, cancelRun } from "./poll.js";

const task = pollRunStatus(runId, {
  interval: 2000,                       // 2 秒一次，够实时又不打爆接口
  onProgress: (s) => render(s.progress),
  onFinish: (s) => renderResult(s.status),   // done / failed / cancelled
  onError: () => showRetryHint(),
});

// 用户点取消
await cancelRun(runId);
// 页面卸载 / 切换路由时务必停掉
task.stop();
```

四条实践要点：

1. **终止条件是三种终态**（done / failed / cancelled），不是「progress === 100」——失败和取消的任务进度永远到不了 100
2. **单次请求失败不终止轮询**：网络抖动交给下一轮自愈，避免用户切个 Wi-Fi 就丢掉整个任务
3. **必须能 stop**：组件卸载、切换页面时不停定时器，就是在泄漏
4. **取消后不要立刻停轮询**：取消只是请求，任务真正停下要等执行循环走到下一个检查点，仍需轮询到 `cancelled`

## 四、测试覆盖

`tests/test_api.py` 新增 5 条，全部走临时 SQLite，不依赖真实模型：

| 用例 | 验证点 |
|------|--------|
| `test_single_case_failure_isolated` | 一条抛异常，任务仍 done，另一条正常出分，异常回答带前缀 |
| `test_run_cancel_marks_cancelled` | 预置 `cancel_requested` 后执行，被测应用一次都不调用，终态 cancelled |
| `test_cancel_api` | pending 可取消；done 返回 400 INVALID_PARAM |
| `test_run_timeout_marks_failed` | 超时阈值置 0，终态 failed，error_message 含「超时」 |
| `test_recover_stale_running_runs` | running 被置 failed，done 不受影响 |

全量 60 条测试通过。

## 五、与计划的四处偏差（有意为之）

| 偏差 | 原因 |
|------|------|
| `EvalRunner` 增加 `on_result / should_stop / use_cache` 三个可选参数，而不是在服务层重写一套循环 | 并发/重试已有实现，重写等于复制粘贴；默认值保持原行为，原有 7 条引擎测试不动 |
| 取消粒度是「每个 worker 启动前」，并发下最多多跑 `concurrency` 条 | 无法安全中断已在执行的请求；多跑几条换来数据自洽，可接受 |
| 评测服务关闭引擎缓存（`use_cache=False`） | 缓存 key 只有问题和 Prompt 版本，不含被测应用版本；跨轮次复用旧回答会污染对比结果 |
| `database.init_db` 增加 SQLite 轻量迁移 | `create_all` 不会给已有表加列，本地开发库需要补 `cancel_requested`；生产仍走 `sql/schema.sql` |

## 六、Day 17 验收

- `POST /api/runs` 立即返回，后台并发执行，前端 2 秒轮询可见进度
- 取消、超时、单条失败、重启恢复四条路径都能走到明确终态
- `python -m pytest -q`：60 passed
