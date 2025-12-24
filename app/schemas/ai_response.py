from pydantic import BaseModel
from typing import Optional


class AIResponse(BaseModel):
    """AI 回覆格式"""
    reply: str                    # AI 要回給使用者的訊息
    is_final: bool = False        # 是否為最終評分（多輪對話結束）
    pass_: bool = False           # 是否通過（只有 is_final=True 時有意義）
    score: int = 0                # 評分 0-100（只有 is_final=True 時有意義）
    reason: str = ""              # 評分原因（只有 is_final=True 時有意義）

    class Config:
        populate_by_name = True

    @classmethod
    def from_dict(cls, data: dict) -> "AIResponse":
        """從字典建立 AIResponse"""
        return cls(
            reply=data.get("reply", ""),
            is_final=data.get("is_final", False),
            pass_=data.get("pass", False),
            score=data.get("score", 0),
            reason=data.get("reason", "")
        )


class TrainingResult(BaseModel):
    """訓練結果"""
    user_message: str             # 用戶輸入的訊息
    ai_response: AIResponse       # AI 回覆內容
    current_day: int              # 當前天數
    next_day: int                 # 下一天（如果通過）
    is_completed: bool            # 是否完成全部訓練（Day 14）
    round_count: int = 0          # 目前對話輪數


class Day0Result(BaseModel):
    """Day 0 教學結果"""
    teaching_content: str         # 教學內容
    current_day: int = 0
    next_day: int = 1
    auto_pass: bool = True
