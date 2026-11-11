"""
Prompt v1.0.0 — 初版（宽松约束）

变更说明：初版，无严格约束，仅提供基础角色设定。
基线分：62.5（模拟）
"""

VERSION = "v1.0.0"

SYSTEM_PROMPT = """你是一个企业客服助手。
请根据用户的问题给出回答。

参考资料：
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
        "temperature": 0.7,
        "top_p": 1.0,
        "max_tokens": 1024,
    }
