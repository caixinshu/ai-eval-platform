"""LLM Judge 单元测试（不依赖真实 API，覆盖解析/降级/偏差控制）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.llm_judge import LLMJudge, _parse_json
from evaluation.faithfulness_judge import FaithfulnessJudge, split_claims


def test_parse_json_with_fence():
    data = _parse_json('```json\n{"score": 4, "reason": "基本正确"}\n```')
    assert data["score"] == 4


def test_parse_json_with_noise():
    data = _parse_json('打分结果如下：{"score": 2, "reason": "遗漏"} 以上')
    assert data["reason"] == "遗漏"


def test_fallback_empty_answer():
    judge = LLMJudge(api_key="")
    r = judge.score("问题", "   ", "标准答案")
    assert judge.available is False
    assert r["source"] == "fallback"
    assert r["raw_score"] == 0


def test_position_bias_swap_to_tie():
    """模型总选第一个时，双向调用应判平局，避免位置偏差"""
    judge = LLMJudge(api_key="fake-key")
    judge._chat_json = lambda prompt: {"winner": "A"}
    r = judge.compare_pair("q", "回答一", "回答二")
    assert r["winner"] == "TIE"


def test_compare_consistent_winner():
    judge = LLMJudge(api_key="fake-key")
    answers = iter([{"winner": "A"}, {"winner": "B"}])
    judge._chat_json = lambda prompt: next(answers)
    r = judge.compare_pair("q", "更好的回答", "更差的回答")
    assert r["winner"] == "A"


def test_split_claims_filters_filler():
    claims = split_claims("您好，退款3-5个工作日到账。感谢您的咨询！祝您生活愉快。")
    assert claims == ["退款3-5个工作日到账"]


def test_faithfulness_rule_fallback():
    judge = FaithfulnessJudge(judge=LLMJudge(api_key=""))
    r = judge.evaluate(
        "退款会在审核通过后3-5个工作日原路退回。全场包邮且支持货到付款。",
        ["退款将在审核通过后 3-5 个工作日内原路退回支付账户。"],
    )
    assert r["source"] == "fallback"
    assert 0.0 < r["score"] < 1.0
    assert any("包邮" in c for c in r["unsupported"])


def test_faithfulness_empty_answer():
    judge = FaithfulnessJudge(judge=LLMJudge(api_key=""))
    r = judge.evaluate("", ["任意上下文"])
    assert r["score"] == 0.0
    assert r["source"] == "empty"
