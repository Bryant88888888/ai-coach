from sqlalchemy import Column, Integer, String, Text
from app.database import Base


class Day(Base):
    """訓練課程資料表"""
    __tablename__ = "days"

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Integer, unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    goal = Column(String(500), nullable=False)
    prompt = Column(Text, nullable=False)
    prompt_persona_a = Column(Text, nullable=True)  # 無經驗版本的 prompt（選配）
    prompt_persona_b = Column(Text, nullable=True)  # 有經驗版本的 prompt（選配）

    def __repr__(self):
        return f"<Day(day={self.day}, title={self.title})>"
