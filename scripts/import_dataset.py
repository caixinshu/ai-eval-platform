"""
示例数据集导入（Day 20-21：一键启动的初始化步骤）

用法：
    python scripts/import_dataset.py eval_datasets/golden_set.json
    python scripts/import_dataset.py eval_datasets/edge_set.json --name 边界集 --type edge
    docker compose exec api python scripts/import_dataset.py eval_datasets/golden_set.json

幂等：数据集按「名称 + 类型」复用；用例按 id 去重，重复自动跳过。
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import SessionLocal, init_db
from backend.models.dataset import Dataset, TestCase
from backend.models.prompt import PromptVersion

TYPE_NAMES = {
    "golden": "黄金集",
    "edge": "边界集",
    "adversarial": "对抗集",
    "calibration": "校准集",
}

DEFAULT_PROMPT = (
    "你是客服助手。请仅基于提供的资料回答用户问题，"
    "资料中没有的信息要明确说明，不要编造。回答保持简洁。"
)


def load_cases(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases") or data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是数组，或包含 cases / items 数组的对象")
    return data


def infer_type(path: Path) -> str:
    for key in TYPE_NAMES:
        if key in path.name:
            return key
    return "golden"


def ensure_prompt(db, name: str, version: str) -> str:
    row = db.query(PromptVersion).filter_by(name=name).order_by(
        PromptVersion.created_at.desc()).first()
    if row is not None:
        return "%s @ %s" % (row.name, row.version)
    db.add(PromptVersion(id="pv_" + uuid.uuid4().hex[:12], name=name,
                         version=version, content=DEFAULT_PROMPT,
                         description="导入示例数据时自动创建"))
    db.commit()
    return "%s @ %s（已自动创建）" % (name, version)


def import_dataset(path: Path, name: str = None, dtype: str = None,
                   version: str = "v1", force: bool = False,
                   prompt_name: str = "客服问答",
                   prompt_version: str = "v1.0.0") -> dict:
    cases = load_cases(path)
    dtype = dtype or infer_type(path)
    name = name or TYPE_NAMES.get(dtype, "示例数据集")

    init_db()
    db = SessionLocal()
    try:
        dataset = db.query(Dataset).filter_by(name=name, type=dtype).first()
        if dataset is None:
            dataset = Dataset(id="ds_" + uuid.uuid4().hex[:12], name=name,
                              type=dtype, version=version, case_count=0,
                              description="由 %s 导入" % path.name)
            db.add(dataset)
            db.flush()
        elif force:
            db.query(TestCase).filter_by(dataset_id=dataset.id).delete()

        imported = skipped = 0
        for raw in cases:
            case_id = raw.get("id")
            question = raw.get("question")
            if not case_id or not question:
                skipped += 1
                continue
            if db.get(TestCase, case_id) is not None:
                skipped += 1
                continue
            db.add(TestCase(
                id=str(case_id)[:50],
                dataset_id=dataset.id,
                question=question,
                ground_truth=raw.get("ground_truth"),
                category=raw.get("category"),
                difficulty=raw.get("difficulty"),
                tags=raw.get("tags"),
                expected_behavior=raw.get("expected_behavior"),
                expected_context=raw.get("context"),
            ))
            imported += 1

        db.flush()
        dataset.case_count = db.query(TestCase).filter_by(
            dataset_id=dataset.id).count()
        db.commit()
        prompt = ensure_prompt(db, prompt_name, prompt_version)
        return {
            "dataset_id": dataset.id,
            "dataset": "%s @ %s" % (dataset.name, dataset.version),
            "type": dtype,
            "imported": imported,
            "skipped": skipped,
            "case_count": dataset.case_count,
            "prompt": prompt,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="导入示例数据集到评测平台")
    parser.add_argument("file", help="用例 JSON 路径，如 eval_datasets/golden_set.json")
    parser.add_argument("--name", help="数据集名称（默认按类型推断）")
    parser.add_argument("--type", dest="dtype", choices=sorted(TYPE_NAMES),
                        help="数据集类型（默认按文件名推断）")
    parser.add_argument("--version", default="v1", help="数据集版本，默认 v1")
    parser.add_argument("--force", action="store_true",
                        help="先清空该数据集已有用例再导入")
    parser.add_argument("--prompt-name", default="客服问答")
    parser.add_argument("--prompt-version", default="v1.0.0")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print("文件不存在: %s" % path)
        return 1

    result = import_dataset(path, name=args.name, dtype=args.dtype,
                            version=args.version, force=args.force,
                            prompt_name=args.prompt_name,
                            prompt_version=args.prompt_version)
    print("数据集：%s（%s）" % (result["dataset"], result["dataset_id"]))
    print("导入 %d 条，跳过 %d 条，当前共 %d 条"
          % (result["imported"], result["skipped"], result["case_count"]))
    print("Prompt 版本：%s" % result["prompt"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
