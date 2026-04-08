"""模擬練習系統 — 資料模型

讓經紀人與 AI 生成的擬真諮詢者對話練習，
諮詢者人格由 Claude 動態生成，每次都不同。
"""
import json
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class SimulationSession(Base):
    """一次模擬練習的 Session"""
    __tablename__ = "simulation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)       # 練習者（可選，未來綁定用戶）
    admin_id = Column(Integer, ForeignKey("admin_accounts.id"), nullable=True, index=True)  # 練習者（管理員身份）

    # 動態生成的人格資料（JSON）
    persona_snapshot = Column(Text, nullable=False)     # 完整人格 JSON（生成後不再變動）
    persona_name = Column(String(50), nullable=False)   # 諮詢者暱稱（顯示用）
    persona_summary = Column(String(200), nullable=False)  # 一句話摘要（列表顯示用）
    difficulty = Column(String(20), default="random")   # easy / medium / hard / random

    # Session 狀態
    status = Column(String(20), default="active")       # active / completed / abandoned
    total_rounds = Column(Integer, default=0)            # 總對話輪數

    # 情緒追蹤（JSON，每輪更新）
    emotion_history = Column(Text, default="[]")         # [{round, emotion, intensity, trigger}]

    # 最終評分（結束時填入）
    final_score = Column(Integer, nullable=True)         # 0-100
    score_breakdown = Column(Text, nullable=True)        # JSON: 各維度分數
    feedback = Column(Text, nullable=True)               # AI 教練的總結回饋
    grade = Column(String(5), nullable=True)             # A/B/C/D

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    messages = relationship("SimulationMessage", back_populates="session", order_by="SimulationMessage.id")

    @property
    def persona_data(self) -> dict:
        """解析人格 JSON"""
        try:
            return json.loads(self.persona_snapshot) if self.persona_snapshot else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def emotions(self) -> list:
        try:
            return json.loads(self.emotion_history) if self.emotion_history else []
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def score_details(self) -> dict:
        try:
            return json.loads(self.score_breakdown) if self.score_breakdown else {}
        except (json.JSONDecodeError, TypeError):
            return {}


class SimulationMessage(Base):
    """模擬練習中的單則訊息"""
    __tablename__ = "simulation_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("simulation_sessions.id"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)       # 第幾輪對話

    role = Column(String(20), nullable=False)            # user / assistant
    content = Column(Text, nullable=False)               # 訊息內容

    # AI 回覆的原始資料（用於資料分析與 AI 訓練）
    raw_response = Column(Text, nullable=True)           # Claude 的完整原始回覆（JSON parse 前）

    # AI 回覆的內部狀態（僅 assistant 角色有）
    inner_thought = Column(Text, nullable=True)          # AI 的內心想法（不顯示給練習者）
    current_emotion = Column(String(50), nullable=True)  # 當前情緒
    emotion_intensity = Column(Float, nullable=True)     # 情緒強度 0-1
    trust_level = Column(Float, nullable=True)           # 對經紀人的信任度 0-1
    willingness = Column(Float, nullable=True)           # 來上班的意願度 0-1

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("SimulationSession", back_populates="messages")
