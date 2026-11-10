# Day 2：评测指标体系设计

> 项目三第 1 周 · 建立可量化、可复现的 AI 评测指标体系

## 一、六大类评测指标总览

| 类别 | 指标 | 类型 | 定义 |
|------|------|------|------|
| **准确性** | accuracy | 规则 | 预测正确的比例 |
| | exact_match | 规则 | 归一化后完全匹配 |
| | f1 | 规则 | 词元重叠 F1 分数 |
| **语义相似度** | bert_score | 外部 | BERT 嵌入 token 级相似度 |
| | cosine_similarity | 外部 | 句向量余弦相似度 |
| **RAG 专项** | faithfulness | LLM评分 | 回答基于上下文的程度 |
| | context_precision | LLM评分 | 检索结果与问题相关比例 |
| | context_recall | LLM评分 | 上下文覆盖答案信息比例 |
| | answer_relevance | LLM评分 | 回答与问题相关程度 |
| **安全合规** | toxicity | 外部 | 有害内容概率 |
| | jailbreak | 规则 | 越狱/违规检测 |
| **效率** | latency_p95 | 规则 | P95 响应延迟 |
| | tokens_per_request | 规则 | 单次 Token 消耗 |
| | cost_per_request | 规则 | 单次请求成本 |
| **格式** | format_valid | 规则 | JSON/Schema 格式合规 |

共 **15 个指标**，定义在 `metrics/dictionary.py`。

## 二、规则指标 vs LLM 评分指标

| 类型 | 特点 | 代表指标 | 适用场景 |
|------|------|---------|---------|
| **规则指标** | 确定性、可复现、零成本 | accuracy、f1、latency、format_valid、jailbreak | 有明确对错的场景 |
| **LLM 评分指标** | 语义理解能力强、有成本、有波动 | faithfulness、context_recall、answer_relevance | 语义判断场景 |
| **外部工具指标** | 准确率高、需装依赖 | bert_score、toxicity | 需要深度语义理解 |

**设计原则**：能用规则的不用 LLM，能用 LLM 评分的不用人工。L1 单元层全用规则，L2 组件层混合使用。

## 三、文件结构

```
metrics/
├── __init__.py        # 统一导出
├── dictionary.py      # 指标字典（15个指标的定义、公式、类型）
├── weights.py         # 权重配置（5种场景预设）
├── accuracy.py        # 准确性：accuracy, exact_match, f1
├── similarity.py      # 相似度：cosine_similarity, bert_score
├── rag.py             # RAG：faithfulness, context_precision/recall, answer_relevance
├── safety.py          # 安全：toxicity, jailbreak
├── efficiency.py      # 效率+格式：latency, tokens, cost, format_valid
└── scorer.py          # 综合评分器（加权求和 + 等级）
```

## 四、权重配置（5 种场景）

| 预设 | 侧重 | 权重和 |
|------|------|--------|
| default | 均衡 | 1.0 |
| qa | 准确性 + 忠实度 | 1.0 |
| generation | 相关性 + 格式 | 1.0 |
| safety | 安全合规优先 | 1.0 |
| performance | 效率优先 | 1.0 |

## 五、综合评分示例

模拟一组指标得分，综合得分 **82.71/100（B 良好）**：

```
accuracy          贡献 8.50
f1                贡献 11.70
faithfulness      贡献 9.00
answer_relevance  贡献 5.28
latency_p95       贡献 2.93
...
```

## 六、使用示例

```python
from metrics import compute_composite_score, accuracy, faithfulness, toxicity

# 计算单个指标
acc = accuracy(["巴黎"], ["巴黎"])
f = faithfulness("回答", ["上下文1", "上下文2"])

# 综合评分
scores = {
    "accuracy": 0.85, "f1": 0.78, "faithfulness": 0.90,
    "answer_relevance": 0.88, "latency_p95": 800.0,
    # ...
}
result = compute_composite_score(scores, preset="qa")
print(f"得分: {result['total']}")  # 82.71
```

## 七、降级策略

所有需要外部依赖的指标都有降级实现：
- `bert_score` → 降级为 F1
- `cosine_similarity` → 降级为 TF-IDF 余弦（中文 2-gram）
- `toxicity` → 降级为关键词匹配
- RAG 4 指标 → 降级为关键词覆盖率

**目的**：框架在无 GPU、无 LLM API 时也能跑通，用于验证流程。
