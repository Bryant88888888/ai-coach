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
            3. 立即發送 Day 0 開場白
            4. 記錄推送
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

            if is_new:
                # 新用戶：立即推送 Day 0 開場白
                push_service = PushService(db)
                push_service.push_to_user(user)
                print(f"✅ 新用戶加入: {line_user_id} ({display_name}), 已發送 Day 0 開場白")
            else:
                # 舊用戶回歸，發送當前進度的課程
                push_service = PushService(db)
                push_service.push_to_user(user)
                print(f"👋 舊用戶回歸: {line_user_id} ({display_name}), Day {user.current_day}")

        # 註冊訊息處理器
        @handler.add(MessageEvent, message=TextMessageContent)
        def handle_text_message(event: MessageEvent):
            """處理文字訊息"""
            # 處理訊息並取得回覆
            reply_message = line_service.handle_message(event, db)

            # 發送回覆
            line_service.send_reply(event.reply_token, reply_message)

        # 註冊 Postback 處理器（用於請假審核按鈕）
        @handler.add(PostbackEvent)
        def handle_postback(event: PostbackEvent):
            """處理 Postback 事件（按鈕點擊）"""
            data = parse_qs(event.postback.data)
            action = data.get("action", [None])[0]
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
