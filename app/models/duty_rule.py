from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class DutyRule(Base):
    """排班規則（按星期幾指定人員，同一天可多人）"""
    __tablename__ = "duty_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_type = Column(String(20), nullable=False)   # 'duty' or 'leader'
    weekday = Column(Integer, nullable=False)         # 0=週一, 1=週二, ..., 6=週日
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
