from fastapi import APIRouter, Request, HTTPException, Depends
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent, PostbackEvent
from sqlalchemy.orm import Session
from datetime import datetime
from urllib.parse import parse_qs

from app.database import get_db
from app.services.line_service import LineService
from app.services.user_service import UserService
from app.services.push_service import PushService
from app.models.leave_request import LeaveRequest, LeaveStatus

router = APIRouter(prefix="/webhook", tags=["LINE Webhook"])

# 初始化 LINE 服務
line_service = LineService()


@router.post("")
async def line_webhook(request: Request, db: Session = Depends(get_db)):
    """
    LINE Webhook 端點

    接收 LINE 平台發送的訊息事件，進行處理並回覆
    """
    # 取得簽章和請求內容
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_str = body.decode("utf-8")

    # 驗證簽章
    handler = line_service.get_handler()

    try:
        # 註冊加好友事件處理器
        @handler.add(FollowEvent)
        def handle_follow(event: FollowEvent):
            """
            處理加好友事件

            當用戶加入好友時：
            1. 取得 LINE 用戶資料
            2. 建立用戶記錄
            3. 發送歡迎訊息（不自動開始訓練）
            """
            line_user_id = event.source.user_id

            # 取得 LINE 用戶資料
            profile = line_service.get_user_profile(line_user_id)
            display_name = profile.get("displayName") if profile else None
            picture_url = profile.get("pictureUrl") if profile else None

            # 建立用戶
            user_service = UserService(db)
            user, is_new = user_service.get_or_create_user(
                line_user_id,
                line_display_name=display_name,
                line_picture_url=picture_url
            )

            # 發送歡迎訊息
            welcome_message = "歡迎加入！您的帳號已建立，請等待管理員為您安排訓練課程。"

            if is_new:
                line_service.send_reply(event.reply_token, welcome_message)
                print(f"✅ 新用戶加入: {line_user_id} ({display_name})")
            else:
                # 舊用戶回歸：檢查是否有進行中的訓練
                active_training = user.active_training
                if active_training:
                    # 有進行中的訓練，推送當前進度
                    push_service = PushService(db)
                    push_service.push_to_training(active_training)
                    print(f"👋 舊用戶回歸: {line_user_id} ({display_name}), Day {active_training.current_day}")
                else:
                    line_service.send_reply(event.reply_token, "歡迎回來！請等待管理員為您安排訓練課程。")
                    print(f"👋 舊用戶回歸（無訓練）: {line_user_id} ({display_name})")

        # 註冊訊息處理器
        @handler.add(MessageEvent, message=TextMessageContent)
        def handle_text_message(event: MessageEvent):
            """處理文字訊息 - 確保每則訊息都會回覆"""
            try:
                # 處理訊息並取得回覆
                reply_data = line_service.handle_message(event, db)

                # 根據類型發送回覆
                if reply_data["type"] == "flex":
                    line_service.send_reply_flex(
                        event.reply_token,
                        "訓練結果",
                        reply_data["content"]
                    )
                else:
                    line_service.send_reply(event.reply_token, reply_data["content"])

            except Exception as e:
                # 發生錯誤時也要回覆，避免用戶等不到回應
                print(f"❌ 處理訊息失敗: {e}")
                error_reply = "抱歉，系統處理時發生錯誤，請稍後再試。如持續發生問題，請聯繫管理員。"
                try:
                    line_service.send_reply(event.reply_token, error_reply)
                except Exception as reply_error:
                    print(f"❌ 發送錯誤回覆也失敗: {reply_error}")

        # 註冊 Postback 處理器（用於請假審核按鈕和訓練開始按鈕）
        @handler.add(PostbackEvent)
        def handle_postback(event: PostbackEvent):
            """處理 Postback 事件（按鈕點擊）"""
            data = parse_qs(event.postback.data)
            action = data.get("action", [None])[0]

            # 處理訓練開始按鈕
            if action == "start_training":
                training_id = data.get("training_id", [None])[0]
                day = data.get("day", [None])[0]
                if training_id:
                    try:
                        training_id = int(training_id)
                        day = int(day) if day else None
                        push_service = PushService(db)
                        result = push_service.send_training_opening(training_id, day=day)

                        if result["status"] == "success":
                            # 開場訊息會由 push_service 發送（用 Push）
                            # 這裡用 Reply 回覆一個簡短提示
                            line_service.send_reply(
                                event.reply_token,
                                "✨ 課程開始！請閱讀上方的情境，然後回覆你的回應。"
                            )
                        else:
                            reason = str(result.get('reason', '未知錯誤'))
                            if 'monthly limit' in reason.lower() or '429' in reason:
                                line_service.send_reply(
                                    event.reply_token,
                                    "⚠️ 系統訊息額度已達上限，請稍後再試或聯繫管理員。"
                                )
                            else:
                                line_service.send_reply(
                                    event.reply_token,
                                    "❌ 啟動失敗，請稍後再試。"
                                )
                    except Exception as e:
                        print(f"處理訓練開始失敗: {e}")
                        error_msg = str(e).lower()
                        if 'monthly limit' in error_msg or '429' in error_msg:
                            line_service.send_reply(
                                event.reply_token,
                                "⚠️ 系統訊息額度已達上限，請稍後再試或聯繫管理員。"
                            )
                        else:
                            line_service.send_reply(
                                event.reply_token,
                                "❌ 發生錯誤，請稍後再試。"
                            )
                return

            # 處理重新測驗按鈕
            if action == "retry_training":
                training_id = data.get("training_id", [None])[0]
                if training_id:
                    try:
                        training_id = int(training_id)
                        push_service = PushService(db)
                        result = push_service.retry_training(training_id)

                        if result["status"] == "success":
                            line_service.send_reply(
                                event.reply_token,
                                "🔄 重新開始！請閱讀上方的情境，然後回覆你的回應。"
                            )
                        else:
                            # 檢查是否是 LINE API 限制
                            reason = str(result.get('reason', '未知錯誤'))
                            if 'monthly limit' in reason.lower() or '429' in reason:
                                line_service.send_reply(
                                    event.reply_token,
                                    "⚠️ 系統訊息額度已達上限，請稍後再試或聯繫管理員。"
                                )
                            else:
                                line_service.send_reply(
                                    event.reply_token,
                                    "❌ 重新測驗失敗，請稍後再試。"
                                )
                    except Exception as e:
                        print(f"處理重新測驗失敗: {e}")
                        error_msg = str(e).lower()
                        if 'monthly limit' in error_msg or '429' in error_msg:
                            line_service.send_reply(
                                event.reply_token,
                                "⚠️ 系統訊息額度已達上限，請稍後再試或聯繫管理員。"
                            )
                        else:
                            line_service.send_reply(
                                event.reply_token,
                                "❌ 發生錯誤，請稍後再試。"
                            )
                return

            # 處理請假審核按鈕
            leave_id = data.get("leave_id", [None])[0]
            if action in ["approve_leave", "reject_leave", "pending_proof"] and leave_id:
                try:
                    from datetime import timedelta

                    leave_id = int(leave_id)
                    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()

                    if not leave_request:
                        line_service.send_reply(event.reply_token, "❌ 找不到此請假申請")
                        return

                    # 檢查是否已審核（待補件狀態可再次審核）
                    if leave_request.status not in [LeaveStatus.PENDING.value, LeaveStatus.PENDING_PROOF.value]:
                        status_text = "已核准" if leave_request.status == LeaveStatus.APPROVED.value else "已拒絕"
                        line_service.send_reply(event.reply_token, f"ℹ️ 此申請{status_text}，無需再次審核")
                        return

                    applicant_name = leave_request.applicant_name or "員工"

                    # 更新狀態
                    if action == "approve_leave":
                        leave_request.status = LeaveStatus.APPROVED.value
                        leave_request.reviewed_at = datetime.now()
                        result_text = "✅ 已核准"
                        db.commit()

                        # 通知請假者審核結果
                        line_service.notify_requester_result(leave_request)

                    elif action == "reject_leave":
                        leave_request.status = LeaveStatus.REJECTED.value
                        leave_request.reviewed_at = datetime.now()
                        result_text = "❌ 已拒絕"
                        db.commit()

                        # 通知請假者審核結果
                        line_service.notify_requester_result(leave_request)

                    elif action == "pending_proof":
                        # 設定待補件狀態和 7 天期限
                        leave_request.status = LeaveStatus.PENDING_PROOF.value
                        leave_request.proof_deadline = datetime.now() + timedelta(days=7)
                        result_text = "⏳ 已設為待補件"
                        db.commit()

                        # 通知請假者需要補件
                        line_service.notify_requester_pending_proof(leave_request)

                    # 回覆主管
                    line_service.send_reply(
                        event.reply_token,
                        f"{result_text} {applicant_name} 的請假申請（{leave_request.leave_date}）"
                    )

                except Exception as e:
                    print(f"處理請假審核失敗: {e}")
                    line_service.send_reply(event.reply_token, f"❌ 處理失敗：{str(e)}")

        # 處理 Webhook 事件
        handler.handle(body_str, signature)

    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        # 記錯錯誤但不中斷
        print(f"Error handling webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@router.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy", "service": "LINE Webhook"}
