from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class UserStatus(str, enum.Enum):
    """用戶狀態"""
    ACTIVE = "Active"
    INACTIVE = "Inactive"


class Persona(str, enum.Enum):
    """用戶類別（經驗程度）"""
    A_NO_EXPERIENCE = "A_無經驗"      # 無經驗：保守、警戒心強
    B_HAS_EXPERIENCE = "B_有經驗"     # 有經驗：做過制服/禮服店


class User(Base):
    """用戶資料表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, index=True, nullable=False)
    line_display_name = Column(String(100), nullable=True)  # LINE 顯示名稱
    line_picture_url = Column(String(500), nullable=True)   # LINE 大頭貼
    real_name = Column(String(100), nullable=True)          # 本名
    name = Column(String(100), nullable=True)               # 舊欄位，保留相容性
    current_day = Column(Integer, default=0)
    current_round = Column(Integer, default=0)  # 當天訓練的對話輪數
    status = Column(String(20), default=UserStatus.ACTIVE.value)
    persona = Column(String(20), nullable=True)
    notification_enabled = Column(Boolean, default=True)  # 是否接收課程通知
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    messages = relationship("Message", back_populates="user", order_by="Message.created_at.desc()")
    trainings = relationship("UserTraining", back_populates="user", order_by="UserTraining.created_at.desc()")
    leave_requests = relationship("LeaveRequest", back_populates="user", order_by="LeaveRequest.created_at.desc()")

    def __repr__(self):
        return f"<User(id={self.id}, line_user_id={self.line_user_id}, current_day={self.current_day})>"

    @property
    def status_enum(self) -> UserStatus:
        """取得狀態的 Enum 值"""
        return UserStatus(self.status) if self.status else UserStatus.ACTIVE

    @property
    def persona_enum(self) -> Persona | None:
        """取得 Persona 的 Enum 值"""
        return Persona(self.persona) if self.persona else None

    @property
    def active_training(self):
        """取得目前進行中的訓練"""
        for training in self.trainings:
            if training.status == "active":
                return training
        return None

    @property
    def display_name(self) -> str:
        """取得顯示名稱（優先 LINE 名稱）"""
        return self.line_display_name or self.real_name or self.name or "未命名"
