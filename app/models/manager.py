from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base


class Manager(Base):
    """主管資料表（用於請假審核通知）"""
    __tablename__ = "managers"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)  # 主管姓名
    is_active = Column(Boolean, default=True)  # 是否啟用通知
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Manager(id={self.id}, name={self.name}, line_user_id={self.line_user_id})>"
