# Day 6：评测框架选型 + 首轮基线

> 项目三第 1 周 · 选型评测框架，接上被测应用，跑出第一份全量基线报告

## 一、评测框架选型对比

### 1.1 主流框架对比

| 框架 | 语言 | 核心能力 | 优点 | 缺点 | 适用场景 |
|------|------|---------|------|------|---------|
| **Ragas** | Python | RAG 全链路指标（faithfulness/context_precision 等） | 指标全面、与 LangChain 集成好、社区活跃 | 依赖 LLM-as-Judge、中文支持需调优 | RAG 应用评测 |
| **DeepEval** | Python | 单元测试风格的 LLM 评测 | API 简洁、测试用例管理好 | 指标不如 Ragas 全 | LLM 单元测试 |
| **TruLens** | Python | 反馈函数 + 追踪 | 可视化好、追踪能力强 | 配置复杂、偏实验 | 研发阶段调试 |
| **自研规则** | Python | 关键词/格式/长度检查 | 无需 LLM、速度快、可控 | 语义理解弱 | 格式/安全/边界检查 |

### 1.2 最终方案：Ragas + 自研规则 混合

**选择理由**：
- **语义指标用 Ragas**：faithfulness、answer_relevancy、context_precision、context_recall 这四个 RAG 核心指标，Ragas 有成熟的 LLM-as-Judge 实现
- **业务规则用自研**：安全（违规词）、格式（非空/长度）、字数限制等，用规则更可控、更高效
- **不追求纯框架化**：框架覆盖不到的地方必须能自己写，保持灵活性

### 1.3 降级策略

由于当前环境无 LLM API Key，Ragas 的 LLM-as-Judge 无法直接使用。设计降级方案：

| 指标 | 有 API Key（Ragas） | 无 API Key（规则降级） |
|------|---------------------|----------------------|
| faithfulness | LLM 判断每条声明是否被上下文支持 | 声明中的关键词是否出现在上下文中 |
| answer_relevancy | LLM 判断回答是否针对问题 | 问题关键词在回答中的覆盖率 |
| context_precision | LLM 判断每个上下文是否相关 | 问题关键词在上下文中的覆盖率 |
| context_recall | LLM 判断黄金答案信息是否被上下文覆盖 | 黄金答案关键词在上下文中的覆盖率 |

降级实现复用 `metrics/rag.py` 中的规则版本，保证无 API Key 时框架也能跑通。

---

## 二、评测脚本实现

### 2.1 语义评测（`evaluation/ragas_eval.py`）

```python
def run_ragas_eval(cases, qa_func) -> dict:
    # 收集问答结果
    # 有 API Key -> Ragas 官方 LLM-as-Judge
    # 无 API Key -> metrics.rag 规则降级
    return {
        "faithfulness": ...,
        "answer_relevancy": ...,
        "context_precision": ...,
        "context_recall": ...,
        "engine": "ragas" | "rule",
    }
```

### 2.2 规则评测（`evaluation/rule_eval.py`）

| 指标 | 判定逻辑 | 阈值 |
|------|---------|------|
| safety | 命中违规词/越狱模式 → 0，否则 1 | =1.0 |
| format | 非空且 10-1000 字 → 1，过短 → 0，过长 → 0.5 | =1.0 |
| length | ≤200 字 → 1，否则 0 | =1.0 |
| correctness | F1 + 余弦相似度的平均 | ≥0.3 |

### 2.3 基线脚本（`scripts/run_baseline.py`）

流程（已优化：问答结果只收集一次，评测和 badcase 复用）：
1. 加载黄金集（55 条）
2. **一次性收集所有问答结果**（循环调用 `app.rag.ask()`，55 条只调 55 次）
3. 运行语义评测（4 指标，使用预收集结果）
4. 运行规则评测（安全/格式/长度/正确性，使用预收集结果）
5. 用 `metrics.scorer` 计算综合得分
6. 逐条分析 badcase（低于阈值的指标，使用预收集结果）
7. 输出 JSON 报告到 `reports/baseline_golden_v1.json`

---

## 三、首轮基线结果

> 以下结果来自规则降级评测（无 LLM API Key），接入真实 LLM 后需重跑。

### 3.1 语义指标

| 指标 | 得分 | 说明 |
|------|------|------|
| faithfulness | 1.0000 | mock 回答直接拼接上下文片段，忠实度满分 |
| answer_relevancy | 0.0424 | mock 回答是原始上下文片段，未针对问题组织语言，关键词重叠极低 |
| context_precision | 0.0485 | 检索相关性偏低（知识库仅 13 篇文档，粒度粗） |
| context_recall | 0.3545 | 上下文对黄金答案的覆盖度中等 |

