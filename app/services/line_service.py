from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from sqlalchemy.orm import Session
import json

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

    def handle_message(self, event: MessageEvent, db: Session) -> dict:
        """
        處理收到的 LINE 訊息

        Args:
            event: LINE MessageEvent
            db: 資料庫 Session

        Returns:
            dict: {"type": "text" | "flex", "content": ...}
        """
        # 取得用戶資訊
        line_user_id = event.source.user_id
        user_message = event.message.text

        # 初始化服務
        user_service = UserService(db)
        training_service = TrainingService(db)

        # 取得或建立用戶
        user, is_new = user_service.get_or_create_user(line_user_id)

        # 標記今日推送為已回覆（如果有的話）
        from app.services.push_service import PushService
        push_service = PushService(db)
        push_service.mark_as_responded(user.id)

        # 取得 training_id（用於重新測驗按鈕）
        training_id = None
        active_training = user.active_training
        if active_training:
            training_id = active_training.id

        # 處理訓練流程
        if is_new:
            # 新用戶：分類 Persona 並開始訓練
            result = training_service.handle_new_user(user, user_message)
        else:
            # 既有用戶：繼續訓練
            result = training_service.process_training(user, user_message)

        # 組合回覆訊息
        reply_data = self._format_reply(result, training_id)

        return reply_data

    def _format_reply(self, result, training_id: int = None) -> dict:
        """
        格式化回覆訊息

        多輪對話：
        - is_final=False: 只回覆 AI 的對話內容（純文字）
        - is_final=True 且通過: 顯示評分結果（純文字）
        - is_final=True 且未通過: 顯示評分結果 + 重新測驗按鈕（Flex Message）

        Returns:
            dict: {"type": "text" | "flex", "content": ...}
        """
        ai_response = result.ai_response

        # 基本回覆
        reply = ai_response.reply

        # 如果是最終評分
        if ai_response.is_final:
            if ai_response.pass_ and not result.is_completed:
                reply += f"\n\n✅ 通過！分數：{ai_response.score}\n"
                reply += f"📚 進度：Day {result.current_day} → Day {result.next_day}"
                if ai_response.reason:
                    reply += f"\n💬 評語：{ai_response.reason}"
                return {"type": "text", "content": reply}

            elif ai_response.pass_ and result.is_completed:
                reply += "\n\n🎉 恭喜完成所有訓練！"
                return {"type": "text", "content": reply}

            elif not ai_response.pass_:
                # 未通過：返回 Flex Message 以顯示重新測驗按鈕
                return {
                    "type": "flex",
                    "content": self._build_retry_flex(
                        reply=reply,
                        reason=ai_response.reason,
                        score=ai_response.score,
                        current_day=result.current_day,
                        training_id=training_id
                    )
                }

        # 非最終評分，純文字回覆
        return {"type": "text", "content": reply}

    def _build_retry_flex(self, reply: str, reason: str, score: int, current_day: int, training_id: int = None) -> dict:
        """建立未通過時的 Flex Message（含重新測驗按鈕）"""
        contents = [
            {
                "type": "text",
                "text": reply,
                "wrap": True,
                "size": "sm",
                "color": "#333333"
            },
            {
                "type": "separator",
                "margin": "lg"
            },
            {
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "contents": [
                    {
                        "type": "text",
                        "text": "❌ 本輪未通過",
                        "weight": "bold",
                        "size": "md",
                        "color": "#EF4444"
                    },
                    {
                        "type": "text",
                        "text": f"💡 原因：{reason}",
                        "wrap": True,
                        "size": "sm",
                        "color": "#666666",
                        "margin": "md"
                    },
                    {
                        "type": "text",
                        "text": f"📝 分數：{score}",
                        "size": "sm",
                        "color": "#666666",
                        "margin": "sm"
                    }
                ]
            }
        ]

        # 建立重新測驗按鈕
        footer_contents = []
        if training_id:
            footer_contents.append({
                "type": "button",
                "style": "primary",
                "color": "#7C3AED",
                "action": {
                    "type": "postback",
                    "label": "🔄 重新測驗",
                    "data": f"action=retry_training&training_id={training_id}&day={current_day}"
                }
            })

        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": contents
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": footer_contents
            } if footer_contents else None
        }

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

    def send_reply_flex(self, reply_token: str, alt_text: str, flex_content: dict) -> None:
        """
        發送 Flex Message 作為回覆

        Args:
            reply_token: LINE 的回覆 token
            alt_text: 替代文字
            flex_content: Flex Message JSON 內容
        """
        with ApiClient(self.configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[
                        FlexMessage(
                            alt_text=alt_text,
                            contents=FlexContainer.from_dict(flex_content)
                        )
                    ]
                )
            )

    def get_user_profile(self, user_id: str) -> dict | None:
        """
        取得 LINE 用戶資料

        Args:
            user_id: LINE User ID

        Returns:
            dict with displayName, pictureUrl, statusMessage or None if failed
        """
        try:
            with ApiClient(self.configuration) as api_client:
                messaging_api = MessagingApi(api_client)
                profile = messaging_api.get_profile(user_id)
                return {
                    "displayName": profile.display_name,
                    "pictureUrl": profile.picture_url,
                    "statusMessage": profile.status_message
                }
        except Exception as e:
            print(f"取得用戶資料失敗: {e}")
            return None

    def send_push_message(self, user_id: str, message: str) -> None:
        """
        主動推送訊息給用戶

        Args:
            user_id: LINE User ID
            message: 要發送的訊息
        """
        with ApiClient(self.configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )

    def send_flex_message(self, user_id: str, alt_text: str, flex_content: dict) -> None:
        """
        發送 Flex Message 給用戶

        Args:
            user_id: LINE User ID
            alt_text: 替代文字（在不支援 Flex Message 的環境顯示）
            flex_content: Flex Message JSON 內容
        """
        with ApiClient(self.configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[
                        FlexMessage(
                            alt_text=alt_text,
                            contents=FlexContainer.from_dict(flex_content)
                        )
                    ]
                )
            )

    def notify_managers_leave_request(self, leave_request, db=None) -> None:
        """
        通知主管有新的請假申請

        Args:
            leave_request: LeaveRequest 物件
            db: 資料庫 Session（可選，如未提供則自行建立）
        """
        from app.database import SessionLocal
        from app.models.manager import Manager

        # 如果沒有傳入 db，自行建立
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            # 從資料庫取得啟用中的主管
            managers = db.query(Manager).filter(Manager.is_active == True).all()

            if not managers:
                print("警告：未設定主管，無法發送通知")
                return

            # 建立 Flex Message 內容
            flex_content = self._build_leave_request_flex(leave_request)

            # 發送給所有啟用中的主管
            for manager in managers:
                try:
                    self.send_flex_message(
                        user_id=manager.line_user_id,
                        alt_text=f"請假申請 - {leave_request.applicant_name or '員工'}",
                        flex_content=flex_content
                    )
                    print(f"✅ 已發送請假通知給主管 {manager.name}: {manager.line_user_id}")
                except Exception as e:
                    print(f"❌ 發送請假通知失敗 ({manager.name}): {e}")
        finally:
            if should_close:
                db.close()

    def notify_requester_result(self, leave_request) -> None:
        """
        通知請假者審核結果

        Args:
            leave_request: LeaveRequest 物件
        """
        if not leave_request.user or not leave_request.user.line_user_id:
            print("警告：找不到請假者的 LINE ID")
            return

        user_line_id = leave_request.user.line_user_id
        flex_content = self._build_leave_result_flex(leave_request)

        try:
            self.send_flex_message(
                user_id=user_line_id,
                alt_text=f"請假審核結果 - {'已核准' if leave_request.status == 'approved' else '已拒絕'}",
                flex_content=flex_content
            )
            print(f"✅ 已發送審核結果給請假者: {user_line_id}")
        except Exception as e:
            print(f"❌ 發送審核結果失敗: {e}")

    def notify_requester_pending_proof(self, leave_request) -> None:
        """
        通知請假者需要補上證明文件

        Args:
            leave_request: LeaveRequest 物件
        """
        if not leave_request.user or not leave_request.user.line_user_id:
            print("警告：找不到請假者的 LINE ID")
            return

        user_line_id = leave_request.user.line_user_id
        settings = get_settings()

        # 計算補件期限
        deadline_str = ""
        if leave_request.proof_deadline:
            deadline_str = leave_request.proof_deadline.strftime("%Y-%m-%d %H:%M")

        flex_content = self._build_pending_proof_flex(leave_request, deadline_str, settings.site_url)

        try:
            self.send_flex_message(
                user_id=user_line_id,
                alt_text="請假申請 - 請補上證明文件",
                flex_content=flex_content
            )
            print(f"✅ 已發送補件通知給請假者: {user_line_id}")
        except Exception as e:
            print(f"❌ 發送補件通知失敗: {e}")

    def _build_pending_proof_flex(self, leave_request, deadline_str: str, site_url: str) -> dict:
        """建立待補件通知的 Flex Message"""
        content_items = [
            {
                "type": "text",
                "text": "您的病假申請需要補上證明文件",
                "size": "sm",
                "color": "#333333",
                "wrap": True
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "請假日期", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": str(leave_request.leave_date), "size": "sm", "color": "#333333", "flex": 5}
                ]
            }
        ]

        if deadline_str:
            content_items.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "補件期限", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": deadline_str, "size": "sm", "color": "#EF4444", "flex": 5, "weight": "bold"}
                ]
            })

        # 上傳連結
        upload_url = f"{site_url.rstrip('/')}/leave/upload/{leave_request.id}" if site_url else ""

        footer_contents = []
        if upload_url:
            footer_contents.append({
                "type": "button",
                "style": "primary",
                "color": "#7C3AED",
                "action": {
                    "type": "uri",
                    "label": "上傳證明文件",
                    "uri": upload_url
                }
            })

        return {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#F59E0B",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "請補上證明文件", "color": "#FFFFFF", "size": "lg", "weight": "bold"},
                    {"type": "text", "text": f"申請編號 #{leave_request.id}", "color": "#FEF3C7", "size": "sm", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": content_items
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": footer_contents
            } if footer_contents else None
        }

    def _build_leave_request_flex(self, leave_request) -> dict:
        """建立請假申請的 Flex Message"""
        leave_type_color = "#1E88E5" if leave_request.leave_type == "事假" else "#8E24AA"
        leave_type_icon = "📋" if leave_request.leave_type == "事假" else "🏥"

        # 內容區塊
        content_items = [
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "申請人", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": leave_request.applicant_name or "未填寫", "size": "sm", "color": "#333333", "flex": 5, "weight": "bold"}
                ]
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "請假類型", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": f"{leave_type_icon} {leave_request.leave_type}", "size": "sm", "color": leave_type_color, "flex": 5, "weight": "bold"}
                ]
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "請假日期", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": str(leave_request.leave_date), "size": "sm", "color": "#333333", "flex": 5, "weight": "bold"}
                ]
            }
        ]

        # 如果是事假，顯示理由
        if leave_request.leave_type == "事假" and leave_request.reason:
            content_items.append({
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "請假理由", "size": "sm", "color": "#888888"},
                    {"type": "text", "text": leave_request.reason, "size": "sm", "color": "#333333", "margin": "sm", "wrap": True}
                ]
            })

        # 如果是病假，提示有證明文件
        if leave_request.leave_type == "病假" and leave_request.proof_file:
            content_items.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "📎", "size": "sm", "flex": 0},
                    {"type": "text", "text": "已附證明文件", "size": "sm", "color": "#22C55E", "margin": "sm", "weight": "bold"}
                ]
            })
        elif leave_request.leave_type == "病假":
            content_items.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "⚠️", "size": "sm", "flex": 0},
                    {"type": "text", "text": "尚未附證明文件", "size": "sm", "color": "#F59E0B", "margin": "sm"}
                ]
            })

        # 建立 footer 按鈕
        settings = get_settings()
        footer_contents = []

        # 如果有證明文件，加入查看按鈕
        if leave_request.leave_type == "病假" and leave_request.proof_file and settings.site_url:
            proof_url = f"{settings.site_url.rstrip('/')}/static/uploads/{leave_request.proof_file}"
            footer_contents.append({
                "type": "button",
                "style": "secondary",
                "action": {
                    "type": "uri",
                    "label": "查看證明文件",
                    "uri": proof_url
                }
            })

        # 病假無證明時，加入「待補件」按鈕
        if leave_request.leave_type == "病假" and not leave_request.proof_file:
            footer_contents.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#22C55E",
                        "action": {
                            "type": "postback",
                            "label": "✓ 核准",
                            "data": f"action=approve_leave&leave_id={leave_request.id}"
                        }
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#F59E0B",
                        "action": {
                            "type": "postback",
                            "label": "待補件",
                            "data": f"action=pending_proof&leave_id={leave_request.id}"
                        }
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#EF4444",
                        "action": {
                            "type": "postback",
                            "label": "✗ 拒絕",
                            "data": f"action=reject_leave&leave_id={leave_request.id}"
                        }
                    }
                ]
            })
        else:
            # 核准/拒絕按鈕（事假或已有證明的病假）
            footer_contents.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#22C55E",
                        "action": {
                            "type": "postback",
                            "label": "✓ 核准",
                            "data": f"action=approve_leave&leave_id={leave_request.id}"
                        }
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#EF4444",
                        "action": {
                            "type": "postback",
                            "label": "✗ 拒絕",
                            "data": f"action=reject_leave&leave_id={leave_request.id}"
                        }
                    }
                ]
            })

        return {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#7C3AED",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "請假申請", "color": "#FFFFFF", "size": "lg", "weight": "bold"},
                    {"type": "text", "text": f"#{leave_request.id}", "color": "#E0E0E0", "size": "sm", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": content_items
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": footer_contents
            }
        }

    def _build_leave_result_flex(self, leave_request) -> dict:
        """建立審核結果的 Flex Message"""
        is_approved = leave_request.status == "approved"
        status_color = "#22C55E" if is_approved else "#EF4444"
        status_text = "已核准 ✓" if is_approved else "已拒絕 ✗"

        content_items = [
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "請假類型", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": leave_request.leave_type, "size": "sm", "color": "#333333", "flex": 5}
                ]
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "請假日期", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": str(leave_request.leave_date), "size": "sm", "color": "#333333", "flex": 5}
                ]
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "審核結果", "size": "sm", "color": "#888888", "flex": 2},
                    {"type": "text", "text": status_text, "size": "sm", "color": status_color, "flex": 5, "weight": "bold"}
                ]
            }
        ]

        # 如果有審核備註
        if leave_request.reviewer_note:
            content_items.append({
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "審核備註", "size": "sm", "color": "#888888"},
                    {"type": "text", "text": leave_request.reviewer_note, "size": "sm", "color": "#333333", "margin": "sm", "wrap": True}
                ]
            })

        return {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": status_color,
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "請假審核結果", "color": "#FFFFFF", "size": "lg", "weight": "bold"},
                    {"type": "text", "text": f"申請編號 #{leave_request.id}", "color": "#E0E0E0", "size": "sm", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": content_items
            }
        }
