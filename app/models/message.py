from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Message(Base):
    """對話記錄表"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 訓練相關
    training_day = Column(Integer, nullable=False)  # 當時的訓練天數

    # 對話內容
    user_message = Column(Text, nullable=False)     # 用戶輸入的訊息
    ai_reply = Column(Text, nullable=False)         # AI 回覆的訊息

    # 評分結果
    passed = Column(Boolean, default=False)         # 是否通過
    score = Column(Integer, default=0)              # 分數 (0-100)
    reason = Column(Text, nullable=True)            # 評分原因

    # 時間戳記
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 關聯
    user = relationship("User", back_populates="messages")

    def __repr__(self):
        return f"<Message(id={self.id}, user_id={self.user_id}, day={self.training_day}, passed={self.passed})>"
