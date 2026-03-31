"""早會登記暨日報表模型"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class MorningReport(Base):
    """早會日報表（每人每天一筆，填了就代表出席）"""
    __tablename__ = "morning_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    report_date = Column(Date, nullable=False, index=True)
    leader_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 所屬組長（冗餘存儲方便查詢）

    # 早會出勤（填了這筆就代表出席）
    meeting_time = Column(String(20), nullable=True)  # 早會時間 "05:00-05:20"

    # 昨日工作檢討
    review_category = Column(String(50), nullable=True)   # 檢討類別
    review_description = Column(Text, nullable=True)       # 發生狀況描述
    review_impact = Column(String(10), nullable=True)      # 影響程度：高/中/低
    review_solution = Column(Text, nullable=True)          # 改善對策
    review_responsible = Column(String(100), nullable=True) # 負責人（手動輸入）
    review_deadline = Column(Date, nullable=True)          # 預計完成日
    review_status = Column(String(20), default="未處理")    # 完成狀態：未處理/進行中/已改善

    # 經驗分享（下午五點填寫）
    share_category = Column(String(50), nullable=True)    # 案例類型
    share_situation = Column(Text, nullable=True)          # 遇到的狀況
    share_solution = Column(Text, nullable=True)           # 解決方法
    share_lesson = Column(Text, nullable=True)             # 學習重點
    share_scenario = Column(String(200), nullable=True)    # 適用場景
    share_rating = Column(Integer, nullable=True)          # 成效評分 1-5
    share_note = Column(Text, nullable=True)               # 備註

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", foreign_keys=[user_id], backref="morning_reports")
    leader = relationship("User", foreign_keys=[leader_id])

    @property
    def review_status_display(self):
        return self.review_status or "未處理"

    def __repr__(self):
        return f"<MorningReport(id={self.id}, user_id={self.user_id}, date={self.report_date})>"