### 3.2 规则指标

| 指标 | 得分 | 说明 |
|------|------|------|
| safety | 1.0000 | 无违规内容，安全检查全通过 |
| format | 1.0000 | 格式合规（非空、长度在合理范围） |
| length | 0.0000 | **全部超限**：mock 截断为 200 字 + "..." = 203 字，超过 200 字限制 |
| correctness | 0.3742 | 与标准答案的相似度（F1 + 余弦平均） |

### 3.3 综合得分

```
综合得分: 13.08 / 100
等级: F (不及格)
```

### 3.4 Badcase 分析

Badcase 数：**55 / 55**（全部用例均有指标低于阈值）

失败指标分布：
- **answer_relevancy 低于阈值**：55 条（100%）
- **context_precision 低于阈值**：55 条（100%）
- **length 低于阈值**：55 条（100%）
- **context_recall 低于阈值**：约 40 条（~73%）
- **correctness 低于阈值**：约 6 条（~11%）

主要问题：
1. **answer_relevancy 极低 (0.0424)**：mock LLM 直接返回上下文原始片段，未针对问题组织语言，问题关键词几乎不出现在回答中。接入真实 LLM 后此指标预期显著提升。
2. **context_precision 极低 (0.0485)**：知识库仅 13 篇文档，embedding 检索的相关性偏弱，且 mock 取前 2 篇拼接，无关内容拉低精度。
3. **length 全部 0 分**：`mock_llm_answer` 截断逻辑 `answer[:200] + "..."` 产出 203 字，超过 Prompt 要求的 200 字上限。这是 mock 生成器的已知缺陷，真实 LLM 受 Prompt 约束不会出现。
4. **context_recall 中等 (0.3545)**：约 1/3 的黄金答案信息能被检索上下文覆盖，仍有提升空间。
5. **correctness 偏低 (0.3742)**：mock 回答与标准答案的语义相似度有限。

**结论**：当前基线低分主要由 **mock LLM 降级** 和 **知识库规模小** 导致，并非 Prompt 或框架本身的问题。接入真实 LLM API Key 后需重跑，预期 answer_relevancy、context_precision、length、correctness 均会明显改善。

---

## 四、踩坑记录

### 坑 1：项目 `datasets/` 包与 HuggingFace `datasets` 命名冲突

**现象**：`from datasets import Dataset` 报错 `ImportError: cannot import name 'Dataset'`。

**根因**：项目的 `datasets/` 包遮蔽了 site-packages 中的 HuggingFace `datasets` 库。

**解决**：重命名项目包为 `eval_datasets/`，更新所有 import。

### 坑 2：chromadb telemetry 报错

**现象**：`Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given`。

**根因**：chromadb 0.5.20 的 telemetry 与 posthog 版本不兼容。

**解决**：设置环境变量 `ANONYMIZED_TELEMETRY=False` 禁用 telemetry。

### 坑 3：cosine_similarity 每次调用都加载模型导致评测极慢

**现象**：首轮基线规则评测阶段 55 条用例耗时约 550 秒（每条 ~10 秒）。

**根因**：`metrics/similarity.py` 的 `cosine_similarity` 每次调用都 `SentenceTransformer("paraphrase-MiniLM-L6-v2")` 重新加载模型，没有缓存。

**解决**：在模块级缓存模型实例（`_st_model` 单例），首次加载后复用。优化后规则评测耗时从 550s 降至 30s。

---

## 五、文件清单

| 文件 | 说明 |
|------|------|
| `evaluation/__init__.py` | 包初始化 |
| `evaluation/ragas_eval.py` | Ragas 语义评测（含规则降级） |
| `evaluation/rule_eval.py` | 规则评测（安全/格式/长度/正确性） |
| `scripts/run_baseline.py` | 首轮基线评测脚本（预收集优化） |
| `metrics/similarity.py` | 相似度模块（增加模型缓存，性能优化） |
| `reports/baseline_golden_v1.json` | 基线报告（含 badcase） |

---

## 六、下一步

- 接入真实 LLM API Key 后重跑基线，验证 Ragas 官方指标
- 针对 badcase 优化 Prompt 或知识库切分策略
- Day 7：跑对抗集和边界集的基线，分析安全性和边界表现
