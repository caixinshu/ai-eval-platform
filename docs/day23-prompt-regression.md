# Day 23：Prompt 变更回归与灰度

## 今日目标

建立 Prompt 变更的完整回归流程：版本对比、逐用例差异分析、灰度分流与自动回滚。核心原则是**别被均值骗了**——总分上涨不代表改版成功，必须看具体哪些用例退化、退化集中在哪个业务分类。

## 1. Prompt 变更标准流程（7 步）

| 步骤 | 动作 | 本项目的落地方式 |
|------|------|------------------|
| 1 | 修改 Prompt → 提交 PR | `prompts/` 变更触发 PR workflow |
| 2 | CI 自动跑冒烟评测（20 条） | `scripts/run_eval.py --limit 20` |
| 3 | 门禁检查：硬阈值 + 相对基线 | `scripts/quality_gate.py`（Day 22） |
| 4 | 通过 → 生成 diff 报告 → 人工 review | `scripts/prompt_diff.py` 输出 improved / degraded |
| 5 | 合并 → 每日全量回归 | `daily-regression.yml`（55 条） |
| 6 | 发布 → 小流量灰度（5%） | `app/ab_router.py` 按 user_id 稳定分流 |
| 7 | 灰度指标正常 → 全量 | `app/gray_guard.py` 5 项指标自动判断回滚 |

门禁负责「能不能进」，diff 负责「进去之后到底改好了哪些、改坏了哪些」，灰度负责「上线后真实流量是否验证了离线结论」。

## 2. 逐用例差异分析

[analysis/prompt_diff.py](../analysis/prompt_diff.py) 逐条对比两次评测，按 ±5 分阈值分成三组：

- `improved`：提升 ≥5 分，按涨幅降序
- `degraded`：下降 ≥5 分，按跌幅升序（最差的排最前）
- `unchanged`：±5 分以内，视为噪声

输入兼容三种形态：`run_eval.py` 的 `case_results`、平台 `/api/runs/{id}/results` 的 `items`、直接传入逐用例列表。缺少 `total_score` 时按指标白名单折算成 0-100（避免把 `f1`、`exact_match` 这类诊断项混进平均）。

除三组明细外，额外做两件事：

1. **分类归因**：按 `category` 统计提升/退化/未变数量与平均变化，退化最多的分类排最前。
2. **风险提示**：如果净变化为正但仍有退化，提示「均值可能掩盖问题」；如果 60% 以上退化集中在同一分类，直接点名该分类——即使总分上涨也不能上线。

CLI：

```powershell
python scripts\prompt_diff.py baselines\latest.json reports\candidate.json `
  --label-baseline v1.2.0 --label-current v1.3.0 `
  --json reports\prompt-diff.json --markdown reports\prompt-diff.md
```

真实输出（用冒烟基线自身对比，验证链路与空差异路径）：

```text
基线 20 条 / 当前 20 条 / 基线独有 0 条
提升 0 / 退化 0 / 未变 20 / 净变化 +0
风险提示: 无退化用例
  退款政策   提升 0 / 退化 0 / 平均 +0.00
  物流查询   提升 0 / 退化 0 / 平均 +0.00
  产品咨询   提升 0 / 退化 0 / 平均 +0.00
  账户安全   提升 0 / 退化 0 / 平均 +0.00
```

需要说明：当前没有 `LLM_API_KEY`，mock 生成直接拼检索片段，Prompt 内容不参与生成，因此同一数据集两次运行必然 0 差异。improved / degraded 的逻辑由单元测试用构造数据覆盖；接入真实 LLM 后即可产生有意义的 Prompt diff。

## 3. 灰度路由

[app/ab_router.py](../app/ab_router.py) 按 `user_id` 做稳定分流：

```python
router = PromptRouter("v1.3.0", ratio=0.05)
router.pick_version("user-42", "v1.2.0")   # 同一用户永远得到同一结果
```

- 用 MD5 取 `[0, 1)` 分桶，而不是 `random`，保证刷新、重放、跨实例一致
- `ratio=0` 全量稳定版，`ratio=1` 全量新版，便于测试和紧急切换
- 空 `user_id` 一律走稳定版，避免匿名流量被误分到新版本
- 支持从 `GRAY_VERSION` / `GRAY_RATIO` 环境变量构造

实测：10000 个用户、`ratio=0.05`，命中数在 350-650 区间内（单元测试断言），分布符合预期。

## 4. 灰度监控与回滚

[app/gray_guard.py](../app/gray_guard.py) 接收稳定版与灰度版在同一时间窗的聚合快照：

| 指标 | 判断方式 | 回滚阈值 |
|------|----------|----------|
| 在线评测分数 | 绝对下降 | > 3 分（与离线噪声阈值一致） |
| 用户负反馈率 | 相对上涨 | > 30% |
| 拒答率 | 相对上涨 | > 20% |
| 延迟 P95 | 绝对值 | > 3000ms |
| Token 成本 | 相对上涨 | > 30% |

```python
result = GrayReleaseGuard().evaluate(stable_snapshot, candidate_snapshot)
if result["rollback"]:
    print(result["reasons"])   # 例如：延迟 P95 3500ms（> 3000ms）
```

设计细节：

- 分数下降用绝对差，比率与成本用相对涨幅；基数为 0、候选大于 0 时视为无穷大，直接触发
- 每个指标都返回 `checks` 明细（稳定值、灰度值、变化量、阈值、是否触发），便于灰度看板展示
- 缺指标、分数超出 `[0, 1]`、负数延迟等输入直接报错，不静默放过
- 灰度至少持续 24 小时，覆盖不同时段；期间两版必须并行，才有对比基准

## 5. 今日产出

- `analysis/prompt_diff.py`：improved / degraded / unchanged 明细、分类归因、风险提示、Markdown 报告
- `scripts/prompt_diff.py`：差异分析 CLI，支持 JSON + Markdown 双输出
- `scripts/run_eval.py`：新增逐用例 `case_results`，为 Prompt diff 提供输入
- `app/ab_router.py`：基于 user_id 的稳定灰度分流
- `app/gray_guard.py`：5 项监控指标 + 自动回滚判断
- `tests/test_prompt_regression.py`：19 条测试
- `baselines/latest.json`：重新生成，包含 20 条逐用例结果

## 6. 遗留与风险

| 风险 | 说明 | 处理 |
|------|------|------|
| mock 模式无 Prompt 敏感性 | 无 LLM Key 时输出只由检索片段决定，Prompt diff 必然全为未变 | 配好 Key 后重跑两版，diff 才具备决策价值 |
| 路由未接入 `/ask` | 当前只有一个本地 Prompt 模块，平台 Prompt 版本存在数据库里，尚未做「按版本加载 Prompt」 | 接入时用 `PromptRouter` 选版本，再由版本号加载 Prompt 内容；不要只返回版本标签 |
| 监控快照来源 | `GrayReleaseGuard` 只做判断，真实负反馈/拒答/成本需要埋点聚合 | 先接每日离线抽样 + 网关日志，再补实时看板 |
| 差异阈值 | ±5 分为默认值，不同指标波动不同 | 用 `derive_thresholds.py` 的历史 σ 校准，波动大的指标单独设阈值 |
| 灰度回滚执行 | 当前返回回滚建议，未自动切流 | 接入配置中心或网关后，把 `rollback=True` 映射为切回稳定版 |
