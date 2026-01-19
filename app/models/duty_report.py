from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import json


class DutyReportStatus(str, enum.Enum):
    """值日回報狀態"""
    PENDING = "pending"      # 待審核
    APPROVED = "approved"    # 已通過
    REJECTED = "rejected"    # 已拒絕


class DutyReport(Base):
    """值日回報記錄"""
    __tablename__ = "duty_reports"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("duty_schedules.id"), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    report_text = Column(Text, nullable=True)  # 回報文字內容
    photo_urls = Column(Text, nullable=True)  # JSON array: 照片 URL 列表
    status = Column(String(20), default=DutyReportStatus.PENDING.value)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 審核人
    reviewer_note = Column(Text, nullable=True)  # 審核備註
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    schedule = relationship("DutySchedule", back_populates="report")
    user = relationship("User", foreign_keys=[user_id], backref="duty_reports")
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    def __repr__(self):
        return f"<DutyReport(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"

    @property
    def status_enum(self) -> DutyReportStatus:
        """取得狀態的 Enum 值"""
        return DutyReportStatus(self.status) if self.status else DutyReportStatus.PENDING

    @property
    def status_display(self) -> str:
        """取得狀態的顯示文字"""
        status_map = {
            DutyReportStatus.PENDING.value: "待審核",
            DutyReportStatus.APPROVED.value: "已通過",
            DutyReportStatus.REJECTED.value: "已拒絕"
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

    def add_photo_url(self, url: str) -> None:
        """添加照片 URL"""
        urls = self.get_photo_urls()
        urls.append(url)
        self.set_photo_urls(urls)
