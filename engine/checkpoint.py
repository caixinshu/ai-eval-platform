"""
断点续跑：记录已完成用例，中断后重跑自动跳过

特点：
- 按 run_id 分文件，不同评测任务互不干扰
- 原子写（临时文件 + os.replace），避免进程中断时写坏 json
"""
import json
import os


class Checkpoint:
    """记录已完成的任务，支持中断后继续"""

    def __init__(self, run_id: str, path: str = ".cache/checkpoints"):
        os.makedirs(path, exist_ok=True)
        self.run_id = run_id
        self.file = os.path.join(path, run_id + ".json")
        self.done = set()
        self._load()

    def _load(self):
        if os.path.exists(self.file):
            try:
                with open(self.file, encoding="utf-8") as f:
                    self.done = set(json.load(f).get("done", []))
            except (json.JSONDecodeError, OSError):
                # 文件损坏则从头开始，不阻塞评测
                self.done = set()

    def mark_done(self, case_id: str):
        self.done.add(case_id)
        self._save()

    def _save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id, "done": sorted(self.done)}, f,
                      ensure_ascii=False)
        os.replace(tmp, self.file)

    def is_done(self, case_id: str) -> bool:
        return case_id in self.done

    @property
    def count(self) -> int:
        return len(self.done)
