import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class DutySwapStatus(str, enum.Enum):
    PENDING = "pending"        # 待審核（等對方同意）
    APPROVED = "approved"      # 已同意（排班已互換）
    REJECTED = "rejected"      # 已拒絕
    CANCELLED = "cancelled"    # 已取消（申請者自行取消）


class DutySwap(Base):
    """值日生換班申請"""
    __tablename__ = "duty_swaps"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("duty_schedules.id"), nullable=False)
    target_schedule_id = Column(Integer, ForeignKey("duty_schedules.id"), nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default=DutySwapStatus.PENDING.value, nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    response_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id], backref="swap_requests_sent")
    target_user = relationship("User", foreign_keys=[target_user_id], backref="swap_requests_received")
    schedule = relationship("DutySchedule", foreign_keys=[schedule_id], backref="swap_as_source")
    target_schedule = relationship("DutySchedule", foreign_keys=[target_schedule_id], backref="swap_as_target")

    @property
    def status_enum(self) -> DutySwapStatus:
        return DutySwapStatus(self.status)

    @property
    def status_display(self) -> str:
        display_map = {
            DutySwapStatus.PENDING: "待審核",
            DutySwapStatus.APPROVED: "已同意",
            DutySwapStatus.REJECTED: "已拒絕",
            DutySwapStatus.CANCELLED: "已取消",
        }
        return display_map.get(self.status_enum, self.status)
