# Day 13：结果分析与报告 v1（分析层）

> 项目三第 2 周 · 把评测数据变成能指导决策的结论：分组统计、badcase 聚类、版本对比。

## 一、结果分析的四个层次

| 层次 | 回答的问题 | 本日实现 |
|------|-----------|---------|
| L1 总览 | 整体多少分、能不能上线 | 总分 + 等级（Day 6 已落地） |
| L2 分组 | 哪个类别最差 | `aggregator.group_badcases` |
| L3 个案 | 失败模式是什么 | `badcase.cluster_badcases` |
| L4 趋势 | 比上个版本好了还是差了 | `comparator.compare_runs` |

只看 L1 会得出「分数低」这种没法行动的结论，L2-L4 才能回答「改哪里」。

## 二、分组统计（真实数据：黄金集 55 条 baseline）

| 类别 | badcase 数 | 占比 | 主要失败指标 |
|------|-----------|------|-------------|
| 退款政策 | 10 | 18% | answer_relevancy×10、context_precision×10、context_recall×7 |
| 产品咨询 | 10 | 18% | answer_relevancy×6、context_precision×6、correctness×4 |
| 物流查询 | 9 | 16% | answer_relevancy×9、context_precision×9、context_recall×7 |
| 账户安全 | 9 | 16% | answer_relevancy×9、context_precision×9、context_recall×5 |
| 功能使用 | 9 | 16% | answer_relevancy×9、context_precision×9、context_recall×6 |
| 售后服务 | 8 | 14% | answer_relevancy×8、context_precision×8、context_recall×6 |

失败集中在 `answer_relevancy`（51/55）和 `context_precision`（51/55），是全局性的而非某一类别特有 —— 这本身就排除了「某一类知识没写好」的假设。

`aggregate(results, cases)` 按计划实现（均分升序，最差类别排最前），等 Day 14 报告里补上逐条得分后即可输出 avg_score / pass_rate。

## 三、Badcase 聚类（bge 向量 + KMeans，5 簇）

| 簇 | 自动标签 | 条数 | 代表问题 |
|----|---------|------|---------|
| 2 | 发货 / 收到 / 快递 | 14 | 怎么查物流？ |
| 3 | 账号 / 密码 / 手机 | 12 | 怎么修改密码？ |
| 1 | 退款 / 多久 / 分期 | 11 | 你们的退款政策是什么？ |
| 0 | X1 / 支持 / 多少 | 9 | 这款手机的电池容量是多少？ |
| 4 | 保修 / 修期 / 维修 | 9 | 物流三天没更新了怎么办？ |

簇标签是「簇内高频二元组」，只用于快速浏览，不是真实语义分类（簇 4 就混进了物流逾期问题）。要看准确语义需要接入 LLM 聚类命名。

**结论**：badcase 是按业务主题均匀分布的，不是集中在某个话题上，说明问题在通用链路（生成方式 / 检索阈值），不在单篇知识。

## 四、版本对比（`analysis/comparator.py`）

`compare_runs(current, baseline)` 输出每项指标的 current / baseline / delta / delta_pct / improved / significant，并汇总 `regressions` 与 `improvements`。

**噪声阈值 3 个百分点**：LLM 评测有 ±2 分天然波动，1-2 分的「提升」多半是噪声。不加阈值会让团队追着噪声做无效优化；超过 3 个点才在报告里标红或标绿。

本次没有可比的两个版本（只有一个 baseline），版本对比能力由单测覆盖，Day 14 产出报告 v1 时接入真实 diff。

## 五、优化建议（由数据自动生成，5 条）

| 优先级 | 建议 | 数据依据 |
|--------|------|---------|
| P1 | 接入真实 LLM 后重跑基线 | 当前 model=mock，答案是检索片段拼接，正确性不具参考性 |
| P2 | CP/CR 相关性阈值从 0.75 校准到 0.65-0.70 | Day 11 实测：0.65 时 Recall 0.855，0.75 时仅 0.382；期望片段最大相似度均值 0.7223 |
| P3 | 知识库扩充到 50+ 片段并补同义问法 | 仅 13 个片段，top-2 已覆盖全部可召回内容 |
| P4 | 优先修「退款政策」类（10 条，占 18.2%） | 该类 badcase 最多，失败指标与全局一致 |
| P5 | 针对最大簇「发货/收到/快递」设计专项用例 | 该簇 14 条，是最大的失败模式 |

建议不是手写的：`build_suggestions()` 从 model、知识库规模、失败指标频次、类别分布、聚类结果中推导，数据变了建议会跟着变。

## 六、今日产出对照

| 计划产出 | 交付 |
|---------|------|
| 结果聚合器（按 category 分组） | ✅ `aggregate` + `group_badcases` |
| Badcase 聚类（KMeans + 高频模式） | ✅ bge 向量 + KMeans + 二元组自动标签 |
| 版本对比器（diff + 显著性） | ✅ 3 个百分点噪声阈值 + regressions/improvements |
| 分析结论 ≥3 条可执行建议 | ✅ 5 条，全部带数据依据 |

单测：`tests/test_analysis.py` 7 条通过（分组排序、badcase 分布、空输入、版本退化识别、零基线除零、小样本聚类、停用词过滤）。

## 七、下一步

- Day 14：HTML 报告 v1（总分红绿灯、指标卡、分组柱状图、badcase 展开、原始数据下载）
- 报告首屏必须是「结论区」：能否上线 + 一句话主因 + 1-3 条行动项
- 逐条得分写入报告后，`aggregate` 才能输出 avg_score / pass_rate
