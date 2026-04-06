from pydantic import BaseModel
from typing import Optional


class DimensionalScore(BaseModel):
    """四面向評分"""
    process_completeness: int = 0    # 流程完整性 0/10/20/25
    script_accuracy: int = 0         # 話術到位度 0/10/20/25
    emotional_control: int = 0       # 情緒風險控制 0/10/20/25
    action_orientation: int = 0      # 行動結果導向 0/10/20/25
    total: int = 0                   # 總分 0-100

    @classmethod
    def from_dict(cls, data: dict) -> "DimensionalScore":
        """從字典建立 DimensionalScore"""
        if isinstance(data, dict):
            pc = data.get("process_completeness")
            sa = data.get("script_accuracy")
            ec = data.get("emotional_control")
            ao = data.get("action_orientation")
            total = data.get("total")
            return cls(
                process_completeness=pc if isinstance(pc, (int, float)) else 0,
                script_accuracy=sa if isinstance(sa, (int, float)) else 0,
                emotional_control=ec if isinstance(ec, (int, float)) else 0,
                action_orientation=ao if isinstance(ao, (int, float)) else 0,
                total=total if isinstance(total, (int, float)) else 0,
            )
        return cls()


class AIResponse(BaseModel):
    """AI 回覆格式"""
    reply: str                    # AI 要回給使用者的訊息
    is_final: bool = False        # 是否為最終評分（多輪對話結束）
    pass_: bool = False           # 是否通過（只有 is_final=True 時有意義）
    score: int = 0                # 評分 0-100（只有 is_final=True 時有意義，向下相容）
    reason: str = ""              # 評分原因（只有 is_final=True 時有意義）

    # 新版四面向評分
    dimensional_score: Optional[DimensionalScore] = None  # 四面向分數
    dimension_feedback: Optional[dict] = None              # 各維度回饋文字
    grade: str = ""                                        # A/B/C/D 等級

    class Config:
        populate_by_name = True

    @classmethod
    def from_dict(cls, data: dict) -> "AIResponse":
        """從字典建立 AIResponse"""
        # 處理 score：可能是 int（舊格式）或 dict（新格式）
        raw_score = data.get("score")
        dimensional_score = None
        score_int = 0

        if isinstance(raw_score, dict):
            # 新格式：score 是物件
            dimensional_score = DimensionalScore.from_dict(raw_score)
            score_int = dimensional_score.total
        elif isinstance(raw_score, (int, float)):
            # 舊格式：score 是數字
            score_int = int(raw_score)
        elif raw_score is not None:
            try:
                score_int = int(raw_score)
            except (ValueError, TypeError):
                score_int = 0

        # 計算等級
        grade = ""
        if data.get("is_final"):
            if score_int >= 85:
                grade = "A"
            elif score_int >= 70:
                grade = "B"
            elif score_int >= 50:
                grade = "C"
            else:
                grade = "D"

        return cls(
            reply=data.get("reply") or "",
            is_final=data.get("is_final") or False,
            pass_=data.get("pass") if data.get("pass") is not None else False,
            score=score_int,
            reason=data.get("reason") or "",
            dimensional_score=dimensional_score,
            dimension_feedback=data.get("dimension_feedback"),
            grade=grade,
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
