"""RAG 分段评测器单元测试（归因矩阵、指标计算；用桩替代 Embedding 模型）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluation.rag_evaluator as rag


def test_diagnose_four_quadrants():
    assert rag.diagnose(0.9, 0.9)["diagnosis"] == "检索准、生成稳"
    assert rag.diagnose(0.2, 0.9)["diagnosis"] == "漏召回，但模型诚实"
    assert rag.diagnose(0.9, 0.2)["diagnosis"] == "召回了却没用上"
    assert rag.diagnose(0.2, 0.2)["diagnosis"] == "检索和生成都有问题"


def test_diagnose_direction():
    assert "Rerank" in rag.diagnose(0.1, 0.9)["direction"]
    assert "Prompt" in rag.diagnose(0.9, 0.1)["direction"]


def test_context_precision(monkeypatch):
    monkeypatch.setattr(rag, "semantic_similarity", lambda a, b: 1.0 if "退款" in a else 0.1)
    assert rag.eval_context_precision(["退款政策说明", "无关内容"], "退款") == 0.5
    assert rag.eval_context_precision([], "退款") == 0.0


def test_context_recall(monkeypatch):
    monkeypatch.setattr(rag, "semantic_similarity", lambda a, b: 1.0 if "退款" in a else 0.1)
    assert rag.eval_context_recall(["退款政策说明"], ["退款条款"]) == 1.0
    assert rag.eval_context_recall(["无关内容"], ["退款条款"]) == 0.0
    assert rag.eval_context_recall([], []) == 1.0


def test_aggregate_quadrant_distribution():
    scores = [
        {"case_id": "a", "category": "x", "context_precision": 0.5,
         "context_recall": 0.9, "faithfulness": 0.9, "answer_relevancy": 0.5},
        {"case_id": "b", "category": "x", "context_precision": 0.5,
         "context_recall": 0.1, "faithfulness": 0.9, "answer_relevancy": 0.5},
    ]
    agg = rag.aggregate(scores)
    assert agg["case_count"] == 2
    assert agg["metrics"]["context_recall"] == 0.5
    dist = agg["quadrant_distribution"]
    assert dist["高召回 × 高忠实"]["case_ids"] == ["a"]
    assert dist["低召回 × 高忠实"]["case_ids"] == ["b"]


def test_weakest_metric():
    scores = [{"case_id": "a", "category": "x", "context_precision": 0.2,
               "context_recall": 0.8, "faithfulness": 0.9, "answer_relevancy": 0.6}]
    assert rag.aggregate(scores)["weakest_metric"] == "context_precision"
