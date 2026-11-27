"""
用户反馈收集与 badcase 归类（Day 24）

反馈表只记录「好/差 + 原因 + 评论」，归类放在收集层做：
差评评论按关键词映射到 5 类问题，映射不到的统一进 other，不丢数据。
"""
from datetime import datetime, timedelta

CATEGORIES = {
    "hallucination": ("编造", "瞎说", "不存在", "没有依据", "胡编"),
    "irrelevant": ("答非所问", "没回答", "不相关", "答错了"),
    "incomplete": ("不完整", "漏了", "缺少", "没说完"),
    "format": ("格式", "看不懂", "乱码", "排版"),
    "tone": ("态度", "语气", "太生硬", "不礼貌"),
}


class BadcaseCollector:
    """从用户反馈中收集差评并自动归类"""

    CATEGORIES = CATEGORIES

    def classify(self, comment: str = "", reason: str = "") -> str:
        """评论 + 用户选择的原因一起匹配，返回 issue category"""
        text = "%s %s" % (reason or "", comment or "")
        for category, keywords in self.CATEGORIES.items():
            if any(keyword in text for keyword in keywords):
                return category
        return "other"

    def to_badcase(self, row) -> dict:
        """把一条反馈行转成 badcase（兼容 ORM 对象与 dict）"""
        get = row.get if isinstance(row, dict) else lambda key, default=None: getattr(row, key, default)
        comment = get("comment", "") or ""
        reason = get("reason", "") or ""
        category = get("issue_category", None) or self.classify(comment, reason)
        return {
            "feedback_id": get("id", None),
            "request_id": get("request_id", ""),
            "question": get("question", "") or "",
            "answer": get("answer", "") or "",
            "reason": reason,
            "comment": comment,
            "category": category,
            "biz_line": get("biz_line", None),
            "created_at": get("created_at", None),
        }

    def collect_from_rows(self, rows) -> list:
        """纯函数入口，便于测试与离线导入"""
        return [self.to_badcase(row) for row in rows]

    def collect_badcases(self, days: int = 7, db=None, now=None) -> list:
        """从反馈表收集近 N 天差评；未传 db 时使用默认会话"""
        if days <= 0:
            raise ValueError("days 必须大于 0")
        now = now or datetime.now()
        since = now - timedelta(days=days)

        own_session = db is None
        if own_session:
            from backend.database import SessionLocal

            db = SessionLocal()
        try:
            from backend.models.feedback import UserFeedback

            rows = (db.query(UserFeedback)
                    .filter(UserFeedback.rating == "bad",
                            UserFeedback.created_at >= since)
                    .order_by(UserFeedback.created_at.desc())
                    .all())
            return self.collect_from_rows(rows)
        finally:
            if own_session:
                db.close()
