from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from app.database import Base
import json


class DutyConfig(Base):
    """值日生排班設定"""
    __tablename__ = "duty_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 設定名稱（例：清潔值日）
    members_per_day = Column(Integer, default=1)  # 每天值日人數
    tasks = Column(Text, nullable=True)  # JSON: 任務清單
    notify_time = Column(String(10), default="08:00")  # 提醒時間 (HH:MM)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<DutyConfig(id={self.id}, name={self.name})>"

    def get_tasks(self) -> list[str]:
        """取得任務清單"""
        if not self.tasks:
            return []
        try:
            return json.loads(self.tasks)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_tasks(self, tasks: list[str]) -> None:
        """設定任務清單"""
        self.tasks = json.dumps(tasks, ensure_ascii=False)
