from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Date
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class LeaveType(str, enum.Enum):
    """請假類型"""
    PERSONAL = "事假"    # 事假
    SICK = "病假"        # 病假


class LeaveStatus(str, enum.Enum):
    """請假狀態"""
    PENDING = "pending"              # 待審核
    PENDING_PROOF = "pending_proof"  # 待補件
    APPROVED = "approved"            # 已核准
    REJECTED = "rejected"            # 已拒絕


class LeaveRequest(Base):
    """請假申請表"""
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    applicant_name = Column(String(100), nullable=True)  # 申請人填寫的姓名
    line_display_name = Column(String(100), nullable=True)  # LINE 顯示名稱
    line_picture_url = Column(String(500), nullable=True)  # LINE 頭像 URL
    leave_type = Column(String(20), nullable=False)  # 事假/病假
    leave_date = Column(Date, nullable=False)  # 請假日期
    reason = Column(Text, nullable=True)  # 事假理由
    proof_file = Column(String(500), nullable=True)  # 病假證明檔案路徑
    proof_deadline = Column(DateTime(timezone=True), nullable=True)  # 補件期限
    status = Column(String(20), default=LeaveStatus.PENDING.value)
    reviewer_note = Column(Text, nullable=True)  # 審核備註
    reviewed_at = Column(DateTime(timezone=True), nullable=True)  # 審核時間
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 關聯
    user = relationship("User", backref="leave_requests")

    def __repr__(self):
        return f"<LeaveRequest(id={self.id}, user_id={self.user_id}, type={self.leave_type}, date={self.leave_date})>"

    @property
    def leave_type_enum(self) -> LeaveType:
        """取得請假類型的 Enum 值"""
        return LeaveType(self.leave_type) if self.leave_type else LeaveType.PERSONAL

    @property
    def status_enum(self) -> LeaveStatus:
        """取得狀態的 Enum 值"""
        return LeaveStatus(self.status) if self.status else LeaveStatus.PENDING
