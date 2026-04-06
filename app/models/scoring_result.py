import json
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class ScoringResult(Base):
    """四面向評分結果"""
    __tablename__ = "scoring_results"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    training_day = Column(Integer, nullable=False)

    # 四面向分數 (各 0/10/20/25)
    process_completeness = Column(Integer, default=0)    # 流程完整性
    script_accuracy = Column(Integer, default=0)         # 話術到位度
    emotional_control = Column(Integer, default=0)       # 情緒風險控制
    action_orientation = Column(Integer, default=0)      # 行動結果導向
    total_score = Column(Integer, default=0)             # 總分 0-100

    dimension_feedback = Column(Text, nullable=True)     # JSON: 每維度回饋文字
    summary = Column(Text, nullable=True)                # 總評
    grade = Column(String(5), nullable=True)             # "A"/"B"/"C"/"D"
    passed = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ScoringResult(user_id={self.user_id}, day={self.training_day}, total={self.total_score}, grade={self.grade})>"

    @property
    def feedback_dict(self) -> dict:
        """將 dimension_feedback JSON 轉為字典"""
        if not self.dimension_feedback:
            return {}
        try:
            return json.loads(self.dimension_feedback)
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def calculate_grade(total_score: int) -> str:
        """根據總分計算等級"""
        if total_score >= 85:
            return "A"
        elif total_score >= 70:
            return "B"
        elif total_score >= 50:
            return "C"
        else:
            return "D"
