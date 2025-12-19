from pydantic import BaseModel
from typing import Optional


class AIResponse(BaseModel):
    """AI 回覆格式（GPT 回傳的 JSON 結構）"""
    reply: str                    # AI 要回給使用者的訊息
    pass_: bool                   # 是否通過（用 pass_ 因為 pass 是 Python 保留字）
    score: int                    # 評分（0-100）
    reason: str                   # 評分原因

    class Config:
        # 允許從 JSON 的 "pass" 欄位對應到 pass_
        populate_by_name = True

    @classmethod
    def from_dict(cls, data: dict) -> "AIResponse":
        """從字典建立 AIResponse（處理 pass 欄位名稱）"""
        return cls(
            reply=data.get("reply", ""),
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
