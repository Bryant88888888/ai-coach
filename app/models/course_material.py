from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class CourseMaterial(Base):
    """課程教材附件（文件/影片/圖片/連結）"""
    __tablename__ = "course_materials"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    material_type = Column(String(20), nullable=False)   # "document"/"video"/"image"/"link"
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    file_url = Column(String(500), nullable=True)        # 上傳檔案的 URL
    external_url = Column(String(500), nullable=True)    # 外部連結（YouTube 等）
    content = Column(Text, nullable=True)                # 行內文字內容
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<CourseMaterial(course_id={self.course_id}, type={self.material_type}, title={self.title})>"
