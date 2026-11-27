"""
灰度路由（Day 23）

按 user_id 稳定分流：同一用户永远命中同一版本，避免刷新页面就换答案。
用 MD5 取桶而不是 random，保证可复现、可回放。
"""
import hashlib
import os

DEFAULT_RATIO = 0.05


class PromptRouter:
    """按用户 ID 稳定分流到新/旧 Prompt 版本"""

    def __init__(self, new_version: str, ratio: float = DEFAULT_RATIO):
        if not new_version:
            raise ValueError("new_version 不能为空")
        if not 0 <= ratio <= 1:
            raise ValueError("ratio 必须在 [0, 1] 之间")
        self.new_version = new_version
        self.ratio = ratio

    def bucket(self, user_id: str) -> float:
        """返回 [0, 1) 的稳定分桶；没有 user_id 时视为稳定版用户"""
        if not user_id:
            return 1.0
        digest = hashlib.md5(user_id.encode("utf-8")).hexdigest()
        return (int(digest, 16) % 10000) / 10000.0

    def pick_version(self, user_id: str, stable_version: str) -> str:
        """命中灰度返回新版本，否则返回稳定版本"""
        return self.new_version if self.bucket(user_id) < self.ratio else stable_version

    @classmethod
    def from_env(cls):
        """从 GRAY_VERSION / GRAY_RATIO 构造；未配置灰度时返回 None"""
        version = os.getenv("GRAY_VERSION")
        if not version:
            return None
        return cls(version, float(os.getenv("GRAY_RATIO", DEFAULT_RATIO)))
