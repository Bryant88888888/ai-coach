from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import json


class DutyComplaintStatus(str, enum.Enum):
    """檢舉狀態"""
    PENDING = "pending"      # 待處理
    RESOLVED = "resolved"    # 已處理
    DISMISSED = "dismissed"  # 已駁回


class DutyComplaint(Base):
    """值日檢舉記錄"""
    __tablename__ = "duty_complaints"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("duty_schedules.id"), nullable=False)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 檢舉人
    reported_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 被檢舉人
    complaint_text = Column(Text, nullable=False)  # 檢舉內容
    photo_urls = Column(Text, nullable=True)  # JSON array: 證據照片 URL 列表
    status = Column(String(20), default=DutyComplaintStatus.PENDING.value)
    handler_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 處理人
    handler_note = Column(Text, nullable=True)  # 處理備註
    handled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 關聯
    schedule = relationship("DutySchedule", backref="complaints")
    reporter = relationship("User", foreign_keys=[reporter_id], backref="filed_complaints")
    reported_user = relationship("User", foreign_keys=[reported_user_id], backref="received_complaints")
    handler = relationship("User", foreign_keys=[handler_id])

    def __repr__(self):
        return f"<DutyComplaint(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"

    @property
    def status_enum(self) -> DutyComplaintStatus:
        """取得狀態的 Enum 值"""
        return DutyComplaintStatus(self.status) if self.status else DutyComplaintStatus.PENDING

    @property
    def status_display(self) -> str:
        """取得狀態的顯示文字"""
        status_map = {
            DutyComplaintStatus.PENDING.value: "待處理",
            DutyComplaintStatus.RESOLVED.value: "已處理",
            DutyComplaintStatus.DISMISSED.value: "已駁回"
        }
        return status_map.get(self.status, "未知")

    def get_photo_urls(self) -> list[str]:
        """取得照片 URL 列表"""
        if not self.photo_urls:
            return []
        try:
            return json.loads(self.photo_urls)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_photo_urls(self, urls: list[str]) -> None:
        """設定照片 URL 列表"""
        self.photo_urls = json.dumps(urls)
