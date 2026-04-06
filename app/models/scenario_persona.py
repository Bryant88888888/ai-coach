import json
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base


class ScenarioPersona(Base):
    """模擬人設（AI 角色扮演用）"""
    __tablename__ = "scenario_personas"

    id = Column(Integer, primary_key=True, index=True)
    course_version = Column(String(50), default="v1", index=True)
    name = Column(String(100), nullable=False)          # 人設名稱，如 "好奇型女生"
    code = Column(String(30), nullable=False)            # 代碼，如 "curious"
    description = Column(Text, nullable=False)           # AI prompt 用的完整人設描述
    behavior_traits = Column(Text, nullable=True)        # JSON: 行為特徵列表
    opening_templates = Column(Text, nullable=True)      # JSON: 可用的開場白列表
    difficulty_level = Column(Integer, default=1)        # 1=簡單 2=中等 3=困難
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ScenarioPersona(name={self.name}, code={self.code})>"

    @property
    def traits_list(self) -> list:
        """將 behavior_traits JSON 轉為列表"""
        if not self.behavior_traits:
            return []
        try:
            return json.loads(self.behavior_traits)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def openings_list(self) -> list:
        """將 opening_templates JSON 轉為列表"""
        if not self.opening_templates:
            return []
        try:
            return json.loads(self.opening_templates)
        except (json.JSONDecodeError, TypeError):
            return []
