from sqlalchemy.orm import Session
from app.models.user import User
from app.models.user_training import UserTraining, TrainingStatus
from app.services.user_service import UserService
from app.services.ai_service import AIService
from app.services.message_service import MessageService
from app.services.course_service import get_course_data
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

    def _get_testing_day(self, user: User) -> int:
        """
        取得正在測驗的天數

        手動發送時 testing_day 會與 current_day 不同
        一般情況下 testing_day 等於 current_day
        """
        training = self._get_active_training(user)
        if training:
            # 如果有設定 testing_day 就用它，否則用 current_day
            if training.testing_day is not None:
                return training.testing_day
            return training.current_day
        return user.current_day

    def _is_manual_test(self, user: User) -> bool:
        """
        判斷是否為手動發送的測驗

        手動發送時 testing_day != current_day
        """
        training = self._get_active_training(user)
        if training and training.testing_day is not None:
            return training.testing_day != training.current_day
        return False

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

    def _get_course_version(self, user: User) -> str:
        """取得用戶當前訓練的課程版本"""
        training = self._get_active_training(user)
        if training and training.batch:
            return training.batch.course_version
        return "v1"  # 預設版本

    def get_today_training(self, current_day: int, course_version: str = "v1") -> dict | None:
        """取得當日課程資料"""
        return get_course_data(self.db, current_day, course_version)

    def _get_attempt_started_at(self, user: User):
        """取得當前測驗開始時間"""
        training = self._get_active_training(user)
        if training and training.attempt_started_at:
            return training.attempt_started_at
        return None

    def get_conversation_history(self, user: User, limit: int = 10) -> list[dict]:
        """
        取得用戶當前測驗的對話歷史（用於多輪對話）

        只取當前測驗開始後的訊息，不會使用之前測驗的紀錄

        Args:
            user: 用戶物件
            limit: 最多取幾輪

        Returns:
            對話歷史列表，格式為 [{"role": "user/assistant", "content": "..."}]
        """
        testing_day = self._get_testing_day(user)  # 使用 testing_day
        attempt_started_at = self._get_attempt_started_at(user)

        # 只取當前測驗的訊息
        messages = self.message_service.get_current_attempt_messages(
            user_id=user.id,
            day=testing_day,
            attempt_started_at=attempt_started_at
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
        current_day = self._get_training_day(user)      # 正式進度
        testing_day = self._get_testing_day(user)       # 正在測驗的天數
        is_manual_test = self._is_manual_test(user)     # 是否為手動發送的測驗
        current_round = self._get_training_round(user)
        course_version = self._get_course_version(user)

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

        # 取得測驗天數的課程（使用 testing_day，不是 current_day）
        day_data = self.get_today_training(testing_day, course_version)
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
                training_day=testing_day
            )

            # 只有非手動測驗才推進進度
            if not is_manual_test:
                self._update_progress(user, active_training, current_day + 1)
                self._reset_round(user, active_training)
                self._clear_testing_day(active_training)
                next_day = current_day + 1
            else:
                # 手動測驗完成，清除 testing_day 但不改變 current_day
                self._reset_round(user, active_training)
                self._clear_testing_day(active_training)
                next_day = current_day  # 維持原進度

            return TrainingResult(
                user_message=user_message,
                ai_response=ai_response,
                current_day=current_day,
                next_day=next_day,
                is_completed=False,
                round_count=0
            )

        # 取得今日 Persona（已在用戶按下「開始訓練」時隨機決定）
        # Persona 決定 AI 要扮演哪種角色出題（A=無經驗諮詢者, B=有經驗諮詢者）
        persona = self._get_persona_letter(user)
        if not persona:
            # 如果沒有設定（例如舊資料），預設使用 A
            persona = "A"

        # 取得對話歷史
        conversation_history = self.get_conversation_history(user)

        # 增加輪數
        new_round = current_round + 1

        # 呼叫 AI 產生回應（使用 testing_day）
        ai_response = self.ai_service.generate_response(
            day=testing_day,
            persona=persona,
            user_message=user_message,
            round_count=new_round,
            conversation_history=conversation_history
        )

        # 儲存對話記錄（使用 testing_day）
        self.message_service.save_message(
            user=user,
            user_message=user_message,
            ai_response=ai_response,
            training_day=testing_day
        )

        # 更新輪數
        self._update_round(user, active_training, new_round)

        # 判斷是否結束這輪訓練
        next_day = current_day
        is_completed = False

        if ai_response.is_final:
            if ai_response.pass_:
                # 通過
                if is_manual_test:
                    # 手動測驗：不推進進度，只清除 testing_day
                    self._reset_round(user, active_training)
                    self._clear_testing_day(active_training)
                    # next_day 維持 current_day（不變）
                elif current_day < MAX_TRAINING_DAY:
                    # 正常測驗且還沒到最後一天：進入下一天
                    next_day = current_day + 1
                    self._update_progress(user, active_training, next_day)
                    self._reset_round(user, active_training)
                    self._clear_testing_day(active_training)
                else:
                    # 已完成所有訓練
                    is_completed = True
                    self._clear_testing_day(active_training)
                    if active_training:
                        from datetime import datetime
                        active_training.status = TrainingStatus.COMPLETED.value
                        active_training.completed_at = datetime.now()
                        self.db.commit()
            else:
                # 未通過：重置輪數（不管是否手動測驗）
                self._reset_round(user, active_training)
                # 不清除 testing_day，讓用戶可以重新測驗

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

        新用戶需要先被加入訓練批次，並按下「開始訓練」按鈕才會開始
        Persona 會在按下「開始訓練」時隨機決定
        """
        # 直接進入訓練流程（會檢查是否已開始訓練）
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

    def _clear_testing_day(self, training: UserTraining | None) -> None:
        """清除 testing_day（測驗完成後呼叫）"""
        if training:
            training.testing_day = None
            self.db.commit()

    def get_progress_summary(self, user: User) -> dict:
        """取得用戶訓練進度摘要"""
        active_training = self._get_active_training(user)
        current_day = self._get_training_day(user)
        current_round = self._get_training_round(user)
        persona = self._get_training_persona(user)
        course_version = self._get_course_version(user)
        total_days = MAX_TRAINING_DAY + 1  # Day 0 到 Day 14

        day_data = self.get_today_training(current_day, course_version)
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
