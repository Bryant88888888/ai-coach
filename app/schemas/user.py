from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """用戶基礎欄位"""
    line_user_id: str
    name: Optional[str] = None


class UserCreate(UserBase):
    """建立用戶時的資料"""
    pass


class UserUpdate(BaseModel):
    """更新用戶時的資料"""
    name: Optional[str] = None
    current_day: Optional[int] = None
    status: Optional[str] = None
    persona: Optional[str] = None


class UserResponse(UserBase):
    """用戶回應格式"""
    id: int
    current_day: int
    status: str
    persona: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
