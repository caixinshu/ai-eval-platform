"""
线上请求抽样评测（Day 24）

线上流量不可全量评测，只能抽样；抽样要满足两件事：
1. 成本可控：采样率 + 每小时硬上限，突发流量不会把评测队列打爆
2. 结果可复现：按 request_id 哈希取桶，不是 random，重放同一请求结论一致
"""
import hashlib
import os
import threading


class OnlineSampler:
    """线上请求抽样：稳定哈希 + 小时限流"""

    def __init__(self, sample_rate: float = 0.02, max_per_hour: int = 200):
        if not 0 <= sample_rate <= 1:
            raise ValueError("sample_rate 必须在 [0, 1] 之间")
        if max_per_hour < 0:
            raise ValueError("max_per_hour 不能为负")
        self.sample_rate = sample_rate
        self.max_per_hour = max_per_hour
        self.hour_count = 0
        self.current_hour = None
        self._lock = threading.Lock()

    def should_sample(self, request_id: str, hour_key: str) -> bool:
        """是否采样；同一 request_id 在同一小时桶内结果稳定"""
        if not request_id:
            return False

        with self._lock:
            # 跨小时先把计数归零，限流只约束当前小时
            if hour_key != self.current_hour:
                self.current_hour = hour_key
                self.hour_count = 0
            if self.hour_count >= self.max_per_hour:
                return False

            digest = hashlib.md5(request_id.encode("utf-8")).hexdigest()
            if (int(digest, 16) % 10000) / 10000.0 < self.sample_rate:
                self.hour_count += 1
                return True
            return False

    @classmethod
    def from_env(cls):
        """从 ONLINE_SAMPLE_RATE / ONLINE_SAMPLE_MAX_PER_HOUR 构造"""
        return cls(
            float(os.getenv("ONLINE_SAMPLE_RATE", "0.02")),
            int(os.getenv("ONLINE_SAMPLE_MAX_PER_HOUR", "200")),
        )
