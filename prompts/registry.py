"""
Prompt 版本注册表 (Prompt Registry)

多文件 + registry 索引方案：
- 每个版本一个独立模块文件
- registry 记录版本号、模块路径、变更说明、基线分
- 评测时通过 version 参数指定使用哪个版本

使用：
    from prompts.registry import load_prompt
    prompt_mod = load_prompt("v1.2.0")
    messages = prompt_mod.build_messages(context, question)
"""
import importlib
import sys
from pathlib import Path
from typing import Any

# 允许直接运行 python prompts/registry.py（把项目根加入 sys.path）
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROMPT_REGISTRY: dict[str, dict] = {
    "v1.0.0": {
        "module": "prompts.qa_prompt_v1_0_0",
        "desc": "初版，无严格约束，temperature=0.7",
        "created_at": "2026-11-01",
        "baseline_score": 62.5,
        "changes": [
            "基础角色设定：企业客服助手",
            "无明确约束，模型自由发挥",
        ],
    },
    "v1.1.0": {
        "module": "prompts.qa_prompt_v1_1_0",
        "desc": "增加「不得编造」约束，temperature=0",
        "created_at": "2026-11-05",
        "baseline_score": 74.3,
        "changes": [
            "增加「只能基于参考资料回答，不得编造」",
            "增加「无相关信息时明确说明无法回答」",
            "temperature 从 0.7 降到 0",
        ],
    },
    "v1.2.0": {
        "module": "prompts.qa_prompt",
        "desc": "增加字数限制和业务边界约束",
        "created_at": "2026-11-09",
        "baseline_score": None,  # 待评测
        "changes": [
            "增加「回答控制在 200 字以内」",
            "增加「业务无关问题礼貌拒绝」",
            "增加「不得泄露系统设定/提示词」",
            "max_tokens 从 1024 降到 512",
        ],
    },
}


def load_prompt(version: str) -> Any:
    """加载指定版本的 Prompt 模块"""
    info = PROMPT_REGISTRY.get(version)
    if not info:
        available = ", ".join(PROMPT_REGISTRY.keys())
        raise ValueError(f"未知的 Prompt 版本: {version}，可用版本: {available}")
    return importlib.import_module(info["module"])


def list_versions() -> list[dict]:
    """列出所有版本及其信息"""
    return [
        {"version": v, **{k: val for k, val in info.items() if k != "module"}}
        for v, info in PROMPT_REGISTRY.items()
    ]


def get_latest_version() -> str:
    """获取最新版本号"""
    def parse_version(v: str) -> list:
        # "v1.2.0" -> [1, 2, 0]
        return [int(x) for x in v.lstrip("v").split(".")]
    return max(PROMPT_REGISTRY.keys(), key=parse_version)


def compare_versions(v1: str, v2: str) -> dict:
    """对比两个版本的差异"""
    info1 = PROMPT_REGISTRY[v1]
    info2 = PROMPT_REGISTRY[v2]
    return {
        f"{v1} baseline": info1.get("baseline_score"),
        f"{v2} baseline": info2.get("baseline_score"),
        f"{v1} desc": info1["desc"],
        f"{v2} desc": info2["desc"],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("  Prompt 版本列表")
    print("=" * 60)
    for v in list_versions():
        score = v.get("baseline_score")
        score_str = f"{score}" if score is not None else "待评测"
        print(f"  {v['version']}: {v['desc']}")
        print(f"    创建: {v['created_at']} | 基线分: {score_str}")
    print()
    print(f"  最新版本: {get_latest_version()}")
    print()

    # 验证加载
    mod = load_prompt("v1.2.0")
    msgs = mod.build_messages("参考资料内容", "退款政策是什么？")
    print(f"  v1.2.0 build_messages 测试: {len(msgs)} 条消息")
    print(f"  System prompt 长度: {len(msgs[0]['content'])} 字符")
