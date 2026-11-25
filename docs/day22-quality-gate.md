# Day 22：评测门禁接入 CI

## 今日目标

把评测从「想起来才跑」变成「不达标就阻断合并」：PR 改动 Prompt / 被测应用 / 评测集时自动跑冒烟评测，硬阈值不达标或相对基线掉太多，直接让 CI 失败并在 PR 里评论具体差距。

## 1. 三种触发时机

| 时机 | 跑什么 | 本次实现 | 是否阻断 |
|------|--------|----------|----------|
| PR 提交 | 黄金集前 20 条 + 核心指标 | `ai-quality-gate.yml` | 是，阻断合并 |
| 每日定时 | 黄金集全量 55 条 + 全量基线对比 | `daily-regression.yml` | 否，失败即告警 |
| 发布前 | 黄金集全量 + 对抗集 + 边界集 | `release-gate.yml` | 是，阻断发布 |

> 与计划原文的差异：计划里的 workflow 会起 `db` 容器再调 API。本项目的 `scripts/run_eval.py` 直接跑评测引擎，不依赖数据库和平台进程，因此 CI 只装依赖、建知识库、跑评测，链路更短也更稳定。

## 2. 门禁判断

[scripts/quality_gate.py](../scripts/quality_gate.py) 实现 6 条规则：

| 指标 | 规则 | 阈值 | 说明 |
|------|------|------|------|
| safety | absolute + veto | 1.00 | 一票否决，命中立即返回 |
| faithfulness | both | min 0.85 / max_drop 0.03 | 既看绝对值也比基线 |
| correctness | both | min 0.80 / max_drop 0.05 | 答案正确性 |
| relevance | both | min 0.80 / max_drop 0.05 | 兼容 `answer_relevance` / `answer_relevancy` |
| context_precision | relative | max_drop 0.05 | 只看相对基线，避免知识库规模变化导致口径漂移 |
| performance | absolute | 0.70 | `1 - 平均延迟 / 3000ms` |

三个实现细节：

1. **指标归一**：历史报告字段不统一，`answer_relevancy`、`answer_relevance` 都映射到 `relevance`；报告标注 `metric_scale=percent` 时自动除以 100；缺 `performance` 但有 `avg_latency_ms` 时按 3 秒口径补齐。避免因命名差异误判「指标缺失」。
2. **失败信息可执行**：每条失败都带当前值、阈值、差多少；`--comment` 生成 Markdown 表格，PR 评论里能直接看到是哪项、差多少。
3. **退出码**：`0` 通过、`1` 未通过、`2` 报告读取失败，CI 直接按退出码判断。

本地跑通的两条路径（真实数据）：

```text
# 未通过：当前 mock 基线
python scripts/quality_gate.py baselines/latest.json baselines/latest.json
→ ❌ correctness: 0.399 < 硬阈值 0.80（差 0.401）
→ ❌ relevance:   0.042 < 硬阈值 0.80（差 0.758）
   exit 1

# 通过：单元测试里的合格报告（tests/test_quality_gate.py）
check_gate({safety:1.0, faithfulness:0.90, correctness:0.86,
            answer_relevance:0.88, context_precision:0.80, performance:0.92})
→ True, []
```

## 3. 统一评测入口

[scripts/run_eval.py](../scripts/run_eval.py) 把「跑评测 → 出门禁报告」收敛成一个命令：

```powershell
python scripts\run_eval.py --dataset golden --limit 20 --output reports\gate-result.json
```

- 有 `ground_truth`（黄金集）：语义四指标 + 规则指标；无 LLM Key 时语义自动降级为规则实现
- 无 `ground_truth`（对抗/边界集）：断言通过率，同时作为 `correctness`；`--min-assertion` 控制发布下限
- `performance` 用平均延迟换算；**先预热一条再计时**，否则 embedding 模型冷启动（本机约 170s）会把性能分拖到 0
- 默认不读缓存：CI 要看到本次代码的真实表现，缓存会掩盖回归

实测输出：

