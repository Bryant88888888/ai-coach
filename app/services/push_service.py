from datetime import date, datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_
from anthropic import Anthropic
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)

from app.config import get_settings
from app.models.user import User, UserStatus
from app.models.push_log import PushLog
from app.data.days_data import get_day_data

# 訓練的最後一天
MAX_TRAINING_DAY = 14


class PushService:
    """每日推送服務"""

    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
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
        """取得需要推送的用戶列表"""
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

    def generate_opening_message(self, day: int, persona: str | None) -> str:
        """
        使用 AI 生成當日訓練的開場訊息

        根據每天的主題，生成一個擬真的客人/教官開場白
        """
        day_data = get_day_data(day)
        if not day_data:
            return "你好，今天的訓練開始了！"

        # 建立系統提示，讓 AI 生成開場白
        system_prompt = f"""你是一個角色扮演專家。根據以下訓練主題，生成一個開場白。

## 訓練主題：{day_data['title']}
## 訓練目標：{day_data['goal']}

## 任務
請生成一個開場訊息，這個訊息會發送給正在接受訓練的新人。

根據不同的訓練天數，你要扮演不同的角色：
- Day 0-6：扮演「資深訓練教官」，用溫和但專業的口吻開始今天的教學
- Day 7-12：扮演「模擬客人」，用自然的口吻開始對話
- Day 13-14：扮演「刁難型客人」，用試探的口吻開始對話

## 用戶經驗
{"無經驗新人 - 請更溫和親切" if persona and "A" in persona else "有經驗新人 - 可以直接專業"}

## 規則
1. 只輸出開場白內容，不要有任何其他說明
2. 開場白要自然、口語化，像真人說話
3. 長度控制在 50-150 字之間
4. 不要使用 emoji
5. 如果是教官角色，可以適當提及今天要教什麼
6. 如果是客人角色，就直接開始模擬對話
"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"請生成 Day {day}「{day_data['title']}」的開場白"}
            ],
        )

        return response.content[0].text.strip()

    def push_to_user(self, user: User) -> dict:
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
            # 生成開場訊息
            opening_message = self.generate_opening_message(
                user.current_day,
                user.persona
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

    def push_daily_training(self) -> dict:
        """
        執行每日訓練推送

        Returns:
            dict: 推送結果摘要
        """
        users = self.get_users_to_push()

        results = {
            "push_time": datetime.now(timezone.utc).isoformat(),
            "total_users": len(users),
            "success": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }

        for user in users:
            result = self.push_to_user(user)
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
