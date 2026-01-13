from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.database import get_db, SessionLocal
from app.config import get_settings
from app.services.push_service import PushService

router = APIRouter(prefix="/cron", tags=["排程任務"])


def run_daily_push_background():
    """背景執行每日推送（獨立的 DB session）"""
    db = SessionLocal()
    try:
        push_service = PushService(db)
        result = push_service.push_daily_training()
        print(f"✅ 每日推送完成: {result}")
    except Exception as e:
        print(f"❌ 每日推送失敗: {e}")
    finally:
        db.close()


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
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_cron_secret)
):
    """
    每日訓練推送（背景執行）

    此端點由 Render Cron Job 每天 17:30 (UTC+8) 呼叫
    - 立即回傳，推送在背景執行
    - 取得所有活躍且未完成訓練的用戶
    - 根據每個用戶的 current_day 推送對應的訓練內容
    - 記錄推送歷史
    """
    # 加入背景任務，立即回傳
    background_tasks.add_task(run_daily_push_background)

    return {
        "status": "started",
        "message": "每日推送已在背景執行",
        "started_at": datetime.now().isoformat()
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


@router.get("/analyze-messages")
async def analyze_messages(
    db: Session = Depends(get_db),
    _: None = Depends(verify_cron_secret)
):
    """
    分析對話紀錄，找出潛在問題
    """
    from app.models.message import Message
    from app.models.user import User
    from collections import defaultdict

    # 取得所有對話
    messages = db.query(Message).order_by(Message.created_at.desc()).limit(500).all()

    analysis = {
        "total_messages": len(messages),
        "pass_count": 0,
        "fail_count": 0,
        "avg_score": 0,
        "issues": [],
        "samples": {
            "failed": [],
            "low_score": [],
            "recent": []
        },
        "by_day": defaultdict(lambda: {"count": 0, "pass": 0, "fail": 0}),
        "ai_behavior_issues": []
    }

    scores = []
    for msg in messages:
        # 統計通過/失敗
        if msg.passed:
            analysis["pass_count"] += 1
        else:
            analysis["fail_count"] += 1

        if msg.score:
            scores.append(msg.score)

        # 按天數統計
        day_stats = analysis["by_day"][msg.training_day]
        day_stats["count"] += 1
        if msg.passed:
            day_stats["pass"] += 1
        else:
            day_stats["fail"] += 1

        # 收集失敗樣本
        if not msg.passed and len(analysis["samples"]["failed"]) < 10:
            analysis["samples"]["failed"].append({
                "day": msg.training_day,
                "user_msg": msg.user_message[:100] if msg.user_message else "",
                "ai_reply": msg.ai_reply[:200] if msg.ai_reply else "",
                "score": msg.score,
                "reason": msg.reason
            })

        # 收集低分樣本
        if msg.score and msg.score < 60 and len(analysis["samples"]["low_score"]) < 10:
            analysis["samples"]["low_score"].append({
                "day": msg.training_day,
                "user_msg": msg.user_message[:100] if msg.user_message else "",
                "ai_reply": msg.ai_reply[:200] if msg.ai_reply else "",
                "score": msg.score,
                "reason": msg.reason
            })

        # 檢查 AI 行為問題
        if msg.ai_reply:
            ai_reply = msg.ai_reply.lower()
            # 檢查 AI 是否在吵架
            if any(word in ai_reply for word in ["你錯了", "不對", "你不懂", "你應該"]):
                if len(analysis["ai_behavior_issues"]) < 5:
                    analysis["ai_behavior_issues"].append({
                        "type": "arguing",
                        "ai_reply": msg.ai_reply[:200],
                        "day": msg.training_day
                    })
            # 檢查 AI 是否用外部資訊挑戰
            if any(phrase in ai_reply for phrase in ["我聽說", "別家", "其他公司", "外面"]):
                if len(analysis["ai_behavior_issues"]) < 5:
                    analysis["ai_behavior_issues"].append({
                        "type": "external_challenge",
                        "ai_reply": msg.ai_reply[:200],
                        "day": msg.training_day
                    })

    # 計算平均分數
    if scores:
        analysis["avg_score"] = round(sum(scores) / len(scores), 1)

    # 轉換 defaultdict 為普通 dict
    analysis["by_day"] = dict(analysis["by_day"])

    # 最近 5 則對話
    for msg in messages[:5]:
        analysis["samples"]["recent"].append({
            "day": msg.training_day,
            "user_msg": msg.user_message[:100] if msg.user_message else "",
            "ai_reply": msg.ai_reply[:200] if msg.ai_reply else "",
            "passed": msg.passed,
            "score": msg.score,
            "created_at": msg.created_at.isoformat() if msg.created_at else None
        })

    # 識別問題
    if analysis["fail_count"] > analysis["pass_count"]:
        analysis["issues"].append("失敗率過高，可能 AI 評分太嚴格")

    if analysis["avg_score"] < 60:
        analysis["issues"].append("平均分數偏低，建議檢視評分標準")

    if analysis["ai_behavior_issues"]:
        analysis["issues"].append(f"發現 {len(analysis['ai_behavior_issues'])} 則 AI 行為問題")

    return analysis
