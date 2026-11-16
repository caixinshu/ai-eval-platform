"""
忠实度 Judge：把答案拆成原子论断，逐条核查是否有上下文依据

为什么拆论断：直接问「答案是否忠于上下文」，模型往往给笼统好评；
拆成论断后必须逐条核查，幻觉无处可藏，且拆解结果本身就是 badcase 材料。

无 LLM_API_KEY 时降级为「中文二元组覆盖率」规则核查，结果标记 source=fallback。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.llm_judge import LLMJudge

FAITHFULNESS_PROMPT = """你是一个事实核查员。

请判断「答案」中的每一条事实性论断，是否能在「参考资料」中找到依据。

参考资料：
{context}

答案：
{answer}

步骤：
1. 把答案拆解为独立的事实性论断（忽略客套话、过渡句）
2. 逐条判断该论断能否被参考资料支撑
3. 输出 JSON

只输出 JSON：
{{"claims": [{{"claim": "论断", "supported": true/false}}], "faithful_count": n, "total_count": m}}"""

# 客套话/过渡句前缀，拆解论断时先剥离（不能整句丢弃，否则会误杀真实信息）
FILLER = ("您好", "感谢您的咨询", "感谢您", "很高兴为您服务", "请问还有什么",
          "希望对您有帮助", "祝您", "如有疑问", "欢迎咨询", "谢谢")


def split_claims(answer: str) -> list:
    """把答案拆成原子论断：按句切分，剥离客套前缀，丢弃过短片段"""
    parts = re.split(r"[。！？；\n]", answer or "")
    claims = []
    for p in parts:
        c = p.strip(" ，,、.。!！?？")
        for f in FILLER:
            if c.startswith(f):
                c = c[len(f):].lstrip("，,、 ")
        if len(c) < 6:
            continue
        claims.append(c)
    return claims


def _bigrams(text: str) -> set:
    chars = re.sub(r"\s+", "", text)
    return {chars[i:i + 2] for i in range(len(chars) - 1)} if len(chars) > 1 else set()


def _supported_by_rules(claim: str, context_text: str, threshold: float = 0.4) -> bool:
    """降级核查：论断的中文二元组有多大比例出现在上下文中"""
    claim_bg = _bigrams(claim)
    if not claim_bg:
        return False
    hit = sum(1 for bg in claim_bg if bg in context_text)
    return hit / len(claim_bg) >= threshold


class FaithfulnessJudge:
    def __init__(self, judge: LLMJudge = None):
        self.judge = judge or LLMJudge()

    def evaluate(self, answer: str, contexts: list) -> dict:
        context_text = "\n---\n".join(contexts or [])

        if not answer or not answer.strip():
            return {"score": 0.0, "claims": [], "unsupported": [], "source": "empty"}

        if self.judge.available:
            return self._evaluate_with_llm(answer, context_text)
        return self._evaluate_with_rules(answer, context_text)

    def _evaluate_with_llm(self, answer: str, context_text: str) -> dict:
        try:
            data = self.judge._chat_json(
                FAITHFULNESS_PROMPT.format(context=context_text, answer=answer))
            claims = [{"claim": c.get("claim", ""), "supported": bool(c.get("supported"))}
                      for c in data.get("claims", [])]
            total = data.get("total_count", len(claims))
            faithful = data.get("faithful_count",
                                sum(1 for c in claims if c["supported"]))
            return {
                "score": round(faithful / total, 4) if total else 1.0,
                "claims": claims,
                "unsupported": [c["claim"] for c in claims if not c["supported"]],
                "source": "llm",
            }
        except Exception as e:
            return {"score": 0.0, "claims": [], "unsupported": [],
                    "source": "llm", "error": "解析失败:%s" % e}

    def _evaluate_with_rules(self, answer: str, context_text: str) -> dict:
        claims = split_claims(answer)
        if not claims:
            return {"score": 1.0, "claims": [], "unsupported": [], "source": "fallback"}

        results = [{"claim": c, "supported": _supported_by_rules(c, context_text)}
                   for c in claims]
        faithful = sum(1 for r in results if r["supported"])
        return {
            "score": round(faithful / len(results), 4),
            "claims": results,
            "unsupported": [r["claim"] for r in results if not r["supported"]],
            "source": "fallback",
        }


_default_judge = None


def judge_faithfulness(answer: str, contexts: list) -> dict:
    """模块级入口（单例）"""
    global _default_judge
    if _default_judge is None:
        _default_judge = FaithfulnessJudge()
    return _default_judge.evaluate(answer, contexts)


if __name__ == "__main__":
    ctx = ["退款将在审核通过后 3-5 个工作日内原路退回支付账户。",
           "非质量问题退货的运费由用户承担。"]
    ans = "退款会在审核通过后3-5个工作日原路退回。另外我们承诺全场包邮且支持货到付款。"
    print("拆解论断:", split_claims(ans))
    print(judge_faithfulness(ans, ctx))
