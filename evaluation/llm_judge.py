"""
LLM-as-Judge：用大模型作为裁判做单维度打分

设计要点：
- 每次只评一个维度（correctness），多维度混评会互相干扰
- 0-5 分 rubric 写死，禁止模型自由发挥
- 强制 JSON 输出，便于程序解析
- 偏差控制：位置随机（compare_pair 双向取平均）、长度不计入、格式不影响、Judge 与生成模型分离

无 LLM_API_KEY 时自动降级为「语义相似度映射 0-5 分」，结果标记 source=fallback，
降级分不能当真实 Judge 结论使用（否定句/数字陷阱会误判）。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-4o-mini")

SCORE_RUBRIC = """请根据以下标准给「待评答案」打分（0-5 分）：

5 分：完全正确，事实准确，与标准答案一致
4 分：基本正确，仅措辞或细节表述有微小差异
3 分：部分正确，覆盖了部分要点但有遗漏
2 分：勉强相关，包含错误信息或严重遗漏
1 分：基本不相关，答非所问
0 分：完全错误或拒绝回答

注意：
- 答案长短、客套话多少不计入评分，只看事实是否正确
- Markdown 排版、分点还是成段不影响评分

只输出 JSON，不要任何解释文字。
格式：{"score": <0-5>, "reason": "<30字以内理由>"}"""

COMPARE_PROMPT = """请比较两个回答哪个更好回答用户问题。

问题：{question}

回答 A：
{answer_a}

回答 B：
{answer_b}

只输出 JSON：{{"winner": "A" 或 "B" 或 "TIE", "reason": "<20字以内>"}}"""


class LLMJudge:
    """LLM 裁判：单维度打分 + 对比（含位置偏差控制）"""

    def __init__(self, model: str = None, api_key: str = None, base_url: str = None):
        self.model = model or JUDGE_MODEL
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        from openai import OpenAI
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def _chat_json(self, prompt: str) -> dict:
        resp = self._get_client().chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return _parse_json(resp.choices[0].message.content)

    # ---- 单维度打分 ----
    def score(self, question: str, answer: str, ground_truth: str) -> dict:
        if not self.available:
            return self._fallback_score(answer, ground_truth)

        prompt = "问题：%s\n\n标准答案：%s\n\n待评答案：%s\n\n%s" % (
            question, ground_truth, answer, SCORE_RUBRIC)
        try:
            data = self._chat_json(prompt)
            raw = max(0, min(5, int(data.get("score", 0))))
            return {
                "score": raw / 5.0,
                "raw_score": raw,
                "reason": data.get("reason", ""),
                "source": "llm",
            }
        except Exception as e:
            return {"score": 0.0, "raw_score": 0, "reason": "解析失败:%s" % e,
                    "source": "llm"}

    # ---- 对比打分（位置偏差控制：双向调用取平均）----
    def compare_pair(self, question: str, answer_a: str, answer_b: str) -> dict:
        if not self.available:
            return self._fallback_compare(question, answer_a, answer_b)

        try:
            first = self._chat_json(COMPARE_PROMPT.format(
                question=question, answer_a=answer_a, answer_b=answer_b)).get("winner", "TIE")
            second = self._chat_json(COMPARE_PROMPT.format(
                question=question, answer_a=answer_b, answer_b=answer_a)).get("winner", "TIE")
        except Exception as e:
            return {"winner": "TIE", "reason": "调用失败:%s" % e, "source": "llm"}

        # 第二次的 A/B 是交换过的，映射回原始位置
        second = {"A": "B", "B": "A"}.get(second, second)
        if first == second and first in ("A", "B"):
            winner = first
        else:
            winner = "TIE"  # 两次不一致视为平局，避免位置偏好
        return {"winner": winner, "first": first, "swapped": second,
                "reason": "双向一致" if winner != "TIE" else "双向不一致，取平局",
                "source": "llm"}

    # ---- 降级实现 ----
    def _fallback_score(self, answer: str, ground_truth: str) -> dict:
        from evaluation.semantic_evaluator import semantic_similarity

        if not answer or not answer.strip():
            return {"score": 0.0, "raw_score": 0, "reason": "空答案",
                    "source": "fallback", "similarity": 0.0}
        sim = semantic_similarity(answer, ground_truth)
        if sim >= 0.93:
            raw = 5
        elif sim >= 0.87:
            raw = 4
        elif sim >= 0.80:
            raw = 3
        elif sim >= 0.70:
            raw = 2
        else:
            raw = 1
        return {"score": raw / 5.0, "raw_score": raw,
                "reason": "降级:相似度%.2f" % sim,
                "source": "fallback", "similarity": round(sim, 4)}

    def _fallback_compare(self, question: str, answer_a: str, answer_b: str) -> dict:
        from evaluation.semantic_evaluator import semantic_similarity

        sa = semantic_similarity(answer_a, question)
        sb = semantic_similarity(answer_b, question)
        if abs(sa - sb) < 0.01:
            winner = "TIE"
        else:
            winner = "A" if sa > sb else "B"
        return {"winner": winner, "reason": "降级:与问题相似度比较",
                "source": "fallback", "sim_a": round(sa, 4), "sim_b": round(sb, 4)}


def _parse_json(content: str) -> dict:
    """解析模型输出：容忍 ```json 包裹和前后杂字"""
    if not content:
        raise ValueError("空响应")
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


_default_judge = None


def judge_correctness(question: str, answer: str, ground_truth: str) -> dict:
    """模块级入口（单例），保持与执行计划一致的调用方式"""
    global _default_judge
    if _default_judge is None:
        _default_judge = LLMJudge()
    return _default_judge.score(question, answer, ground_truth)


if __name__ == "__main__":
    j = LLMJudge()
    print("judge 可用:", j.available, "| 模型:", j.model)
    print(j.score("退款多久到账", "退款审核通过后3-5个工作日到账",
                  "退款审核通过后3-5个工作日内原路退回"))
    print(_parse_json('```json\n{"score": 4, "reason": "基本正确"}\n```'))
