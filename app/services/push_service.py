from datetime import date, datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)

from app.config import get_settings
from app.models.user import User, UserStatus
from app.models.user_training import UserTraining, TrainingStatus
from app.models.push_log import PushLog
from app.services.course_service import get_course_data

# 訓練的最後一天
MAX_TRAINING_DAY = 14


class PushService:
    """每日推送服務"""

    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self.line_config = Configuration(access_token=settings.line_channel_access_token)

    def _send_push_message(self, user_id: str, message: str) -> None:
        """發送 LINE 推送訊息"""
        with ApiClient(self.line_config) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )

    def get_users_to_push(self) -> list[User]:
        """取得需要推送的用戶列表（舊版，保留相容性）"""
        return (
            self.db.query(User)
            .filter(
                and_(
                    User.status == UserStatus.ACTIVE.value,
                    User.current_day <= MAX_TRAINING_DAY
                )
            )
            .all()
        )

    def get_active_trainings_to_push(self) -> list[UserTraining]:
        """取得需要推送的進行中訓練列表"""
        return (
            self.db.query(UserTraining)
            .filter(
                and_(
                    UserTraining.status == TrainingStatus.ACTIVE.value,
                    UserTraining.current_day <= MAX_TRAINING_DAY
                )
            )
            .all()
        )

    def has_pushed_today(self, user_id: int) -> bool:
        """檢查今天是否已經推送過"""
        today = date.today()
        existing = (
            self.db.query(PushLog)
            .filter(
                and_(
                    PushLog.user_id == user_id,
                    PushLog.push_date == today
                )
            )
            .first()
        )
        return existing is not None

    def get_opening_message(self, day: int, persona: str | None, course_version: str = "v1") -> str:
        """
        取得當日訓練的固定開場白

        Args:
            day: 訓練天數
            persona: 用戶 Persona（包含 "A" 或 "B"）
            course_version: 課程版本

        Returns:
            固定的開場白訊息
        """
        day_data = get_course_data(self.db, day, course_version)
        if not day_data:
            return "你好，準備開始今天的訓練了嗎？"

        # Day 0 是純教學
        if day_data.get("type") == "teaching":
            return day_data.get("teaching_content", "")

        # 判斷 Persona 字母
        persona_letter = "a"  # 預設
        if persona and "B" in persona:
            persona_letter = "b"

        # 取得對應 Persona 的開場白
        opening_key = f"opening_{persona_letter}"
        opening = day_data.get(opening_key, "")

        if opening:
            return opening
        else:
            # 如果沒有對應的開場白，使用 A 版本
            return day_data.get("opening_a", "準備開始今天的訓練！")

    def push_to_user(self, user: User, course_version: str = "v1") -> dict:
        """
        推送訊息給單一用戶

        Returns:
            dict: 包含推送結果的資訊
        """
        # 檢查今天是否已經推送過
        if self.has_pushed_today(user.id):
            return {
                "user_id": user.id,
                "line_user_id": user.line_user_id,
                "status": "skipped",
                "reason": "already_pushed_today"
            }

        try:
            # 取得固定開場訊息
            opening_message = self.get_opening_message(
                user.current_day,
                user.persona,
                course_version
            )

            # 發送 LINE 訊息
            self._send_push_message(
                user_id=user.line_user_id,
                message=opening_message
            )

            # 記錄推送
            push_log = PushLog(
                user_id=user.id,
                push_date=date.today(),
                training_day=user.current_day,
                push_message=opening_message,
                responded=False
            )
            self.db.add(push_log)
            self.db.commit()

            return {
                "user_id": user.id,
                "line_user_id": user.line_user_id,
                "status": "success",
                "training_day": user.current_day,
                "message_preview": opening_message[:50] + "..."
            }

        except Exception as e:
            return {
                "user_id": user.id,
                "line_user_id": user.line_user_id,
                "status": "error",
                "reason": str(e)
            }

    def push_to_training(self, user_training: UserTraining) -> dict:
        """
        推送訊息給訓練中的用戶

        Args:
            user_training: UserTraining 物件

        Returns:
            dict: 包含推送結果的資訊
        """
        user = user_training.user

        # 檢查今天是否已經推送過
        if self.has_pushed_today(user.id):
            return {
                "user_id": user.id,
                "training_id": user_training.id,
                "line_user_id": user.line_user_id,
                "status": "skipped",
                "reason": "already_pushed_today"
            }

        try:
            # 取得課程版本（從 training 的 batch 取得）
            course_version = "v1"
            if user_training.batch:
                course_version = user_training.batch.course_version

            # 取得固定開場訊息（使用 training 的 day 和 persona）
            opening_message = self.get_opening_message(
                user_training.current_day,
                user_training.persona,
                course_version
            )

            # 發送 LINE 訊息
            self._send_push_message(
                user_id=user.line_user_id,
                message=opening_message
            )

            # 記錄推送
            push_log = PushLog(
                user_id=user.id,
                push_date=date.today(),
                training_day=user_training.current_day,
                push_message=opening_message,
                responded=False
            )
            self.db.add(push_log)

            # 更新最後推送時間
            user_training.last_push_at = datetime.now(timezone.utc)

            self.db.commit()

            return {
                "user_id": user.id,
                "training_id": user_training.id,
                "line_user_id": user.line_user_id,
                "status": "success",
                "training_day": user_training.current_day,
                "message_preview": opening_message[:50] + "..."
            }

        except Exception as e:
            return {
                "user_id": user.id,
                "training_id": user_training.id,
                "line_user_id": user.line_user_id,
                "status": "error",
                "reason": str(e)
            }

    def push_daily_training(self) -> dict:
        """
        執行每日訓練推送（新版：使用 UserTraining）

        Returns:
            dict: 推送結果摘要
        """
        trainings = self.get_active_trainings_to_push()

        results = {
            "push_time": datetime.now(timezone.utc).isoformat(),
            "total_trainings": len(trainings),
            "success": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }

        for training in trainings:
            result = self.push_to_training(training)
            results["details"].append(result)

            if result["status"] == "success":
                results["success"] += 1
            elif result["status"] == "skipped":
                results["skipped"] += 1
            else:
                results["errors"] += 1

        return results

    def mark_as_responded(self, user_id: int) -> bool:
        """
        標記用戶已回覆今天的推送

        Args:
            user_id: 用戶 ID

        Returns:
            bool: 是否成功標記
        """
        today = date.today()
        push_log = (
            self.db.query(PushLog)
            .filter(
                and_(
                    PushLog.user_id == user_id,
                    PushLog.push_date == today,
                    PushLog.responded == False
                )
            )
            .first()
        )

        if push_log:
            push_log.responded = True
            push_log.responded_at = datetime.now(timezone.utc)
            self.db.commit()
            return True

        return False

    def get_unresponded_pushes(self, days: int = 7) -> list[dict]:
        """
        取得未回覆的推送記錄（供主管查看）

        Args:
            days: 查詢最近幾天的記錄

        Returns:
            list: 未回覆的推送記錄
        """
        from datetime import timedelta

        start_date = date.today() - timedelta(days=days)

        logs = (
            self.db.query(PushLog)
            .filter(
                and_(
                    PushLog.push_date >= start_date,
                    PushLog.responded == False
                )
            )
            .order_by(PushLog.push_date.desc(), PushLog.created_at.desc())
            .all()
        )

        return [
            {
                "id": log.id,
                "user_id": log.user_id,
                "user_name": log.user.name if log.user else None,
                "line_user_id": log.user.line_user_id if log.user else None,
                "push_date": log.push_date.isoformat(),
                "training_day": log.training_day,
                "push_message": log.push_message,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]

    def get_push_stats(self) -> dict:
        """取得推送統計資料"""
        from sqlalchemy import func
        from datetime import timedelta

        today = date.today()
        week_ago = today - timedelta(days=7)

        # 今日推送統計
        today_total = self.db.query(PushLog).filter(PushLog.push_date == today).count()
        today_responded = self.db.query(PushLog).filter(
            and_(PushLog.push_date == today, PushLog.responded == True)
        ).count()

        # 本週推送統計
        week_total = self.db.query(PushLog).filter(PushLog.push_date >= week_ago).count()
        week_responded = self.db.query(PushLog).filter(
            and_(PushLog.push_date >= week_ago, PushLog.responded == True)
        ).count()

        return {
            "today": {
                "total": today_total,
                "responded": today_responded,
                "unresponded": today_total - today_responded,
                "response_rate": round(today_responded / today_total * 100, 1) if today_total > 0 else 0
            },
            "week": {
                "total": week_total,
                "responded": week_responded,
                "unresponded": week_total - week_responded,
                "response_rate": round(week_responded / week_total * 100, 1) if week_total > 0 else 0
            }
        }
