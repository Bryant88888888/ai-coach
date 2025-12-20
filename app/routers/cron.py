from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.config import get_settings
from app.services.push_service import PushService

router = APIRouter(prefix="/cron", tags=["排程任務"])


def verify_cron_secret(x_cron_secret: Optional[str] = Header(None)):
    """
    驗證 Cron Job 的密鑰（可選）

    如果設定了 CRON_SECRET 環境變數，則需要驗證
    """
    settings = get_settings()
    cron_secret = getattr(settings, 'cron_secret', None)

    if cron_secret and x_cron_secret != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid cron secret")


@router.post("/daily-push")
async def daily_push(
    db: Session = Depends(get_db),
    _: None = Depends(verify_cron_secret)
):
    """
    每日訓練推送

    此端點由 Render Cron Job 每天 19:00 (UTC+8) 呼叫
    - 取得所有活躍且未完成訓練的用戶
    - 根據每個用戶的 current_day 推送對應的訓練內容
    - 記錄推送歷史

    Render Cron 設定：
    - Schedule: 0 11 * * * (UTC 時間 11:00 = 台灣時間 19:00)
    - Command: curl -X POST https://your-app.onrender.com/cron/daily-push
    """
    push_service = PushService(db)
    result = push_service.push_daily_training()

    return {
        "status": "completed",
        "result": result
    }


@router.get("/push-stats")
async def get_push_stats(
    db: Session = Depends(get_db),
    _: None = Depends(verify_cron_secret)
):
    """取得推送統計資料"""
    push_service = PushService(db)
    return push_service.get_push_stats()


@router.get("/unresponded")
async def get_unresponded_pushes(
    days: int = 7,
    db: Session = Depends(get_db),
    _: None = Depends(verify_cron_secret)
):
    """
    取得未回覆的推送記錄

    Args:
        days: 查詢最近幾天的記錄（預設 7 天）
    """
    push_service = PushService(db)
    return push_service.get_unresponded_pushes(days=days)


@router.post("/test-push/{line_user_id}")
async def test_push_single_user(
    line_user_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_cron_secret)
):
    """
    測試推送給單一用戶（僅供測試）

    Args:
        line_user_id: LINE User ID
    """
    from app.services.user_service import UserService

    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    push_service = PushService(db)
    result = push_service.push_to_user(user)

    return {
        "status": "completed",
        "result": result
    }
