# Day 19：可视化看板

> 项目三第 3 周 · 用 ECharts 把「需要计算」变成「一眼看到」：能力雷达、版本趋势、分类短板、版本差异，外加首页质量概览。

## 一、看板构成

首页 `/` 即质量概览，四张图 + 四个关键数字：

| 模块 | 图表 | 回答什么问题 |
|------|------|-------------|
| 能力雷达 | 六项指标 vs 目标基线 | 能力短板在哪 |
| 版本趋势 | 最近 5 次总分折线 + 及格线 80 | 整体在变好还是变坏 |
| 分类通过率 | 分组柱状图，低于 70% 标红 | 哪类问题最严重 |
| 版本对比 | 本次 vs 基线的分项条形图 | 这次改版提升了什么、退化了什么 |

顶部数字：最近总分（含等级徽章）、通过率、待处理 Badcase、最近评测（版本/数据集/时间），并带「发起评测」「查看最新报告」快捷入口。

## 二、数据从哪来

新增一个聚合接口，避免首页拿列表接口拼五次：

```
GET /api/dashboard?dataset_id=ds_xxx   # dataset_id 省略时取最近一次已完成评测
```

返回：

```jsonc
{
  "dataset":   { "id": "...", "name": "黄金集" },
  "latest":    { "run_id": "...", "total_score": 82.5, "grade": "B (良好)",
                 "total": 4, "passed": 3, "failed": 1, "prompt_version": "v1.1.0",
                 "finished_at": "..." },
  "radar":     { "indicators": [ { "key": "faithfulness", "label": "忠实度",
                                   "target": 0.85, "value": 0.88 }, ... ],
                 "missing": [] },
  "trend":     [ { "run_id": "...", "label": "v1.0.0", "score": 74.6,
                   "finished_at": "..." }, ... ],
  "categories":[ { "category": "退款", "total": 2, "passed": 1, "pass_rate": 50.0 }, ... ],
  "compare":   { "total": {...}, "metrics": {...}, "regressions": [...],
                 "improvements": [...], "baseline_run_id": "...", "baseline_version": "v1.0.0" },
  "badcase_count": 1
}
```

聚合逻辑在 `backend/services/dashboard_service.py`：

- 趋势只取**同一数据集**最近 5 次已完成任务，按完成时间正序，避免拿黄金集和对抗集的分数硬比
- 分类通过率通过 `eval_results.case_id → test_cases.category` 关联统计，最差分类排前面
- 对比复用 `report_service.compare`，与结果详情页同一套口径（±3 个百分点内视为噪声）
- `grade` 复用 `metrics/scorer.py` 的 A/B/C/D/F 分级

## 三、颜色即结论

图表颜色不是装饰，而是结论：

- 分类通过率 < 70% 标红，≥ 70% 标绿，并画一条 70% 虚线阈值
- 趋势图 80 分及格线用红色虚线，不看刻度也知道这次有没有掉线
- 雷达目标基线用灰色虚线，当前版本用蓝色实心，缺口一眼可见

这正是可视化的价值：把「读数字 → 心算对比 → 判断好坏」压缩成「一眼看到」。

## 四、雷达六维的口径

计划给了六个固定维度，落地时用平台真实产出的指标对齐：

| 维度 | 数据来源 | 目标值 |
|------|---------|--------|
| 忠实度 | `faithfulness`（Ragas / LLM Judge） | 0.85 |
| 答案正确性 | `correctness`（语义相似度） | 0.84（Day 9 校准值） |
| 答案相关性 | `answer_relevance` | 0.85 |
| 上下文精度 | `context_precision` | 0.70 |
| 安全性 | `safety`（对抗集判定） | 0.95 |
| 性能 | 由平均响应时长换算：`1 - avg_ms / 3000` | 0.85 |

两条原则：

1. **缺失不伪造**：某次评测没采集忠实度，就返回 `value: null`，雷达图对应方向留空，并在图下注明「暂无数据：忠实度」。用 0 冒充会把「没测」误读成「极差」。
2. **性能可计算**：延迟类指标不进 `metric_snapshots`，但每条结果都有 `duration_ms`，按 `metrics/scorer.py` 的 3 秒经验阈值换算成 0~1，口径与综合评分器一致。

## 五、前端实现

```
frontend/
├── index.html           # 质量概览首页（原跳转页升级）
├── vendor/
│   └── echarts.min.js   # ECharts 5.5.1，本地托管，离线可用
└── charts/
    ├── radar.js         # 六指标 vs 目标
    ├── trend.js         # 版本趋势 + 及格线
    ├── category.js      # 分类通过率 + 阈值着色
    └── compare.js       # 本次 vs 基线分项条形图
```

- 每个 `charts/*.js` 只暴露一个 `renderXxx(element, data)`，返回 ECharts 实例；页面统一收集并在 `resize` 时 `chart.resize()`
- 对比图只画两次评测都存在的指标，避免用 0 冒充缺失
- 空状态、加载失败、无基线都有明确文案，不会出现空白画布

ECharts 用本地文件而不是 CDN：评测平台经常在内网/离线环境跑，CDN 挂掉不该让看板变白屏。

## 六、验收

- 后端：`python -m pytest tests/test_api.py -q` → 19 passed
  - 新增 `test_dashboard_aggregates_latest_run`：最近评测、雷达缺失值、趋势顺序、分类短板排序、基线对比
  - 新增 `test_dashboard_empty`：无已完成任务时返回空看板
- 浏览器实测（临时 SQLite + 演示数据）：
  - 数字卡：82.5 分 / B（良好）/ 通过率 75%（3 of 4）/ Badcase 1
  - 四张图均渲染出 ECharts canvas（非空），雷达图例「当前版本 / 目标基线」，趋势横轴 v1.0.0 → v1.1.0
  - 分类图「退款」50% 显示红色（低于阈值）
  - 控制台无报错

## 七、与计划的偏差

| 偏差 | 原因 |
|------|------|
| ECharts 本地托管（`frontend/vendor/echarts.min.js`）而非 CDN | 平台面向内网/离线环境，CDN 不可用会导致看板整体白屏 |
| 趋势/分类/对比基于「同一数据集」而非全平台 | 黄金集与对抗集的分数不可直接比较，同一数据集内看演进才有意义 |
| 雷达缺失指标显示空档而非 0 | 0 会被误读为「能力极差」，空档 + 文案才是「未采集」 |
| 首页取代原跳转页，不再默认跳任务列表 | Day 19 的目标就是让质量状况一眼可见，任务列表降为二级页 |
