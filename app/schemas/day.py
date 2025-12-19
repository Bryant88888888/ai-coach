from pydantic import BaseModel
from typing import Optional


class DayBase(BaseModel):
    """課程基礎欄位"""
    day: int
    title: str
    goal: str
    prompt: str


class DayCreate(DayBase):
    """建立課程時的資料"""
    prompt_persona_a: Optional[str] = None
    prompt_persona_b: Optional[str] = None


class DayResponse(DayBase):
    """課程回應格式"""
    id: int
    prompt_persona_a: Optional[str] = None
    prompt_persona_b: Optional[str] = None

    class Config:
        from_attributes = True
