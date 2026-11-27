"""
灰度监控与自动回滚（Day 23）

灰度期间两版并行，任一核心指标越线就返回回滚建议：
- 在线评测分数：下降超过 3 分（与离线基线噪声阈值一致）
- 用户负反馈率：相对上涨超过 30%
- 拒答率：相对上涨超过 20%
- 延迟 P95：超过 3000ms
- Token 成本：相对上涨超过 30%

输入是同一时间窗内两版的聚合快照，字段：
    online_score           0-1
    negative_feedback_rate 0-1
    refusal_rate           0-1
    latency_p95_ms         毫秒
    token_cost             任意成本单位（两版口径需一致）
"""

GRAY_LIMITS = {
    "score_drop": 0.03,
    "negative_feedback_rise": 0.30,
    "refusal_rise": 0.20,
    "latency_p95_ms": 3000.0,
    "token_cost_rise": 0.30,
}

RATE_KEYS = ("online_score", "negative_feedback_rate", "refusal_rate")
REQUIRED_KEYS = ("online_score", "negative_feedback_rate", "refusal_rate",
                 "latency_p95_ms", "token_cost")


def _validate(snapshot: dict, name: str) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in snapshot]
    if missing:
        raise ValueError("%s 缺少指标: %s" % (name, ", ".join(missing)))
    for key in RATE_KEYS:
        value = snapshot[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("%s.%s 必须是数字" % (name, key))
        if not 0 <= value <= 1:
            raise ValueError("%s.%s 必须在 [0, 1] 之间" % (name, key))
    for key in ("latency_p95_ms", "token_cost"):
        value = snapshot[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError("%s.%s 必须是非负数字" % (name, key))


def _relative_rise(base: float, candidate: float):
    """相对涨幅；基数为 0 时只有候选大于 0 才算无穷大"""
    if base > 0:
        return (candidate - base) / base
    return 0.0 if candidate <= 0 else float("inf")


class GrayReleaseGuard:
    """根据两版快照判断是否需要回滚"""

    def __init__(self, limits: dict = None):
        self.limits = dict(GRAY_LIMITS)
        if limits:
            self.limits.update(limits)

    def evaluate(self, stable: dict, candidate: dict) -> dict:
        _validate(stable, "stable")
        _validate(candidate, "candidate")
        checks = []
        reasons = []

        # 1. 在线评测分数：看绝对下降
        drop = stable["online_score"] - candidate["online_score"]
        limit = self.limits["score_drop"]
        checks.append({
            "metric": "online_score", "stable": stable["online_score"],
            "candidate": candidate["online_score"],
            "delta": round(drop, 4), "limit": limit,
            "triggered": drop > limit,
        })
        if drop > limit:
            reasons.append("在线评测分数下降 %.3f（> %.3f）" % (drop, limit))

        # 2. 负反馈率 / 拒答率 / Token 成本：看相对上涨
        relative_rules = (
            ("negative_feedback_rate", "negative_feedback_rise", "用户负反馈率"),
            ("refusal_rate", "refusal_rise", "拒答率"),
            ("token_cost", "token_cost_rise", "Token 成本"),
        )
        for key, limit_key, label in relative_rules:
            rise = _relative_rise(stable[key], candidate[key])
            limit = self.limits[limit_key]
            checks.append({
                "metric": key, "stable": stable[key],
                "candidate": candidate[key],
                "delta_ratio": None if rise == float("inf") else round(rise, 4),
                "limit": limit, "triggered": rise > limit,
            })
            if rise > limit:
                rise_text = "∞" if rise == float("inf") else "%.1f%%" % (rise * 100)
                reasons.append("%s上涨 %s（> %.0f%%）" % (label, rise_text, limit * 100))

        # 3. 延迟：绝对上限
        latency_limit = self.limits["latency_p95_ms"]
        latency = candidate["latency_p95_ms"]
        checks.append({
            "metric": "latency_p95_ms", "stable": stable["latency_p95_ms"],
            "candidate": latency, "limit": latency_limit,
            "triggered": latency > latency_limit,
        })
        if latency > latency_limit:
            reasons.append("延迟 P95 %.0fms（> %.0fms）" % (latency, latency_limit))

        return {
            "rollback": bool(reasons),
            "reasons": reasons,
            "checks": checks,
        }
