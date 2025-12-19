from fastapi import APIRouter, Request, HTTPException, Depends
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.line_service import LineService

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
        # 記錄錯誤但不中斷
        print(f"Error handling webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}


@router.get("/health")
async def health_check():
    """健康檢查端點"""
    return {"status": "healthy", "service": "LINE Webhook"}
