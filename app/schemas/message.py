from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MessageBase(BaseModel):
    """對話記錄基礎欄位"""
    user_message: str
    ai_reply: str
    training_day: int
    passed: bool
    score: int
    reason: Optional[str] = None


class MessageCreate(MessageBase):
    """建立對話記錄時的資料"""
    user_id: int


class MessageResponse(MessageBase):
    """對話記錄回應格式"""
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationHistory(BaseModel):
    """用戶對話歷史"""
    user_id: int
    line_user_id: str
    user_name: Optional[str]
    current_day: int
    total_messages: int
    messages: list[MessageResponse]


class MessageStats(BaseModel):
    """對話統計"""
    total_messages: int
    passed_count: int
    failed_count: int
    pass_rate: float
    average_score: float
