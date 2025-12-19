from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.services.user_service import UserService
from app.services.message_service import MessageService
from app.data.days_data import get_all_days, get_day_data

# 設定模板目錄
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(tags=["前端頁面"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """儀表板首頁"""
    user_service = UserService(db)
    message_service = MessageService(db)

    users = user_service.get_all_users()

    # 計算統計資料
    total_users = len(users)
    active_users = len([u for u in users if u.status == "Active"])
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
            persona_distribution[user.persona] = (
                persona_distribution.get(user.persona, 0) + 1
            )
        else:
            persona_distribution["未分類"] += 1

    stats = {
        "total_users": total_users,
        "active_users": active_users,
        "completed_users": completed_users,
        "completion_rate": round(completed_users / total_users * 100, 1) if total_users > 0 else 0,
        "day_distribution": day_distribution,
        "persona_distribution": persona_distribution
    }

    # 取得最近對話
    recent_messages = message_service.get_recent_messages(hours=24)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "stats": stats,
        "recent_messages": recent_messages
    })


@router.get("/dashboard/users", response_class=HTMLResponse)
async def users_list(request: Request, db: Session = Depends(get_db)):
    """用戶列表頁面"""
    user_service = UserService(db)
    users = user_service.get_all_users()

    return templates.TemplateResponse("users.html", {
        "request": request,
        "active_page": "users",
        "users": users
    })


@router.get("/dashboard/users/{line_user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, line_user_id: str, db: Session = Depends(get_db)):
    """用戶詳情頁面"""
    user_service = UserService(db)
    message_service = MessageService(db)

    user = user_service.get_user_by_line_id(line_user_id)
    if not user:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "用戶不存在"
        }, status_code=404)

    messages = message_service.get_user_messages(user.id)
    stats = message_service.get_user_stats(user.id)

    return templates.TemplateResponse("user_detail.html", {
        "request": request,
        "active_page": "users",
        "user": user,
        "messages": messages,
        "stats": stats
    })


@router.get("/dashboard/messages", response_class=HTMLResponse)
async def messages_list(request: Request, db: Session = Depends(get_db)):
    """對話記錄頁面"""
    message_service = MessageService(db)
    messages = message_service.get_all_messages(limit=200)

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "active_page": "messages",
        "messages": messages
    })


@router.get("/dashboard/days", response_class=HTMLResponse)
async def days_list(request: Request):
    """課程管理頁面"""
    days = []
    for d in get_all_days():
        day_data = get_day_data(d["day"])
        if day_data:
            days.append(day_data)

    return templates.TemplateResponse("days.html", {
        "request": request,
        "active_page": "days",
        "days": days
    })
