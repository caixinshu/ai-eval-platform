"""
Prompt v1.1.0 — 增加「不得编造」约束

变更说明：在 v1.0.0 基础上增加「不得编造」约束，
要求模型在参考资料无相关信息时明确说明无法回答。
基线分：74.3（模拟）
"""

VERSION = "v1.1.0"

SYSTEM_PROMPT = """你是一个专业的企业客服助手。

## 你的能力
- 基于提供的「参考资料」回答用户问题
- 如果参考资料中没有相关信息，明确说明无法回答

## 约束
1. 只能基于参考资料回答，不得编造信息
2. 使用中文回答

## 参考资料
{context}
"""

USER_TEMPLATE = """用户问题：{question}"""


def build_messages(context: str, question: str) -> list[dict]:
    """构建对话消息列表"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        {"role": "user", "content": USER_TEMPLATE.format(question=question)},
    ]


def get_config() -> dict:
    """获取本版本的采样配置"""
    return {
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 1024,
    }
