from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base


class Course(Base):
    """課程資料表"""
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    course_version = Column(String(50), default="v1", index=True)  # 課程版本，如 v1, v2
    day = Column(Integer, nullable=False, index=True)  # 訓練天數 0-14+
    title = Column(String(200), nullable=False)  # 課程標題
    goal = Column(Text, nullable=True)  # 訓練目標
    type = Column(String(20), default="assessment")  # teaching（教學）或 assessment（考核）

    # 開場白（考核用）
    opening_a = Column(Text, nullable=True)  # Persona A（無經驗）開場白
    opening_b = Column(Text, nullable=True)  # Persona B（有經驗）開場白

    # 評分標準（JSON 格式儲存，或用換行分隔）
    criteria = Column(Text, nullable=True)  # 評分標準，換行分隔

    # 輪數設定
    min_rounds = Column(Integer, default=3)  # 最少對話輪數
    max_rounds = Column(Integer, default=5)  # 最多對話輪數

    # 教學內容（教學類型用）
    teaching_content = Column(Text, nullable=True)  # Day 0 等教學內容

    # AI Prompt（進階自訂）
    system_prompt = Column(Text, nullable=True)  # 自訂系統 prompt

    # 狀態
    is_active = Column(Boolean, default=True)  # 是否啟用
    sort_order = Column(Integer, default=0)  # 排序順序

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Course(version={self.course_version}, day={self.day}, title={self.title})>"

    @property
    def criteria_list(self) -> list:
        """將評分標準轉為列表"""
        if not self.criteria:
            return []
        return [c.strip() for c in self.criteria.split('\n') if c.strip()]

    @criteria_list.setter
    def criteria_list(self, value: list):
        """從列表設定評分標準"""
        self.criteria = '\n'.join(value) if value else None

    def to_dict(self) -> dict:
        """轉換為字典格式（相容於舊的 days_data 格式）"""
        return {
            "id": self.id,
            "day": self.day,
            "title": self.title,
            "goal": self.goal,
            "type": self.type,
            "opening_a": self.opening_a,
            "opening_b": self.opening_b,
            "criteria": self.criteria_list,
            "min_rounds": self.min_rounds,
            "max_rounds": self.max_rounds,
            "teaching_content": self.teaching_content,
            "system_prompt": self.system_prompt,
            "course_version": self.course_version,
        }
