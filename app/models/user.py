from sqlalchemy import Column, Integer, String, DateTime, Enum
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
    name = Column(String(100), nullable=True)
    current_day = Column(Integer, default=0)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    persona = Column(Enum(Persona), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    messages = relationship("Message", back_populates="user", order_by="Message.created_at.desc()")

    def __repr__(self):
        return f"<User(id={self.id}, line_user_id={self.line_user_id}, current_day={self.current_day})>"
