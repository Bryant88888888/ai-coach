from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.services.user_service import UserService
from app.services.training_service import TrainingService
from app.services.message_service import MessageService
from app.schemas.user import UserResponse
from app.schemas.message import MessageResponse, ConversationHistory, MessageStats
from app.data.days_data import get_all_days, get_day_data

router = APIRouter(prefix="/admin", tags=["管理後台"])


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(db: Session = Depends(get_db)):
    """取得所有用戶列表"""
    user_service = UserService(db)
    users = user_service.get_all_users()
    return users


@router.get("/users/{line_user_id}")
async def get_user_by_line_id(line_user_id: str, db: Session = Depends(get_db)):
    """透過 LINE User ID 取得用戶資訊"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse.model_validate(user)


@router.get("/users/{line_user_id}/progress")
async def get_user_progress(line_user_id: str, db: Session = Depends(get_db)):
    """取得用戶訓練進度"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    training_service = TrainingService(db)
    return training_service.get_progress_summary(user)


@router.get("/days")
async def get_all_training_days():
    """取得所有訓練課程列表"""
    days = get_all_days()
    # 只返回摘要資訊，不包含完整 prompt
    return [
        {
            "day": d["day"],
            "title": d["title"],
            "goal": d["goal"]
        }
        for d in days
    ]


@router.get("/days/{day}")
async def get_training_day(day: int):
    """取得指定天數的課程資料"""
    day_data = get_day_data(day)

    if not day_data:
        raise HTTPException(status_code=404, detail=f"Day {day} not found")

    return day_data


@router.get("/stats")
async def get_training_stats(db: Session = Depends(get_db)):
    """取得訓練統計資料"""
    user_service = UserService(db)
    users = user_service.get_all_users()

    total_users = len(users)
    active_users = len([u for u in users if u.status.value == "Active"])
    completed_users = len([u for u in users if u.current_day > 14])

    # 各天數的用戶分佈
    day_distribution = {}
    for user in users:
        day = user.current_day
        day_distribution[day] = day_distribution.get(day, 0) + 1

    # Persona 分佈
    persona_distribution = {"A_無經驗": 0, "B_有經驗": 0, "未分類": 0}
    for user in users:
        if user.persona:
            persona_distribution[user.persona.value] = (
                persona_distribution.get(user.persona.value, 0) + 1
            )
        else:
            persona_distribution["未分類"] += 1

    return {
        "total_users": total_users,
        "active_users": active_users,
        "completed_users": completed_users,
        "completion_rate": round(completed_users / total_users * 100, 1) if total_users > 0 else 0,
        "day_distribution": day_distribution,
        "persona_distribution": persona_distribution
    }


# ==================== 對話記錄 API ====================

@router.get("/messages", response_model=List[MessageResponse])
async def get_all_messages(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """取得所有對話記錄（最新在前）"""
    message_service = MessageService(db)
    messages = message_service.get_all_messages(limit=limit, offset=offset)
    return messages


@router.get("/messages/recent")
async def get_recent_messages(
    hours: int = Query(default=24, le=168),
    db: Session = Depends(get_db)
):
    """取得最近 N 小時的對話記錄"""
    message_service = MessageService(db)
    messages = message_service.get_recent_messages(hours=hours)
    return [MessageResponse.model_validate(m) for m in messages]


@router.get("/users/{line_user_id}/messages", response_model=ConversationHistory)
async def get_user_messages(
    line_user_id: str,
    limit: Optional[int] = Query(default=None, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """取得特定用戶的對話記錄"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    message_service = MessageService(db)
    messages = message_service.get_user_messages(
        user_id=user.id,
        limit=limit,
        offset=offset
    )

    return ConversationHistory(
        user_id=user.id,
        line_user_id=user.line_user_id,
        user_name=user.name,
        current_day=user.current_day,
        total_messages=message_service.get_message_count(user.id),
        messages=[MessageResponse.model_validate(m) for m in messages]
    )


@router.get("/users/{line_user_id}/messages/day/{day}", response_model=List[MessageResponse])
async def get_user_messages_by_day(
    line_user_id: str,
    day: int,
    db: Session = Depends(get_db)
):
    """取得用戶某一天的對話記錄"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    message_service = MessageService(db)
    messages = message_service.get_user_messages_by_day(user.id, day)
    return [MessageResponse.model_validate(m) for m in messages]


@router.get("/users/{line_user_id}/stats", response_model=MessageStats)
async def get_user_message_stats(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得用戶的對話統計"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    message_service = MessageService(db)
    return message_service.get_user_stats(user.id)
