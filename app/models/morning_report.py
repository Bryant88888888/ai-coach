"""早會登記暨日報表模型"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import json


class MorningReport(Base):
    """早會日報表（每人每天一筆，填了就代表出席）"""
    __tablename__ = "morning_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    report_date = Column(Date, nullable=False, index=True)
    leader_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # 昨日工作檢討（JSON array，支援多筆）
    # 格式: [{"category":"客戶投訴","description":"...","impact":"高","solution":"...","responsible":"...","deadline":"2026-04-05","status":"進行中"}, ...]
    reviews = Column(Text, nullable=True)

    # 經驗分享（JSON array，支援多筆）
    # 格式: [{"category":"客訴處理","situation":"...","solution":"...","lesson":"...","scenario":"...","rating":5,"note":"..."}, ...]
    shares = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", foreign_keys=[user_id], backref="morning_reports")
    leader = relationship("User", foreign_keys=[leader_id])

    def get_reviews(self) -> list[dict]:
        if not self.reviews:
            return []
        try:
            return json.loads(self.reviews)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_reviews(self, items: list[dict]):
        self.reviews = json.dumps(items, ensure_ascii=False) if items else None

    def get_shares(self) -> list[dict]:
        if not self.shares:
            return []
        try:
            return json.loads(self.shares)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_shares(self, items: list[dict]):
        self.shares = json.dumps(items, ensure_ascii=False) if items else None

    @property
    def review_count(self):
        return len(self.get_reviews())

    @property
    def share_count(self):
        return len(self.get_shares())

    def __repr__(self):
        return f"<MorningReport(id={self.id}, user_id={self.user_id}, date={self.report_date})>"
