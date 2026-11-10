"""
准确性指标计算 (Accuracy Metrics)
- accuracy: 准确率
- exact_match: 完全匹配率
- f1: F1 分数
"""
import re
import string
from collections import Counter


def _normalize(text: str) -> str:
    """文本归一化：小写、去标点、去多余空白"""
    text = text.lower().strip()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text)
    return text


def _tokenize(text: str) -> list[str]:
    """简单分词：按空白和标点切分"""
    return [t for t in re.split(r"[\s\W]+", text.lower()) if t]


def accuracy(predictions: list[str], golds: list[str]) -> float:
    """
    准确率：预测正确的比例。
    这里"正确"指归一化后与黄金答案完全一致。
    """
    if len(predictions) != len(golds):
        raise ValueError(f"长度不一致: predictions={len(predictions)}, golds={len(golds)}")
    if not predictions:
        return 0.0
    correct = sum(1 for p, g in zip(predictions, golds) if _normalize(p) == _normalize(g))
    return correct / len(predictions)


def exact_match(prediction: str, gold: str) -> float:
    """单条样本完全匹配：归一化后相等则 1，否则 0"""
    return 1.0 if _normalize(prediction) == _normalize(gold) else 0.0


def exact_match_batch(predictions: list[str], golds: list[str]) -> float:
    """批量完全匹配率"""
    if not predictions:
        return 0.0
    return sum(exact_match(p, g) for p, g in zip(predictions, golds)) / len(predictions)


def f1_score(prediction: str, gold: str) -> float:
    """
    单条样本 F1 分数（基于词元重叠）。
    F1 = 2 * (P * R) / (P + R)
    """
    pred_tokens = _tokenize(prediction)
    gold_tokens = _tokenize(gold)

    if not pred_tokens or not gold_tokens:
        return 1.0 if pred_tokens == gold_tokens else 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())

    if num_same == 0:
        return 0.0

    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def f1_score_batch(predictions: list[str], golds: list[str]) -> float:
    """批量 F1 分数的平均"""
    if not predictions:
        return 0.0
    return sum(f1_score(p, g) for p, g in zip(predictions, golds)) / len(predictions)


if __name__ == "__main__":
    # 自测
    preds = ["The capital of France is Paris", "Hello World", "Python is great"]
    golds = ["the capital of france is paris.", "hello, world!", "Python is awesome"]

    print(f"accuracy: {accuracy(preds, golds):.4f}")
    print(f"exact_match: {exact_match_batch(preds, golds):.4f}")
    print(f"f1: {f1_score_batch(preds, golds):.4f}")

    print("\n单条 F1 示例:")
    print(f"  'Paris' vs 'Paris' -> {f1_score('Paris', 'Paris'):.4f}")
    print(f"  'Paris is nice' vs 'Paris is great' -> {f1_score('Paris is nice', 'Paris is great'):.4f}")
