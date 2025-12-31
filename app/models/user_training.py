from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class TrainingStatus(str, enum.Enum):
    """訓練狀態"""
    PENDING = "pending"      # 待開始（已加入但未開始）
    ACTIVE = "active"        # 進行中
    PAUSED = "paused"        # 已暫停
    COMPLETED = "completed"  # 已完成


class UserTraining(Base):
    """用戶訓練關聯資料表"""
    __tablename__ = "user_trainings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False, index=True)

    # 訓練進度
    current_day = Column(Integer, default=0)      # 當前天數
    current_round = Column(Integer, default=0)    # 當天對話輪數
    status = Column(String(20), default=TrainingStatus.PENDING.value)

    # 分類資訊（從原本 User 移過來）
    persona = Column(String(20), nullable=True)   # A_無經驗 / B_有經驗

    # 時間記錄
    started_at = Column(DateTime(timezone=True), nullable=True)    # 開始訓練時間
    paused_at = Column(DateTime(timezone=True), nullable=True)     # 暫停時間
    completed_at = Column(DateTime(timezone=True), nullable=True)  # 完成時間
    last_push_at = Column(DateTime(timezone=True), nullable=True)  # 最後推送時間

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    user = relationship("User", back_populates="trainings")
    batch = relationship("TrainingBatch", back_populates="user_trainings")

    def __repr__(self):
        return f"<UserTraining(user_id={self.user_id}, batch_id={self.batch_id}, day={self.current_day}, status={self.status})>"

    @property
    def status_enum(self) -> TrainingStatus:
        """取得狀態的 Enum 值"""
        return TrainingStatus(self.status) if self.status else TrainingStatus.PENDING

    @property
    def is_active(self) -> bool:
        """是否正在進行訓練"""
        return self.status == TrainingStatus.ACTIVE.value

    @property
    def is_completed(self) -> bool:
        """是否已完成訓練"""
        return self.status == TrainingStatus.COMPLETED.value
