from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class InfoFormSubmission(Base):
    """人事資料表單提交記錄"""
    __tablename__ = "info_form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    line_user_id = Column(String(100), nullable=False)
    form_type = Column(String(20), nullable=False)  # 公關版本 / 經紀人版本 / 異動資料
    form_data = Column(Text, nullable=False)  # JSON 格式儲存所有欄位
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="info_form_submissions")

    def __repr__(self):
        return f"<InfoFormSubmission(id={self.id}, type={self.form_type}, user_id={self.user_id})>"
