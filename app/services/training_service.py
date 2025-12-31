from sqlalchemy.orm import Session
from app.models.user import User
from app.models.user_training import UserTraining, TrainingStatus
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

    def _get_active_training(self, user: User) -> UserTraining | None:
        """取得用戶目前進行中的訓練"""
        for training in user.trainings:
            if training.status == TrainingStatus.ACTIVE.value:
                return training
        return None

    def _get_training_day(self, user: User) -> int:
        """取得用戶當前訓練天數（優先使用 UserTraining）"""
        training = self._get_active_training(user)
        if training:
            return training.current_day
        return user.current_day

    def _get_training_round(self, user: User) -> int:
        """取得用戶當前對話輪數（優先使用 UserTraining）"""
        training = self._get_active_training(user)
        if training:
            return training.current_round
        return user.current_round or 0

    def _get_training_persona(self, user: User) -> str | None:
        """取得用戶 Persona（優先使用 UserTraining）"""
        training = self._get_active_training(user)
        if training and training.persona:
            return training.persona
        return user.persona

    def get_today_training(self, current_day: int) -> dict | None:
        """取得當日課程資料"""
        return get_day_data(current_day)

    def get_conversation_history(self, user: User, limit: int = 10) -> list[dict]:
        """
        取得用戶當天的對話歷史（用於多輪對話）

        Args:
            user: 用戶物件
            limit: 最多取幾輪

        Returns:
            對話歷史列表，格式為 [{"role": "user/assistant", "content": "..."}]
        """
        current_day = self._get_training_day(user)
        messages = self.message_service.get_user_messages_by_day(
            user_id=user.id,
            day=current_day
        )

        # 轉換為 Claude 對話格式（最新的在後面）
        history = []
        for msg in reversed(messages[-limit:]):
            history.append({"role": "user", "content": msg.user_message})
            history.append({"role": "assistant", "content": msg.ai_reply})

        return history

    def process_training(self, user: User, user_message: str) -> TrainingResult:
        """
        處理訓練流程（多輪對話版本）

        Args:
            user: 用戶物件
            user_message: 用戶輸入的訊息

        Returns:
            TrainingResult: 訓練結果
        """
        # 取得進行中的訓練（如果有）
        active_training = self._get_active_training(user)

        # 使用 UserTraining 或 User 的進度
        current_day = self._get_training_day(user)
        current_round = self._get_training_round(user)

        # 如果沒有進行中的訓練，回傳提示
        if not active_training and user.current_day == 0:
            return TrainingResult(
                user_message=user_message,
                ai_response=AIResponse(
                    reply="您好！您目前尚未開始訓練，請等待管理員為您安排訓練課程。",
                    is_final=True,
                    pass_=False,
                    score=0,
                    reason="尚未開始訓練"
                ),
                current_day=0,
                next_day=0,
                is_completed=False,
                round_count=0
            )

        # 取得今日課程
        day_data = self.get_today_training(current_day)
        if not day_data:
            # 標記訓練完成
            if active_training:
                from datetime import datetime
                active_training.status = TrainingStatus.COMPLETED.value
                active_training.completed_at = datetime.now()
                self.db.commit()

            return TrainingResult(
                user_message=user_message,
                ai_response=AIResponse(
                    reply="恭喜你！你已經完成了所有訓練課程！",
                    is_final=True,
                    pass_=True,
                    score=100,
                    reason="訓練已完成"
                ),
                current_day=current_day,
                next_day=current_day,
                is_completed=True,
                round_count=current_round
            )

        # Day 0 特殊處理：純教學，自動通過
        if day_data.get("type") == "teaching":
            # 儲存對話記錄
            ai_response = AIResponse(
                reply="好的，我了解了！",
                is_final=True,
                pass_=True,
                score=100,
                reason="Day 0 教學完成"
            )

            self.message_service.save_message(
                user=user,
                user_message=user_message,
                ai_response=ai_response,
                training_day=current_day
            )

            # 自動進入下一天
            self._update_progress(user, active_training, current_day + 1)
            self._reset_round(user, active_training)

            return TrainingResult(
                user_message=user_message,
                ai_response=ai_response,
                current_day=current_day,
                next_day=current_day + 1,
                is_completed=False,
                round_count=0
            )

        # 取得 Persona（如果尚未分類，在第一次 AI 對話時分類）
        training_persona = self._get_training_persona(user)
        if not training_persona and current_day >= 1 and current_round == 0:
            # 第一次進入 AI 對話，分類 Persona
            classified_persona = self.ai_service.classify_persona(user_message)
            self._set_persona(user, active_training, classified_persona)
            persona = "A" if "A" in classified_persona else "B"
        else:
            persona = self._get_persona_letter(user)

        # 取得對話歷史
        conversation_history = self.get_conversation_history(user)

        # 增加輪數
        new_round = current_round + 1

        # 呼叫 AI 產生回應
        ai_response = self.ai_service.generate_response(
            day=current_day,
            persona=persona,
            user_message=user_message,
            round_count=new_round,
            conversation_history=conversation_history
        )

        # 儲存對話記錄
        self.message_service.save_message(
            user=user,
            user_message=user_message,
            ai_response=ai_response,
            training_day=current_day
        )

        # 更新輪數
        self._update_round(user, active_training, new_round)

        # 判斷是否結束這輪訓練
        next_day = current_day
        is_completed = False

        if ai_response.is_final:
            if ai_response.pass_:
                # 通過：進入下一天
                if current_day < MAX_TRAINING_DAY:
                    next_day = current_day + 1
                    self._update_progress(user, active_training, next_day)
                    self._reset_round(user, active_training)
                else:
                    is_completed = True
                    # 標記訓練完成
                    if active_training:
                        from datetime import datetime
                        active_training.status = TrainingStatus.COMPLETED.value
                        active_training.completed_at = datetime.now()
                        self.db.commit()
            else:
                # 未通過：重置輪數，明天繼續同一天
                self._reset_round(user, active_training)

        return TrainingResult(
            user_message=user_message,
            ai_response=ai_response,
            current_day=current_day,
            next_day=next_day,
            is_completed=is_completed,
            round_count=new_round
        )

    def handle_new_user(self, user: User, first_message: str) -> TrainingResult:
        """
        處理新用戶的第一則訊息

        1. 分類 Persona
        2. 開始訓練
        """
        active_training = self._get_active_training(user)

        # 使用 AI 分類 Persona
        persona = self.ai_service.classify_persona(first_message)
        self._set_persona(user, active_training, persona)

        # 開始訓練
        return self.process_training(user, first_message)

    def _get_persona_letter(self, user: User) -> str:
        """取得用戶的 Persona 字母（A 或 B）"""
        persona = self._get_training_persona(user)
        if persona:
            return "A" if "A" in persona else "B"
        return "A"  # 預設

    def _update_progress(self, user: User, training: UserTraining | None, new_day: int) -> None:
        """更新訓練進度"""
        if training:
            training.current_day = new_day
        else:
            user.current_day = new_day
        self.db.commit()

    def _update_round(self, user: User, training: UserTraining | None, round_count: int) -> None:
        """更新用戶的對話輪數"""
        if training:
            training.current_round = round_count
        else:
            user.current_round = round_count
        self.db.commit()

    def _reset_round(self, user: User, training: UserTraining | None) -> None:
        """重置用戶的對話輪數"""
        if training:
            training.current_round = 0
        else:
            user.current_round = 0
        self.db.commit()

    def _set_persona(self, user: User, training: UserTraining | None, persona: str) -> None:
        """設定 Persona"""
        if training:
            training.persona = persona
        else:
            self.user_service.set_persona(user, persona)
        self.db.commit()

    def get_progress_summary(self, user: User) -> dict:
        """取得用戶訓練進度摘要"""
        active_training = self._get_active_training(user)
        current_day = self._get_training_day(user)
        current_round = self._get_training_round(user)
        persona = self._get_training_persona(user)
        total_days = MAX_TRAINING_DAY + 1  # Day 0 到 Day 14

        day_data = self.get_today_training(current_day)
        current_title = day_data["title"] if day_data else "已完成所有訓練"

        # 訓練狀態
        if active_training:
            training_status = active_training.status
            batch_name = active_training.batch.name if active_training.batch else None
        else:
            training_status = "none"
            batch_name = None

        return {
            "user_id": user.id,
            "line_user_id": user.line_user_id,
            "current_day": current_day,
            "current_round": current_round,
            "total_days": total_days,
            "progress_percent": round((current_day / MAX_TRAINING_DAY) * 100, 1),
            "current_title": current_title,
            "persona": persona,
            "is_completed": current_day > MAX_TRAINING_DAY,
            "training_status": training_status,
            "batch_name": batch_name
        }
