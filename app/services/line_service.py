from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.user_service import UserService
from app.services.training_service import TrainingService


class LineService:
    """LINE 訊息處理服務"""

    def __init__(self):
        settings = get_settings()
        self.handler = WebhookHandler(settings.line_channel_secret)
        self.configuration = Configuration(
            access_token=settings.line_channel_access_token
        )

    def get_handler(self) -> WebhookHandler:
        """取得 Webhook Handler"""
        return self.handler

    def handle_message(self, event: MessageEvent, db: Session) -> str:
        """
        處理收到的 LINE 訊息

        Args:
            event: LINE MessageEvent
            db: 資料庫 Session

        Returns:
            str: 要回覆的訊息
        """
        # 取得用戶資訊
        line_user_id = event.source.user_id
        user_message = event.message.text

        # 初始化服務
        user_service = UserService(db)
        training_service = TrainingService(db)

        # 取得或建立用戶
        user, is_new = user_service.get_or_create_user(line_user_id)

        # 處理訓練流程
        if is_new:
            # 新用戶：分類 Persona 並開始訓練
            result = training_service.handle_new_user(user, user_message)
        else:
            # 既有用戶：繼續訓練
            result = training_service.process_training(user, user_message)

        # 組合回覆訊息
        reply_message = self._format_reply(result)

        return reply_message

    def _format_reply(self, result) -> str:
        """
        格式化回覆訊息

        包含：
        1. AI 的回覆內容
        2. 如果通過，顯示進度資訊
        """
        ai_response = result.ai_response

        # 基本回覆
        reply = ai_response.reply

        # 如果通過，加上進度資訊
        if ai_response.pass_ and not result.is_completed:
            reply += f"\n\n✅ 通過！分數：{ai_response.score}\n"
            reply += f"📚 進度：Day {result.current_day} → Day {result.next_day}"
        elif ai_response.pass_ and result.is_completed:
            reply += "\n\n🎉 恭喜完成所有訓練！"
        elif not ai_response.pass_:
            reply += f"\n\n❌ 未通過，請再試一次\n"
            reply += f"💡 提示：{ai_response.reason}"

        return reply

    def send_reply(self, reply_token: str, message: str) -> None:
        """
        發送回覆訊息

        Args:
            reply_token: LINE 的回覆 token
            message: 要發送的訊息
        """
        with ApiClient(self.configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message)]
                )
            )

    def send_push_message(self, user_id: str, message: str) -> None:
        """
        主動推送訊息給用戶

        Args:
            user_id: LINE User ID
            message: 要發送的訊息
        """
        from linebot.v3.messaging import PushMessageRequest

        with ApiClient(self.configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )
