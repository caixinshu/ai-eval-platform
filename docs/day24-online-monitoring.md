# Day 24：线上质量监控与 badcase 回流

## 今日目标

离线评测防退化，线上监控发现未知问题。今天把真实流量接进评测体系：抽样评测、用户反馈收集、badcase 自动归类、待标注回流，以及 5 个面板的线上看板。

## 1. 线上监控 vs 离线评测

| 对比项 | 离线评测 | 线上监控 |
|--------|----------|----------|
| 输入 | 人工构造的评测集 | 真实用户问题 |
| 时机 | 发布前 / 定时 | 实时 / 准实时 |
| 覆盖 | 有限但可控 | 无限但不可控 |
| 成本 | 可全量评测 | 只能抽样 |
| 作用 | 防退化 | 发现未知问题 |

两者不是替代关系：离线负责「已知问题不能变差」，线上负责「找出还没进评测集的问题」。

## 2. 线上抽样评测

[monitor/online_sampler.py](../monitor/online_sampler.py) 两个约束：

1. **成本可控**：采样率 + 每小时硬上限，突发流量不会把评测队列打爆
2. **结果可复现**：按 `request_id` 做 MD5 分桶，不是 `random`，同一请求在同一小时桶内重放结论一致

```python
sampler = OnlineSampler(sample_rate=0.02, max_per_hour=200)
if sampler.should_sample(request_id, hour_key):
    enqueue_for_eval(request_id)
```

细节：跨小时自动重置计数；空 `request_id` 直接不采样；采样率越界、上限为负直接报错；内部加锁，多线程调用不会把小时计数写乱。支持 `ONLINE_SAMPLE_RATE` / `ONLINE_SAMPLE_MAX_PER_HOUR` 环境变量。

## 3. 用户反馈收集

表结构见 [sql/feedback.sql](../sql/feedback.sql)，开发库由 SQLAlchemy 自动建表：

```sql
CREATE TABLE user_feedback (
    id VARCHAR(36) PRIMARY KEY, request_id VARCHAR(64) NOT NULL,
    question TEXT, answer TEXT,
    rating VARCHAR(10) NOT NULL,       -- good / bad
    reason VARCHAR(50),                -- 不准确/不相关/太啰嗦/有害
    comment TEXT, issue_category VARCHAR(30),
    user_id VARCHAR(64), biz_line VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_feedback_rating_created ON user_feedback(rating, created_at);
```

[monitor/feedback_collector.py](../monitor/feedback_collector.py) 把差评评论 + 用户选择的原因一起匹配到 5 类：

| 分类 | 关键词示例 |
|------|------------|
| hallucination | 编造、瞎说、不存在、没有依据 |
| irrelevant | 答非所问、没回答、不相关 |
| incomplete | 不完整、漏了、缺少 |
| format | 格式、看不懂、乱码 |
| tone | 态度、语气、太生硬 |

映射不到统一进 `other`，不丢数据。写入反馈时立即归类并落库，看板按 `issue_category` 聚合。

接口：

```powershell
# 用户反馈
POST /api/feedback
{"request_id":"req-1","question":"退款多久到账","answer":"...","rating":"bad","comment":"回答是编造的"}

# 抽样评测结果（采样器命中后写入）
POST /api/monitor/samples
{"request_id":"req-1","question":"...","answer":"...","score":88,"biz_line":"退款","latency_ms":900}
```

## 4. badcase 回流与质量管控

[monitor/badcase_reflow.py](../monitor/badcase_reflow.py) 的流程不是「差评全塞进回归集」：

1. **归一化 + 去重**：去空白与标点后截断 30 字作为聚类 key，「退款多久到账？」和「退款多久到账」算同一问题
2. **频次门槛**：同类问题至少出现 `min_count` 次才回流（默认 3），过滤一次性噪声
3. **默认 `verified=false`**：线上问题的正确答案往往不明确，先转成待标注用例
4. **人工确认**：业务专家补 `ground_truth` 后才把 `verified` 置为 `true`
5. **门禁隔离**：`run_eval.py` 自动跳过 `verified=false` 的用例，未验证数据只能做问题发现，不能参与门禁判定

CLI 实测（临时 demo 库，近 7 天 7 条差评）：

```text
> python scripts\reflow_badcases.py --days 7 --min-count 3
近 7 天差评 7 条，过滤后待回流 1 条
差评分类分布: {'hallucination': 4, 'irrelevant': 1, 'incomplete': 1, 'format': 1}
  fresh_db1ac92a  [hallucination] 退款多久到账？
已写入 eval_datasets/fresh_set.json，新增 1 条（verified=false，等待人工补标准答案）
回流用例：共 1 条 / 待标注 1 / 已入集 0

> python scripts\reflow_badcases.py --verify fresh_db1ac92a --ground-truth "退款一般 1-7 个工作日原路退回"
已确认 fresh_db1ac92a，verified=true
回流用例：共 1 条 / 待标注 0 / 已入集 1
```

## 5. 线上质量看板

[frontend/pages/monitor.html](../frontend/pages/monitor.html) 5 个面板，数据来自 `GET /api/monitor/overview?days=30`：

| 面板 | 指标 | 更新频率 |
|------|------|----------|
| 质量总览 | 24h 抽样均分、差评率、抽样数 | 每小时（24 个小时桶） |
| 问题分布 | 近 7 天差评按 5 类 + other 占比 | 每日 |
| 质量趋势 | 近 30 天抽样均分 | 每日 |
| 业务线明细 | 各业务线抽样数与均分 | 每日 |
| 回流进度 | 待标注 / 已入集 / 分类明细 | 每日 |

空数据的处理是刻意的：没有抽样的小时/天返回 `null`，图表留空，不把「没数据」画成 0 分；没有反馈时差评率返回 `null` 而不是 0%。看板顶部 4 张卡：24h 抽样均分、24h 差评率、近 7 天 badcase、待标注回流用例。

浏览器实测（临时 demo 库：12 条抽样、9 条反馈、1 条已确认回流）：

- 24h 抽样均分 81.67，抽样 6 条；差评率 100%（demo 近 24h 恰好只有 2 条差评）
- 问题分布：hallucination 4 / format 1 / incomplete 1 / irrelevant 1
- 业务线：退款 5 条 81.6、物流 3 条 82.3、账户安全 2 条 68.0、产品咨询 2 条 84.0
- 回流：1 / 1 已入集，hallucination 分类 1 条
- 3 张图（24h、问题分布、30 天趋势）全部渲染，页面无错误提示

## 6. 今日产出

- `monitor/online_sampler.py`：稳定哈希抽样 + 小时限流
- `monitor/feedback_collector.py`：差评收集 + 5 类自动归类
- `monitor/badcase_reflow.py`：去重、频次门槛、`verified` 流转、进度统计
- `scripts/reflow_badcases.py`：回流 CLI + `--verify` 人工确认 + `--stats`
- `backend/models/feedback.py`、`backend/schemas/monitor.py`、`backend/services/monitor_service.py`、`backend/routers/monitor.py`
- `sql/feedback.sql`：生产库 DDL
- `frontend/pages/monitor.html` + `frontend/charts/monitor.js`：5 面板线上看板
- `tests/test_monitor.py`：14 条测试（抽样、归类、回流、API、空数据）

## 7. 遗留与风险

| 风险 | 说明 | 处理 |
|------|------|------|
| 采样器未接入 `/ask` | 当前是独立组件，网关需要在请求后调用 `should_sample` 并写 `/api/monitor/samples` | 接入网关或 BFF；不要在被测应用里直接写平台库 |
| 反馈入口未嵌入页面 | 只有 `POST /api/feedback`，没有面向用户的反馈组件 | 在前端问答页加「有帮助 / 没帮助」按钮，带上 request_id |
| Python 聚合的规模上限 | 当前把 30 天数据拉到内存聚合，适合中小流量 | 大流量改数据库聚合 + 小时/日预计算表 |
| demo 数据 | 浏览器验证用的是临时 SQLite 演示库，不是生产流量 | 保留为验收证据，不写入仓库 |
| 无主动告警 | 看板只展示，未接告警通道 | 差评率/均分越线接飞书/邮件；复用 Day 22 门禁阈值思路 |
| 回流频次门槛 | 默认 3 次，低流量业务可能长期收集不到 | 低流量业务可降到 1，但需更严格的人工确认 |
