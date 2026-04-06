import json
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class ScoringRubric(Base):
    """評分維度定義（四面向評分制度）"""
    __tablename__ = "scoring_rubrics"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    dimension = Column(String(50), nullable=False)      # "process_completeness"
    dimension_label = Column(String(100), nullable=False)  # "流程完整性"
    description = Column(Text, nullable=True)           # 該維度在這天的具體檢查內容
    max_score = Column(Integer, default=25)
    sort_order = Column(Integer, default=0)

    # JSON: [{"score":0,"criteria":"..."}, {"score":10,...}, {"score":20,...}, {"score":25,...}]
    tiers = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ScoringRubric(course_id={self.course_id}, dimension={self.dimension})>"

    @property
    def tiers_list(self) -> list:
        """將 tiers JSON 轉為列表"""
        if not self.tiers:
            return []
        try:
            return json.loads(self.tiers)
        except (json.JSONDecodeError, TypeError):
            return []

    @tiers_list.setter
    def tiers_list(self, value: list):
        """從列表設定 tiers"""
        self.tiers = json.dumps(value, ensure_ascii=False) if value else None
