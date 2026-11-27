"""
线上 badcase 回流评测集（Day 24）

回流不是「把差评全塞进回归集」：
1. 聚类去重：同一问题的不同表达只留一个代表
2. 频次门槛：至少出现 min_count 次才回流，过滤一次性噪声
3. 默认 verified=false：线上问题的正确答案往往不明确，必须人工补 ground_truth
4. 未验证用例不参与门禁；run_eval.py 会跳过 verified=false 的用例
"""
import json
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path


def _question_key(question: str) -> str:
    """归一化问题作为聚类 key：去空白与标点，截断超长文本"""
    normalized = re.sub(r"[\s\W_]+", "", (question or "").lower())
    return normalized[:30]


def load_cases(path: str) -> list:
    file = Path(path)
    if not file.exists():
        return []
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("cases", [])
    if not isinstance(data, list):
        raise ValueError("评测集应为数组或 {cases: [...]}: %s" % path)
    return data


def save_cases(path: str, cases: list) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)


def reflow_cases(badcases: list, existing: list = None,
                 min_count: int = 3, now: datetime = None) -> list:
    """把 badcase 转成待标注用例；只返回本次新增的部分"""
    now = now or datetime.now()
    existing = existing or []
    seen = {_question_key(case.get("question")) for case in existing}

    counts = Counter(
        _question_key(item.get("question")) for item in badcases
        if _question_key(item.get("question"))
    )

    cases = []
    for item in badcases:
        question = (item.get("question") or "").strip()
        key = _question_key(question)
        if not key or key in seen:
            continue
        if counts[key] < min_count:
            continue
        seen.add(key)
        cases.append({
            "id": "fresh_%s" % uuid.uuid4().hex[:8],
            "type": "fresh",
            "category": item.get("category") or "other",
            "question": question,
            "ground_truth": None,
            "source": "online_badcase",
            "source_request_id": item.get("request_id"),
            "expected_behavior": {"reason": item.get("reason") or ""},
            "created_at": now.strftime("%Y-%m-%d"),
            "verified": False,
        })
    return cases


def merge_into_file(path: str, new_cases: list) -> list:
    """追加到评测集文件，按问题去重，返回实际新增的用例"""
    existing = load_cases(path)
    seen = {_question_key(case.get("question")) for case in existing}
    added = []
    for case in new_cases:
        key = _question_key(case.get("question"))
        if not key or key in seen:
            continue
        seen.add(key)
        added.append(case)
    if added:
        save_cases(path, existing + added)
    return added


def verify_case(path: str, case_id: str, ground_truth: str,
                category: str = None, now: datetime = None) -> dict:
    """人工确认：补 ground_truth 后把 verified 置为 true"""
    ground_truth = (ground_truth or "").strip()
    if not ground_truth:
        raise ValueError("ground_truth 不能为空，未标注的 badcase 不能进回归集")

    cases = load_cases(path)
    target = next((case for case in cases if case.get("id") == case_id), None)
    if target is None:
        raise KeyError("用例不存在: %s" % case_id)

    target["ground_truth"] = ground_truth
    target["verified"] = True
    target["verified_at"] = (now or datetime.now()).isoformat(timespec="seconds")
    if category:
        target["category"] = category
    save_cases(path, cases)
    return target


def stats(cases: list) -> dict:
    """回流进度：总量 / 待标注 / 已入集，以及各问题分类明细"""
    by_category = {}
    pending = verified = 0
    for case in cases:
        category = case.get("category") or "other"
        bucket = by_category.setdefault(
            category, {"total": 0, "pending": 0, "verified": 0})
        bucket["total"] += 1
        if case.get("verified") is True:
            bucket["verified"] += 1
            verified += 1
        else:
            bucket["pending"] += 1
            pending += 1

    return {
        "total": len(cases),
        "pending": pending,
        "verified": verified,
        "by_category": dict(sorted(
            by_category.items(), key=lambda kv: -kv[1]["total"])),
    }
