from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Date
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class PushLog(Base):
    """每日推送記錄表"""
    __tablename__ = "push_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 推送內容
    push_date = Column(Date, nullable=False, index=True)  # 推送日期
    training_day = Column(Integer, nullable=False)         # 推送的訓練天數
    push_message = Column(Text, nullable=False)            # 推送的訊息內容

    # 回覆狀態
    responded = Column(Boolean, default=False)             # 是否已回覆
    responded_at = Column(DateTime(timezone=True), nullable=True)  # 回覆時間

    # 時間戳記
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 關聯
    user = relationship("User", backref="push_logs")

    def __repr__(self):
        return f"<PushLog(id={self.id}, user_id={self.user_id}, date={self.push_date}, day={self.training_day}, responded={self.responded})>"
