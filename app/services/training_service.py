from sqlalchemy.orm import Session
from app.models.user import User
from app.services.user_service import UserService
from app.services.ai_service import AIService
from app.services.message_service import MessageService
from app.data.days_data import get_day_data
from app.schemas.ai_response import AIResponse, TrainingResult

# 訓練的最後一天
MAX_TRAINING_DAY = 14


class TrainingService:
    """訓練流程控制服務"""

    def __init__(self, db: Session):
        self.db = db
        self.user_service = UserService(db)
        self.ai_service = AIService()
        self.message_service = MessageService(db)

    def get_today_training(self, current_day: int) -> dict | None:
        """取得當日課程資料"""
        return get_day_data(current_day)

    def process_training(self, user: User, user_message: str) -> TrainingResult:
        """
        處理訓練流程

        Args:
            user: 用戶物件
            user_message: 用戶輸入的訊息

        Returns:
            TrainingResult: 訓練結果
        """
        current_day = user.current_day

        # 取得今日課程
        day_data = self.get_today_training(current_day)
        if not day_data:
            # 如果沒有課程資料（已完成所有訓練或錯誤）
            return TrainingResult(
                user_message=user_message,
                ai_response=AIResponse(
                    reply="恭喜你！你已經完成了所有訓練課程！",
                    pass_=True,
                    score=100,
                    reason="訓練已完成"
                ),
                current_day=current_day,
                next_day=current_day,
                is_completed=True
            )

        # 呼叫 AI 產生回應
        ai_response = self.ai_service.generate_response(
            prompt=day_data["prompt"],
            user_message=user_message,
            persona=user.persona
        )

        # 儲存對話記錄
        self.message_service.save_message(
            user=user,
            user_message=user_message,
            ai_response=ai_response,
            training_day=current_day
        )

        # 判斷是否通過並更新進度
        next_day = current_day
        is_completed = False

        if ai_response.pass_:
            if current_day < MAX_TRAINING_DAY:
                next_day = current_day + 1
                self.user_service.update_progress(user, next_day)
            else:
                is_completed = True

        return TrainingResult(
            user_message=user_message,
            ai_response=ai_response,
            current_day=current_day,
            next_day=next_day,
            is_completed=is_completed
        )

    def handle_new_user(self, user: User, first_message: str) -> TrainingResult:
        """
        處理新用戶的第一則訊息

        1. 分類 Persona
        2. 開始 Day 0 訓練
        """
        # 分類 Persona（使用關鍵字分類，也可以改用 AI 分類）
        self.user_service.classify_persona(user, first_message)

        # 開始訓練
        return self.process_training(user, first_message)

    def get_progress_summary(self, user: User) -> dict:
        """取得用戶訓練進度摘要"""
        current_day = user.current_day
        total_days = MAX_TRAINING_DAY + 1  # Day 0 到 Day 14

        day_data = self.get_today_training(current_day)
        current_title = day_data["title"] if day_data else "已完成所有訓練"

        return {
            "user_id": user.id,
            "line_user_id": user.line_user_id,
            "current_day": current_day,
            "total_days": total_days,
            "progress_percent": round((current_day / MAX_TRAINING_DAY) * 100, 1),
            "current_title": current_title,
            "persona": user.persona if user.persona else None,
            "is_completed": current_day > MAX_TRAINING_DAY
        }
