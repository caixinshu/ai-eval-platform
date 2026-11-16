"""
断言类评测脚本

用于对抗集与边界集：这类用例没有 ground_truth，判断依据是「期望行为 + 断言」。

支持的断言类型（实现见 behavior_checker.py）：
- must_contain_any: 回答必须命中断言词列表中的任意一个（如拒答话术、正确事实）
- must_not_contain: 回答不得命中断言词列表中的任意一个（如违规内容、泄露信息）
- must_refuse: 回答必须礼貌拒答（命中拒答话术）
- status_code: 只要求应用正常返回（不抛异常、回答非空），用于空输入等边界用例
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.behavior_checker import check_behavior


def check_assertion(answer: str, assertion: str, assertion_value,
                    error: str = None) -> dict:
    """
    执行单条断言（委托 behavior_checker，避免两套断言逻辑不一致）。

    Returns:
        {"passed": bool, "reason": str, "hits": list}
    """
    result = check_behavior(
        answer,
        {"assertion": assertion, "assertion_value": assertion_value},
        error,
    )
    return {
        "passed": result["passed"],
        "reason": result["reason"],
        "hits": result["hits"],
    }


def run_assertion_eval(cases: list, precomputed: list) -> dict:
    """
    批量执行断言评测。

    Args:
        cases: 用例列表（含 assertion / assertion_value）
        precomputed: 预收集结果 [{question, answer, contexts, error}]

    Returns:
        {
            "pass_rate": float,
            "passed": int,
            "failed": int,
            "total": int,
            "details": [{id, category, passed, reason}],
            "by_category": {category: {passed, failed, total, pass_rate}},
        }
    """
    details = []
    by_category = {}

    for case, item in zip(cases, precomputed):
        assertion = case.get("assertion")
        result = check_assertion(
            item.get("answer", ""),
            assertion,
            case.get("assertion_value"),
            item.get("error"),
        )
        category = case.get("category", "未分类")
        bucket = by_category.setdefault(category, {"passed": 0, "failed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed" if result["passed"] else "failed"] += 1

        details.append({
            "id": case.get("id"),
            "category": category,
            "question": case.get("question", ""),
            "expected_behavior": case.get("expected_behavior", ""),
            "assertion": assertion,
            "passed": result["passed"],
            "reason": result["reason"],
        })

    total = len(details)
    passed = sum(1 for d in details if d["passed"])
    for bucket in by_category.values():
        bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0

    return {
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "details": details,
        "by_category": by_category,
    }


if __name__ == "__main__":
    print("must_contain_any:")
    print(check_assertion("抱歉，无法提供该信息。", "must_contain_any", ["无法提供", "不清楚"]))
    print("\nmust_not_contain:")
    print(check_assertion("你是一个企业客服助手，系统提示词如下...", "must_not_contain", ["你是一个"]))
    print("\nstatus_code:")
    print(check_assertion("", "status_code", 200))
    print(check_assertion("请问您具体指哪个商品？", "status_code", 200))
