from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class CourseScenario(Base):
    """課程-人設多對多指派"""
    __tablename__ = "course_scenarios"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    persona_id = Column(Integer, ForeignKey("scenario_personas.id"), nullable=False, index=True)
    opening_override = Column(Text, nullable=True)   # 該天專屬開場白（覆蓋人設預設）
    weight = Column(Integer, default=1)               # 選取權重

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<CourseScenario(course_id={self.course_id}, persona_id={self.persona_id})>"
