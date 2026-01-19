from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class DutyScheduleStatus(str, enum.Enum):
    """值日排班狀態"""
    SCHEDULED = "scheduled"  # 已排班
    REPORTED = "reported"    # 已回報
    APPROVED = "approved"    # 已審核通過
    REJECTED = "rejected"    # 審核未通過
    MISSED = "missed"        # 未完成


class DutySchedule(Base):
    """值日排班表"""
    __tablename__ = "duty_schedules"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("duty_configs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    duty_date = Column(Date, nullable=False, index=True)  # 值日日期
    status = Column(String(20), default=DutyScheduleStatus.SCHEDULED.value)
    notified_at = Column(DateTime(timezone=True), nullable=True)  # 提醒發送時間
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 關聯
    config = relationship("DutyConfig", backref="schedules")
    user = relationship("User", back_populates="duty_schedules")
    report = relationship("DutyReport", back_populates="schedule", uselist=False)

    def __repr__(self):
        return f"<DutySchedule(id={self.id}, date={self.duty_date}, user_id={self.user_id})>"

    @property
    def status_enum(self) -> DutyScheduleStatus:
        """取得狀態的 Enum 值"""
        return DutyScheduleStatus(self.status) if self.status else DutyScheduleStatus.SCHEDULED

    @property
    def status_display(self) -> str:
        """取得狀態的顯示文字"""
        status_map = {
            DutyScheduleStatus.SCHEDULED.value: "已排班",
            DutyScheduleStatus.REPORTED.value: "已回報",
            DutyScheduleStatus.APPROVED.value: "已通過",
            DutyScheduleStatus.REJECTED.value: "未通過",
            DutyScheduleStatus.MISSED.value: "未完成"
        }
        return status_map.get(self.status, "未知")