```text
黄金集 20 条（冒烟基线）：总得分 13.63，performance 0.926，平均延迟 221.9ms
黄金集 55 条（全量基线）：总得分 13.08，performance 0.948，平均延迟 154.8ms
```

## 4. 阈值怎么定

[scripts/derive_thresholds.py](../scripts/derive_thresholds.py) 扫描历史报告，按指标统计 `mean / σ / min / max`：

- 硬阈值建议 = `max(当前目标, mean - 2σ)`：**质量目标只能维持或收紧，不能因为当前分数低就下调**
- 相对下降建议 = `2σ`，夹在 `[0.03, 0.10]`
- `σ > 0.03`（3 分）标记为「波动大」，先解决稳定性再收紧门禁
- 样本 < 3 只做参考，不自动改规则

当前仓库真实输出（`baselines/thresholds.json`）：

| 指标 | 样本 | 均值 | σ | 建议硬阈值 | 备注 |
|------|------|------|---|------------|------|
| safety | 5 | - | - | 1.00 | 永远一票否决 |
| faithfulness | 3 | 1.000 | 0.000 | 1.00 | 分布稳定 |
| correctness | 3 | 0.382 | 0.012 | 0.80 | 当前均值低于目标，先提升质量 |
| relevance | 3 | 0.042 | 0.000 | 0.80 | 当前均值低于目标，先提升质量 |
| context_precision | 3 | 0.043 | 0.007 | - | 只看相对下降 |
| performance | 2 | 0.937 | 0.011 | 0.70 | 样本不足，沿用规则 |

这组数据也说明：**门禁先失败是正常的**。当前无 LLM Key，mock 生成直接拼检索片段，relevance / correctness 只有 0.04 / 0.40；门禁如实阻断，而不是把阈值降到 0.04 让它「变绿」。

## 5. CI 配置

| 文件 | 触发 | 行为 |
|------|------|------|
| `.github/workflows/ai-quality-gate.yml` | PR 修改 `prompts/app/evaluation/eval_datasets` 等；手动 | 20 条冒烟 → 门禁 → 失败自动评论 → 上传报告 |
| `.github/workflows/daily-regression.yml` | 每天 UTC 02:00；手动 | 55 条全量 → 对比 `baselines/full.json`，失败告警 |
| `.github/workflows/release-gate.yml` | 打 `v*` tag；手动 | 黄金集门禁 + 对抗集断言 ≥0.90 + 边界集断言 ≥0.85 |

共同步骤：安装双 requirements → `scripts/ingest.py` 建知识库 → 跑评测 → 门禁 → 上传 `reports/` 产物。PR 评论用 `actions/github-script` 读取 `reports/gate-comment.md`，包含指标、当前值、阈值和差距。

## 6. 今日产出

- `scripts/quality_gate.py`：6 条规则 + 一票否决 + 指标归一 + PR 评论
- `scripts/run_eval.py`：冒烟/全量统一入口，输出门禁可直接消费的 JSON
- `scripts/derive_thresholds.py`：基于历史分布的阈值推导
- `baselines/latest.json`（20 条冒烟基线）、`baselines/full.json`（55 条全量基线）、`baselines/thresholds.json`
- 3 个 GitHub Actions workflow
- `tests/test_quality_gate.py`：13 条测试（含真实评测入口的指标形状）

## 7. 遗留与风险

| 风险 | 说明 | 处理 |
|------|------|------|
| 无 LLM Key | Judge/语义走规则降级，relevance/correctness 偏低，门禁按设计失败 | 配置 `LLM_API_KEY` 后重跑基线，再复核阈值 |
| GitHub Actions 未实机执行 | 本机无 Docker / Actions runner，只做了 YAML 解析与脚本本地跑通 | 首次推送后在 Actions 页面确认；PR 评论需 `pull-requests: write` |
| Fork PR 评论权限 | 来自 fork 的 PR token 只读，自动评论可能失败 | 评论步骤失败不影响门禁结论；可改用 `pull_request_target` 或机器人 |
| 延迟口径 | 性能依赖 CI 机器速度，冒烟与全量基线不能混用 | 已拆分 `latest.json`（20 条）与 `full.json`（55 条） |
