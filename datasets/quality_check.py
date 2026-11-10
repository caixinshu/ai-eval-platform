"""
数据集质量检查工具 (Dataset Quality Check)
5 项检查：ID 唯一性、必填字段、难度一致性、数量达标、答案非范文。

用法:
  python datasets/quality_check.py                    # 全部检查
  python datasets/quality_check.py --check unique_ids  # 单项检查
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 数据集路径
DATASET_DIR = Path(__file__).parent
GOLDEN_FILE = DATASET_DIR / "golden_set.json"
ADVERSARIAL_FILE = DATASET_DIR / "adversarial_set.json"
EDGE_FILE = DATASET_DIR / "edge_set.json"
SCHEMA_FILE = DATASET_DIR / "schema.json"

# 数量要求
REQUIRED_COUNTS = {
    "golden": 50,
    "adversarial": 20,
    "edge": 15,
}


def load_json(path: Path) -> list:
    """加载 JSON 数据集"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all() -> dict[str, list]:
    """加载所有数据集"""
    return {
        "golden": load_json(GOLDEN_FILE),
        "adversarial": load_json(ADVERSARIAL_FILE),
        "edge": load_json(EDGE_FILE),
    }


# ==================== 检查项 ====================

def check_unique_ids(datasets: dict) -> dict:
    """检查 1：所有 ID 全局唯一"""
    all_ids = []
    for ds in datasets.values():
        all_ids.extend(item["id"] for item in ds)

    seen = set()
    duplicates = []
    for _id in all_ids:
        if _id in seen:
            duplicates.append(_id)
        seen.add(_id)

    return {
        "name": "ID 唯一性",
        "passed": len(duplicates) == 0,
        "detail": f"共 {len(all_ids)} 个 ID，重复 {len(duplicates)} 个: {duplicates[:5]}",
    }


def check_required_fields(datasets: dict) -> dict:
    """检查 2：必填字段完整性"""
    requirements = {
        "golden": ["id", "type", "category", "difficulty", "question", "ground_truth", "created_at"],
        "adversarial": ["id", "type", "category", "question", "expected_behavior", "assertion", "assertion_value", "created_at"],
        "edge": ["id", "type", "category", "question", "expected_behavior", "assertion", "assertion_value", "created_at"],
    }

    failures = []
    for ds_name, items in datasets.items():
        required = requirements.get(ds_name, [])
        for item in items:
            for field in required:
                val = item.get(field)
                # edge 集的空输入测试允许 question 为空或纯空白
                if ds_name == "edge" and field == "question" and isinstance(val, str) and val.strip() == "":
                    continue
                if val is None or (isinstance(val, str) and val.strip() == ""):
                    failures.append(f"{ds_name}/{item.get('id', '?')} 缺少字段 {field}")

    return {
        "name": "必填字段完整性",
        "passed": len(failures) == 0,
        "detail": f"缺失 {len(failures)} 处" + (f": {failures[:3]}" if failures else ""),
    }


def check_consistency(datasets: dict) -> dict:
    """检查 3：难度与答案长度一致性"""
    failures = []
    for item in datasets["golden"]:
        difficulty = item.get("difficulty", "")
        gt = item.get("ground_truth", "")
        gt_points = item.get("ground_truth_points", [])

        if difficulty == "hard" and len(gt_points) < 3:
            failures.append(f"{item['id']}: hard 难度但事实要点不足3个")
        if difficulty == "easy" and len(gt_points) > 4:
            failures.append(f"{item['id']}: easy 难度但事实要点过多")

    return {
        "name": "难度一致性",
        "passed": len(failures) == 0,
        "detail": f"不一致 {len(failures)} 处" + (f": {failures[:3]}" if failures else ""),
    }


def check_count(datasets: dict) -> dict:
    """检查 4：数量达标"""
    results = []
    all_passed = True
    for ds_name, required in REQUIRED_COUNTS.items():
        actual = len(datasets.get(ds_name, []))
        passed = actual >= required
        all_passed = all_passed and passed
        results.append(f"{ds_name}: {actual}/{required} {'✓' if passed else '✗'}")

    return {
        "name": "数量达标",
        "passed": all_passed,
        "detail": " | ".join(results),
    }


def check_ground_truth_length(datasets: dict) -> dict:
    """检查 5：ground_truth 非范文（长度 < 200 字）"""
    failures = []
    for item in datasets["golden"]:
        gt = item.get("ground_truth", "")
        if len(gt) > 200:
            failures.append(f"{item['id']}: ground_truth 长度 {len(gt)} > 200")

    return {
        "name": "答案非范文",
        "passed": len(failures) == 0,
        "detail": f"超字数 {len(failures)} 处" + (f": {failures[:3]}" if failures else ""),
    }


# ==================== 主流程 ====================

ALL_CHECKS = {
    "unique_ids": check_unique_ids,
    "required_fields": check_required_fields,
    "consistency": check_consistency,
    "count": check_count,
    "ground_truth_length": check_ground_truth_length,
}


def run_check(check_name: str = "all") -> int:
    """运行检查，返回退出码 (0=全通过, 1=有失败)"""
    datasets = load_all()

    if check_name == "all":
        checks = ALL_CHECKS
    else:
        if check_name not in ALL_CHECKS:
            print(f"未知检查项: {check_name}")
            print(f"可用: {list(ALL_CHECKS.keys())}")
            return 2
        checks = {check_name: ALL_CHECKS[check_name]}

    print(f"{'=' * 60}")
    print(f"  数据集质量检查 ({check_name})")
    print(f"{'=' * 60}")

    all_passed = True
    for name, check_fn in checks.items():
        result = check_fn(datasets)
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"  [{status}] {result['name']}: {result['detail']}")
        if not result["passed"]:
            all_passed = False

    print(f"{'=' * 60}")
    if all_passed:
        print("  全部检查通过！")
        return 0
    else:
        print("  存在未通过的检查项，请修复后重跑。")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据集质量检查")
    parser.add_argument("--check", default="all", choices=["all"] + list(ALL_CHECKS.keys()))
    args = parser.parse_args()
    sys.exit(run_check(args.check))
