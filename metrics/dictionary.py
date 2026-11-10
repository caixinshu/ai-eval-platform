"""
指标字典 (Metric Dictionary)
定义 6 大类评测指标的名称、定义、计算公式和类型。
"""
from dataclasses import dataclass, field
from enum import Enum


class MetricCategory(Enum):
    """指标大类"""
    ACCURACY = "accuracy"          # 准确性
    SIMILARITY = "similarity"      # 语义相似度
    RAG = "rag"                    # RAG 专项
    SAFETY = "safety"              # 安全与合规
    EFFICIENCY = "efficiency"      # 效率
    FORMAT = "format"              # 格式校验


class MetricType(Enum):
    """指标计算类型"""
    RULE = "rule"                  # 规则计算（精确匹配、字符串相似度）
    LLM_JUDGE = "llm_judge"        # LLM 评分
    EXTERNAL = "external"          # 外部工具（BERTScore 等）


@dataclass
class MetricDefinition:
    """单个指标的定义"""
    key: str
    name: str
    category: MetricCategory
    metric_type: MetricType
    definition: str
    formula: str
    range: tuple = (0.0, 1.0)
    higher_is_better: bool = True
    requires_golden: bool = True   # 是否需要黄金答案
    requires_context: bool = False  # 是否需要检索上下文


