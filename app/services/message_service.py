from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.message import Message
from app.models.user import User
from app.schemas.ai_response import AIResponse
from typing import Optional


class MessageService:
    """對話記錄服務"""

    def __init__(self, db: Session):
        self.db = db

    def save_message(
        self,
        user: User,
        user_message: str,
        ai_response: AIResponse,
        training_day: int
    ) -> Message:
        """
        儲存對話記錄

        Args:
            user: 用戶物件
            user_message: 用戶輸入的訊息
            ai_response: AI 回應
            training_day: 當時的訓練天數

        Returns:
            Message: 儲存的對話記錄
        """
        message = Message(
            user_id=user.id,
            training_day=training_day,
            user_message=user_message,
            ai_reply=ai_response.reply,
            passed=ai_response.pass_,
            score=ai_response.score,
            reason=ai_response.reason
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_user_messages(
        self,
        user_id: int,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> list[Message]:
        """取得用戶的所有對話記錄"""
        query = (
            self.db.query(Message)
            .filter(Message.user_id == user_id)
            .order_by(Message.created_at.desc())
            .offset(offset)
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_user_messages_by_day(self, user_id: int, day: int) -> list[Message]:
        """取得用戶某一天的對話記錄"""
        return (
            self.db.query(Message)
            .filter(Message.user_id == user_id, Message.training_day == day)
            .order_by(Message.created_at.asc())
            .all()
        )

    def get_message_count(self, user_id: int) -> int:
        """取得用戶的對話總數"""
        return self.db.query(Message).filter(Message.user_id == user_id).count()

    def get_user_stats(self, user_id: int) -> dict:
        """取得用戶的對話統計"""
        messages = self.db.query(Message).filter(Message.user_id == user_id).all()

        if not messages:
            return {
                "total_messages": 0,
                "passed_count": 0,
                "failed_count": 0,
                "pass_rate": 0.0,
                "average_score": 0.0
            }

        total = len(messages)
        passed = sum(1 for m in messages if m.passed)
        failed = total - passed
        avg_score = sum(m.score for m in messages) / total

        return {
            "total_messages": total,
            "passed_count": passed,
            "failed_count": failed,
            "pass_rate": round(passed / total * 100, 1),
            "average_score": round(avg_score, 1)
        }

    def get_all_messages(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> list[Message]:
        """取得所有對話記錄（後台用）"""
        return (
            self.db.query(Message)
            .order_by(Message.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_recent_messages(self, hours: int = 24) -> list[Message]:
        """取得最近 N 小時的對話記錄"""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(hours=hours)
        return (
            self.db.query(Message)
            .filter(Message.created_at >= cutoff)
            .order_by(Message.created_at.desc())
            .all()
        )
