"""数据集包"""
import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent


def load_golden() -> list:
    """加载黄金集"""
    with open(_DATA_DIR / "golden_set.json", encoding="utf-8") as f:
        return json.load(f)


def load_adversarial() -> list:
    """加载对抗集"""
    with open(_DATA_DIR / "adversarial_set.json", encoding="utf-8") as f:
        return json.load(f)


def load_edge() -> list:
    """加载边界集"""
    with open(_DATA_DIR / "edge_set.json", encoding="utf-8") as f:
        return json.load(f)