# ==================== 指标字典 ====================
METRICS: dict[str, MetricDefinition] = {
    # ---------- 1. 准确性指标 ----------
    "accuracy": MetricDefinition(
        key="accuracy",
        name="准确率",
        category=MetricCategory.ACCURACY,
        metric_type=MetricType.RULE,
        definition="预测正确的样本占总样本的比例",
        formula="accuracy = 正确数 / 总数",
        range=(0.0, 1.0),
        requires_golden=True,
    ),
    "exact_match": MetricDefinition(
        key="exact_match",
        name="完全匹配率",
        category=MetricCategory.ACCURACY,
        metric_type=MetricType.RULE,
        definition="预测答案与黄金答案完全一致（忽略大小写和首尾空白）的比例",
        formula="exact_match = normalize(pred) == normalize(gold) ? 1 : 0",
        range=(0.0, 1.0),
        requires_golden=True,
    ),
    "f1": MetricDefinition(
        key="f1",
        name="F1 分数",
        category=MetricCategory.ACCURACY,
        metric_type=MetricType.RULE,
        definition="基于词元重叠的 F1 分数（精确率和召回率的调和平均）",
        formula="F1 = 2 * (P * R) / (P + R)，P=重叠词/预测词，R=重叠词/黄金词",
        range=(0.0, 1.0),
        requires_golden=True,
    ),

    # ---------- 2. 语义相似度指标 ----------
    "bert_score": MetricDefinition(
        key="bert_score",
        name="BERTScore",
        category=MetricCategory.SIMILARITY,
        metric_type=MetricType.EXTERNAL,
        definition="基于 BERT 上下文嵌入的 token 级余弦相似度",
        formula="对预测和参考的 token 嵌入做两两余弦相似度，取最大匹配加权求和",
        range=(0.0, 1.0),
        requires_golden=True,
    ),
    "cosine_similarity": MetricDefinition(
        key="cosine_similarity",
        name="余弦相似度",
        category=MetricCategory.SIMILARITY,
        metric_type=MetricType.EXTERNAL,
        definition="预测答案与黄金答案的句向量余弦相似度",
        formula="cos(A,B) = (A·B) / (|A| * |B|)",
        range=(-1.0, 1.0),
        requires_golden=True,
    ),

    # ---------- 3. RAG 专项指标 ----------
    "faithfulness": MetricDefinition(
        key="faithfulness",
        name="忠实度",
        category=MetricCategory.RAG,
        metric_type=MetricType.LLM_JUDGE,
        definition="回答中所有声明都能从检索上下文中得到支持的比例",
        formula="faithfulness = 可由上下文支持的声明数 / 回答中总声明数",
        range=(0.0, 1.0),
        requires_golden=False,
        requires_context=True,
    ),
    "context_precision": MetricDefinition(
        key="context_precision",
        name="上下文精度",
        category=MetricCategory.RAG,
        metric_type=MetricType.LLM_JUDGE,
        definition="检索到的上下文中，与问题相关的比例",
        formula="context_precision = 相关上下文数 / 检索到的上下文总数",
        range=(0.0, 1.0),
        requires_golden=False,
        requires_context=True,
    ),
    "context_recall": MetricDefinition(
        key="context_recall",
        name="上下文召回率",
        category=MetricCategory.RAG,
        metric_type=MetricType.LLM_JUDGE,
        definition="黄金答案中需要的信息，有多少能在检索上下文中找到",
        formula="context_recall = 上下文中覆盖的答案属性数 / 答案总属性数",
        range=(0.0, 1.0),
        requires_golden=True,
        requires_context=True,
    ),
    "answer_relevance": MetricDefinition(
        key="answer_relevance",
        name="答案相关性",
        category=MetricCategory.RAG,
        metric_type=MetricType.LLM_JUDGE,
        definition="回答与问题的相关程度，是否答非所问",
        formula="由 LLM 判断回答是否针对问题，0-1 分",
        range=(0.0, 1.0),
        requires_golden=False,
        requires_context=False,
    ),

    # ---------- 4. 安全与合规指标 ----------
    "toxicity": MetricDefinition(
        key="toxicity",
        name="毒性分数",
        category=MetricCategory.SAFETY,
        metric_type=MetricType.EXTERNAL,
        definition="回答中包含辱骂、仇恨、暴力等有害内容的概率",
        formula="toxicity = P(回答有毒)，由分类模型输出",
        range=(0.0, 1.0),
        higher_is_better=False,
        requires_golden=False,
    ),
    "jailbreak": MetricDefinition(
        key="jailbreak",
        name="越狱检测",
        category=MetricCategory.SAFETY,
        metric_type=MetricType.RULE,
        definition="回答是否违反安全策略（输出违规内容）",
        formula="jailbreak = 1 if 回答包含违规内容 else 0",
        range=(0.0, 1.0),
        higher_is_better=False,
        requires_golden=False,
    ),

    # ---------- 5. 效率指标 ----------
    "latency_p95": MetricDefinition(
        key="latency_p95",
        name="P95 延迟(ms)",
        category=MetricCategory.EFFICIENCY,
        metric_type=MetricType.RULE,
        definition="95% 请求的响应时间上限",
        formula="latency_p95 = 第 95 百分位的响应时间",
        range=(0.0, float("inf")),
        higher_is_better=False,
        requires_golden=False,
    ),
    "tokens_per_request": MetricDefinition(
        key="tokens_per_request",
        name="单次 Token 消耗",
        category=MetricCategory.EFFICIENCY,
        metric_type=MetricType.RULE,
        definition="平均每次请求消耗的 Token 数（输入+输出）",
        formula="tokens = (input_tokens + output_tokens) / 请求数",
        range=(0.0, float("inf")),
        higher_is_better=False,
        requires_golden=False,
    ),
    "cost_per_request": MetricDefinition(
        key="cost_per_request",
        name="单次成本($)",
        category=MetricCategory.EFFICIENCY,
        metric_type=MetricType.RULE,
        definition="平均每次请求的费用",
        formula="cost = input_tokens * input_price + output_tokens * output_price",
        range=(0.0, float("inf")),
        higher_is_better=False,
        requires_golden=False,
    ),

    # ---------- 6. 格式校验指标 ----------
    "format_valid": MetricDefinition(
        key="format_valid",
        name="格式合规率",
        category=MetricCategory.FORMAT,
        metric_type=MetricType.RULE,
        definition="回答是否符合预期格式（JSON Schema 等）",
        formula="format_valid = 1 if 符合格式 else 0",
        range=(0.0, 1.0),
        requires_golden=False,
    ),
}


def get_metric(key: str) -> MetricDefinition:
    """获取单个指标定义"""
    if key not in METRICS:
        raise KeyError(f"未知指标: {key}，可用指标: {list(METRICS.keys())}")
    return METRICS[key]


def list_metrics() -> list[MetricDefinition]:
    """列出所有指标"""
    return list(METRICS.values())


def list_by_category(category: MetricCategory) -> list[MetricDefinition]:
    """按类别列出指标"""
    return [m for m in METRICS.values() if m.category == category]


if __name__ == "__main__":
    print(f"共定义 {len(METRICS)} 个指标\n")
    for cat in MetricCategory:
        ms = list_by_category(cat)
        print(f"【{cat.value}】({len(ms)} 个)")
        for m in ms:
            print(f"  - {m.key}: {m.name} [{m.metric_type.value}]")
        print()
