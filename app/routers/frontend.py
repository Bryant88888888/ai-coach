from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
from datetime import datetime, date
import uuid
import os

from app.database import get_db
from app.config import get_settings
from app.services.user_service import UserService
from app.services.message_service import MessageService
from app.services.push_service import PushService
from app.services.auth_service import AuthService
from app.data.days_data import get_all_days, get_day_data
from app.models.leave_request import LeaveRequest, LeaveStatus

# 設定模板目錄
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(tags=["前端頁面"])


def require_auth(request: Request):
    """檢查是否已登入"""
    if not request.session.get("authenticated"):
        return False
    return True


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登入頁面"""
    # 如果已登入，直接跳轉到儀表板
    if request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """處理登入"""
    auth_service = AuthService()
    if auth_service.verify_credentials(username, password):
        request.session["authenticated"] = True
        request.session["username"] = username
        return RedirectResponse(url="/dashboard", status_code=303)
    else:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "帳號或密碼錯誤"
        })


@router.get("/logout")
async def logout(request: Request):
    """登出"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """儀表板首頁"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_service = UserService(db)
    message_service = MessageService(db)
    push_service = PushService(db)

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

    # 取得推送統計
    push_stats = push_service.get_push_stats()

    # 取得未回覆的推送
    unresponded_pushes = push_service.get_unresponded_pushes(days=7)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "stats": stats,
        "recent_messages": recent_messages,
        "push_stats": push_stats,
        "unresponded_pushes": unresponded_pushes
    })


@router.get("/dashboard/users", response_class=HTMLResponse)
async def users_list(request: Request, db: Session = Depends(get_db)):
    """用戶列表頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

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
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

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
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

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
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

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


@router.get("/dashboard/days/{day}/edit", response_class=HTMLResponse)
async def day_edit_page(request: Request, day: int):
    """課程編輯頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    day_data = get_day_data(day)
    if not day_data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Day {day} 不存在"
        }, status_code=404)

    return templates.TemplateResponse("day_edit.html", {
        "request": request,
        "active_page": "days",
        "day": day_data
    })


@router.post("/dashboard/days/{day}/edit")
async def day_edit_save(
    request: Request,
    day: int,
    title: str = Form(...),
    goal: str = Form(...),
    opening_a: str = Form(None),
    opening_b: str = Form(None),
    criteria: str = Form(None),
    min_rounds: int = Form(3),
    max_rounds: int = Form(5),
    teaching_content: str = Form(None)
):
    """儲存課程編輯"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    day_data = get_day_data(day)
    if not day_data:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Day {day} 不存在"
        }, status_code=404)

    # 更新 day_data（顯示用）
    day_data["title"] = title
    day_data["goal"] = goal
    day_data["opening_a"] = opening_a
    day_data["opening_b"] = opening_b
    day_data["criteria"] = [c.strip() for c in criteria.split("\n") if c.strip()] if criteria else []
    day_data["min_rounds"] = min_rounds
    day_data["max_rounds"] = max_rounds
    day_data["teaching_content"] = teaching_content

    # 注意：目前資料儲存在 days_data.py 中（靜態檔案）
    # 實際修改需要透過資料庫儲存，這裡僅顯示成功訊息
    # TODO: 實作資料庫儲存功能

    return templates.TemplateResponse("day_edit.html", {
        "request": request,
        "active_page": "days",
        "day": day_data,
        "success": True
    })


# ========== 請假管理 ==========

# 建立上傳目錄
UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/dashboard/leave", response_class=HTMLResponse)
async def leave_manage(request: Request, db: Session = Depends(get_db)):
    """請假管理頁面（管理員）"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 取得所有請假申請
    leave_requests = db.query(LeaveRequest).order_by(LeaveRequest.created_at.desc()).all()

    # 統計
    pending_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.PENDING.value).count()
    approved_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.APPROVED.value).count()
    rejected_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.REJECTED.value).count()

    return templates.TemplateResponse("leave_manage.html", {
        "request": request,
        "active_page": "leave",
        "leave_requests": leave_requests,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count
    })


@router.get("/leave", response_class=HTMLResponse)
async def leave_apply_form(request: Request, db: Session = Depends(get_db)):
    """請假申請表單頁面（員工用，需 LINE 登入）"""
    settings = get_settings()

    return templates.TemplateResponse("leave_form.html", {
        "request": request,
        "liff_id": settings.liff_id,
        "is_public": True
    })


@router.post("/leave")
async def leave_apply_submit(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    line_user_name: str = Form(...),
    full_name: str = Form(...),
    leave_type: str = Form(...),
    leave_date: date = Form(...),
    reason: str = Form(None),
    proof_file: UploadFile = File(None)
):
    """提交請假申請（員工用，透過 LINE 登入）"""
    settings = get_settings()
    user_service = UserService(db)

    try:
        # 根據 LINE ID 查找或建立使用者
        user = user_service.get_user_by_line_id(line_user_id)
        if not user:
            # 如果使用者不存在，建立新使用者（使用填寫的全名）
            user = user_service.create_user(line_user_id, full_name)
        elif user.name != full_name:
            # 更新使用者名稱
            user.name = full_name
            db.commit()

        # 處理檔案上傳
        proof_filename = None
        if proof_file and proof_file.filename:
            # 產生唯一檔名
            ext = os.path.splitext(proof_file.filename)[1]
            proof_filename = f"{uuid.uuid4()}{ext}"
            file_path = UPLOAD_DIR / proof_filename

            # 儲存檔案
            with open(file_path, "wb") as f:
                content = await proof_file.read()
                f.write(content)

        leave_request = LeaveRequest(
            user_id=user.id,
            leave_type=leave_type,
            leave_date=leave_date,
            reason=reason if leave_type == "事假" else None,
            proof_file=proof_filename if leave_type == "病假" else None,
            status=LeaveStatus.PENDING.value
        )
        db.add(leave_request)
        db.commit()

        return templates.TemplateResponse("leave_form.html", {
            "request": request,
            "liff_id": settings.liff_id,
            "is_public": True,
            "success": True,
            "user_name": full_name
        })

    except Exception as e:
        return templates.TemplateResponse("leave_form.html", {
            "request": request,
            "liff_id": settings.liff_id,
            "is_public": True,
            "error": f"申請失敗：{str(e)}"
        })


@router.post("/dashboard/leave/{leave_id}/review")
async def leave_review(
    request: Request,
    leave_id: int,
    db: Session = Depends(get_db),
    action: str = Form(...),
    reviewer_note: str = Form(None)
):
    """審核請假申請"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave_request:
        return RedirectResponse(url="/dashboard/leave", status_code=303)

    # 更新狀態
    if action == "approve":
        leave_request.status = LeaveStatus.APPROVED.value
    elif action == "reject":
        leave_request.status = LeaveStatus.REJECTED.value

    leave_request.reviewer_note = reviewer_note
    leave_request.reviewed_at = datetime.now()
    db.commit()

    return RedirectResponse(url="/dashboard/leave", status_code=303)
