from fastapi import APIRouter, Request, HTTPException, Depends
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.line_service import LineService
from app.services.user_service import UserService
from app.services.push_service import PushService

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
            1. 建立用戶記錄
            2. 立即發送 Day 0 開場白
            3. 記錄推送
            """
            line_user_id = event.source.user_id

            # 建立用戶
            user_service = UserService(db)
            user, is_new = user_service.get_or_create_user(line_user_id)

            if is_new:
                # 新用戶：立即推送 Day 0 開場白
                push_service = PushService(db)
                push_service.push_to_user(user)
                print(f"✅ 新用戶加入: {line_user_id}, 已發送 Day 0 開場白")
            else:
                # 舊用戶回歸，發送當前進度的課程
                push_service = PushService(db)
                push_service.push_to_user(user)
                print(f"👋 舊用戶回歸: {line_user_id}, Day {user.current_day}")

        # 註冊訊息處理器
        @handler.add(MessageEvent, message=TextMessageContent)
        def handle_text_message(event: MessageEvent):
            """處理文字訊息"""
            # 處理訊息並取得回覆
            reply_message = line_service.handle_message(event, db)

            # 發送回覆
            line_service.send_reply(event.reply_token, reply_message)

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
