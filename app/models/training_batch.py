from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class TrainingBatch(Base):
    """訓練批次資料表"""
    __tablename__ = "training_batches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 批次名稱，例如: "2025年1月新人班"
    description = Column(Text, nullable=True)   # 批次說明
    course_version = Column(String(50), default="v1")  # 課程版本
    total_days = Column(Integer, default=14)    # 總訓練天數
    is_active = Column(Boolean, default=True)   # 是否啟用
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    user_trainings = relationship("UserTraining", back_populates="batch")

    def __repr__(self):
        return f"<TrainingBatch(id={self.id}, name={self.name}, version={self.course_version})>"
