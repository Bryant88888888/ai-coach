from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
from datetime import datetime, date, timezone
import uuid
import os

from app.database import get_db
from app.config import get_settings
from app.services.user_service import UserService
from app.services.message_service import MessageService
from app.services.push_service import PushService
from app.services.auth_service import AuthService
from app.services.line_service import LineService
from app.data.days_data import get_all_days, get_day_data
from app.models.leave_request import LeaveRequest, LeaveStatus
from app.models.manager import Manager
from app.models.training_batch import TrainingBatch
from app.models.user_training import UserTraining, TrainingStatus
from app.services.training_batch_service import TrainingBatchService

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
    line_picture_url: str = Form(""),
    full_name: str = Form(...),
    leave_type: str = Form(...),
    leave_date: date = Form(...),
    reason: str = Form(None),
    proof_file: UploadFile = File(None)
):
    """提交請假申請（員工用，透過 LINE 登入）"""
    settings = get_settings()
    user_service = UserService(db)

    # 檢查當日請假時間限制：下午 5 點後不能請當日假
    now = datetime.now()
    today = now.date()
    if leave_date == today and now.hour >= 17:
        return templates.TemplateResponse("leave_form.html", {
            "request": request,
            "liff_id": settings.liff_id,
            "is_public": True,
            "error": "當日請假需在下午 5 點前提出申請，請選擇其他日期"
        })

    try:
        # 根據 LINE ID 查找或建立使用者
        user = user_service.get_user_by_line_id(line_user_id)
        if not user:
            # 如果使用者不存在，建立新使用者
            user = user_service.create_user(
                line_user_id=line_user_id,
                line_display_name=line_user_name,
                line_picture_url=line_picture_url if line_picture_url else None
            )

        # 更新本名（如果有填寫且不同）
        if full_name and user.real_name != full_name:
            user.real_name = full_name
            db.commit()

        # 更新 LINE 資料（如果有變更）
        if line_user_name and user.line_display_name != line_user_name:
            user.line_display_name = line_user_name
            db.commit()
        if line_picture_url and user.line_picture_url != line_picture_url:
            user.line_picture_url = line_picture_url
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
            applicant_name=full_name,
            line_display_name=line_user_name,
            line_picture_url=line_picture_url if line_picture_url else None,
            leave_type=leave_type,
            leave_date=leave_date,
            reason=reason if leave_type == "事假" else None,
            proof_file=proof_filename if leave_type == "病假" else None,
            status=LeaveStatus.PENDING.value
        )
        db.add(leave_request)
        db.commit()
        db.refresh(leave_request)  # 重新載入以取得 ID

        # 發送 LINE 通知給主管
        try:
            line_service = LineService()
            line_service.notify_managers_leave_request(leave_request)
        except Exception as notify_error:
            print(f"發送主管通知失敗: {notify_error}")
            # 通知失敗不影響申請成功

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


@router.get("/leave/upload/{leave_id}", response_class=HTMLResponse)
async def proof_upload_page(request: Request, leave_id: int, db: Session = Depends(get_db)):
    """病假證明上傳頁面"""
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()

    # 檢查申請是否存在
    if not leave_request:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "leave_request": None
        })

    # 檢查是否已有證明
    if leave_request.proof_file:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "already_uploaded": True
        })

    # 檢查是否已過期限
    if leave_request.proof_deadline and datetime.now(timezone.utc) > leave_request.proof_deadline:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "expired": True
        })

    return templates.TemplateResponse("proof_upload.html", {
        "request": request,
        "leave_request": leave_request
    })


@router.post("/leave/upload/{leave_id}")
async def proof_upload_submit(
    request: Request,
    leave_id: int,
    db: Session = Depends(get_db),
    proof_file: UploadFile = File(...)
):
    """上傳病假證明"""
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()

    if not leave_request:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "error": "找不到此請假申請"
        })

    # 檢查是否已過期限
    if leave_request.proof_deadline and datetime.now(timezone.utc) > leave_request.proof_deadline:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "expired": True
        })

    try:
        # 儲存檔案
        ext = os.path.splitext(proof_file.filename)[1]
        proof_filename = f"{uuid.uuid4()}{ext}"
        file_path = UPLOAD_DIR / proof_filename

        with open(file_path, "wb") as f:
            content = await proof_file.read()
            f.write(content)

        # 更新資料庫
        leave_request.proof_file = proof_filename
        leave_request.status = LeaveStatus.PENDING.value  # 改回待審核，讓主管再次審核
        db.commit()

        # 通知主管已補件（重新發送通知）
        try:
            line_service = LineService()
            line_service.notify_managers_leave_request(leave_request)
        except Exception as notify_error:
            print(f"發送補件通知失敗: {notify_error}")

        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "success": True
        })

    except Exception as e:
        return templates.TemplateResponse("proof_upload.html", {
            "request": request,
            "leave_request": leave_request,
            "error": f"上傳失敗：{str(e)}"
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

    # 發送審核結果通知給請假者
    try:
        line_service = LineService()
        line_service.notify_requester_result(leave_request)
    except Exception as notify_error:
        print(f"發送審核結果通知失敗: {notify_error}")

    return RedirectResponse(url="/dashboard/leave", status_code=303)


# ========== 主管管理 ==========

@router.get("/dashboard/managers", response_class=HTMLResponse)
async def managers_list(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """主管管理頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    managers = db.query(Manager).order_by(Manager.created_at.desc()).all()

    return templates.TemplateResponse("managers.html", {
        "request": request,
        "active_page": "managers",
        "managers": managers,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/managers/add")
async def manager_add(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    line_user_id: str = Form(...)
):
    """新增主管"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 檢查 LINE User ID 格式
    line_user_id = line_user_id.strip()
    if not line_user_id.startswith("U") or len(line_user_id) != 33:
        return RedirectResponse(
            url="/dashboard/managers?error=LINE User ID 格式不正確（應為 U 開頭的 33 字元）",
            status_code=303
        )

    # 檢查是否已存在
    existing = db.query(Manager).filter(Manager.line_user_id == line_user_id).first()
    if existing:
        return RedirectResponse(
            url=f"/dashboard/managers?error=此 LINE User ID 已存在（{existing.name}）",
            status_code=303
        )

    # 新增主管
    manager = Manager(
        name=name.strip(),
        line_user_id=line_user_id,
        is_active=True
    )
    db.add(manager)
    db.commit()

    return RedirectResponse(
        url=f"/dashboard/managers?success=已成功新增主管「{name}」",
        status_code=303
    )


@router.post("/dashboard/managers/{manager_id}/toggle")
async def manager_toggle(
    request: Request,
    manager_id: int,
    db: Session = Depends(get_db)
):
    """切換主管通知狀態"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    manager = db.query(Manager).filter(Manager.id == manager_id).first()
    if manager:
        manager.is_active = not manager.is_active
        db.commit()
        status = "啟用" if manager.is_active else "停用"
        return RedirectResponse(
            url=f"/dashboard/managers?success=已{status}「{manager.name}」的通知",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/managers", status_code=303)


@router.post("/dashboard/managers/{manager_id}/delete")
async def manager_delete(
    request: Request,
    manager_id: int,
    db: Session = Depends(get_db)
):
    """刪除主管"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    manager = db.query(Manager).filter(Manager.id == manager_id).first()
    if manager:
        name = manager.name
        db.delete(manager)
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/managers?success=已刪除主管「{name}」",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/managers", status_code=303)


# ========== 訓練批次管理 ==========

@router.get("/dashboard/training", response_class=HTMLResponse)
async def training_manage(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """訓練批次管理頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    batches = batch_service.get_all_batches()

    # 計算每個批次的統計資料
    batch_stats = {}
    for batch in batches:
        batch_stats[batch.id] = batch_service.get_batch_stats(batch.id)

    return templates.TemplateResponse("training.html", {
        "request": request,
        "active_page": "training",
        "batches": batches,
        "batch_stats": batch_stats,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/training/batch/create")
async def training_batch_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    description: str = Form(None),
    course_version: str = Form("v1")
):
    """建立新的訓練批次"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)

    try:
        batch = batch_service.create_batch(
            name=name.strip(),
            description=description.strip() if description else None,
            course_version=course_version
        )
        return RedirectResponse(
            url=f"/dashboard/training?success=已成功建立批次「{batch.name}」",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/training?error=建立失敗：{str(e)}",
            status_code=303
        )


@router.get("/dashboard/training/batch/{batch_id}", response_class=HTMLResponse)
async def training_batch_detail(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """訓練批次詳情頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    batch = batch_service.get_batch(batch_id)

    if not batch:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "找不到此訓練批次"
        }, status_code=404)

    # 取得批次中的用戶訓練
    user_trainings = batch_service.get_batch_users(batch_id)
    stats = batch_service.get_batch_stats(batch_id)

    # 取得所有未加入此批次的用戶（用於新增用戶）
    user_service = UserService(db)
    all_users = user_service.get_all_users()
    batch_user_ids = {ut.user_id for ut in user_trainings}
    available_users = [u for u in all_users if u.id not in batch_user_ids]

    return templates.TemplateResponse("training_batch.html", {
        "request": request,
        "active_page": "training",
        "batch": batch,
        "user_trainings": user_trainings,
        "stats": stats,
        "available_users": available_users,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/training/batch/{batch_id}/toggle")
async def training_batch_toggle(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db)
):
    """切換批次啟用狀態"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    batch = batch_service.get_batch(batch_id)

    if batch:
        batch_service.update_batch(batch_id, is_active=not batch.is_active)
        status = "啟用" if not batch.is_active else "停用"
        return RedirectResponse(
            url=f"/dashboard/training?success=已{status}批次「{batch.name}」",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/training", status_code=303)


@router.post("/dashboard/training/batch/{batch_id}/add-user")
async def training_batch_add_user(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
    user_id: int = Form(...),
    auto_start: bool = Form(False)
):
    """將用戶加入訓練批次"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    user_service = UserService(db)

    batch = batch_service.get_batch(batch_id)
    user = user_service.get_user_by_id(user_id)

    if not batch or not user:
        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?error=批次或用戶不存在",
            status_code=303
        )

    try:
        user_training = batch_service.add_user_to_batch(user_id, batch_id, auto_start=auto_start)
        user_name = user.display_name or user.line_user_id[:8]

        if auto_start:
            # 發送開場訊息
            push_service = PushService(db)
            push_service.push_to_training(user_training)

        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?success=已將「{user_name}」加入批次",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?error=加入失敗：{str(e)}",
            status_code=303
        )


@router.post("/dashboard/training/batch/{batch_id}/remove-user/{user_id}")
async def training_batch_remove_user(
    request: Request,
    batch_id: int,
    user_id: int,
    db: Session = Depends(get_db)
):
    """將用戶從批次中移除"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    result = batch_service.remove_user_from_batch(user_id, batch_id)

    if result:
        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?success=已移除用戶",
            status_code=303
        )

    return RedirectResponse(
        url=f"/dashboard/training/batch/{batch_id}?error=移除失敗",
        status_code=303
    )


@router.post("/dashboard/training/user/{training_id}/start")
async def training_user_start(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db)
):
    """開始用戶訓練"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(url="/dashboard/training", status_code=303)

    batch_service = TrainingBatchService(db)
    batch_service.start_training(user_training)

    # 發送開場訊息
    push_service = PushService(db)
    push_service.push_to_training(user_training)

    return RedirectResponse(
        url=f"/dashboard/training/batch/{user_training.batch_id}?success=已開始訓練",
        status_code=303
    )


@router.post("/dashboard/training/user/{training_id}/pause")
async def training_user_pause(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db)
):
    """暫停用戶訓練"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(url="/dashboard/training", status_code=303)

    batch_service = TrainingBatchService(db)
    batch_service.pause_training(user_training)

    return RedirectResponse(
        url=f"/dashboard/training/batch/{user_training.batch_id}?success=已暫停訓練",
        status_code=303
    )


@router.post("/dashboard/training/user/{training_id}/resume")
async def training_user_resume(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db)
):
    """恢復用戶訓練"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(url="/dashboard/training", status_code=303)

    batch_service = TrainingBatchService(db)
    batch_service.resume_training(user_training)

    # 發送繼續訓練訊息
    push_service = PushService(db)
    push_service.push_to_training(user_training)

    return RedirectResponse(
        url=f"/dashboard/training/batch/{user_training.batch_id}?success=已恢復訓練",
        status_code=303
    )


@router.post("/dashboard/training/user/{training_id}/restart")
async def training_user_restart(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db)
):
    """重新開始用戶訓練"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(url="/dashboard/training", status_code=303)

    batch_service = TrainingBatchService(db)
    batch_service.restart_training(user_training)

    # 發送開場訊息
    push_service = PushService(db)
    push_service.push_to_training(user_training)

    return RedirectResponse(
        url=f"/dashboard/training/batch/{user_training.batch_id}?success=已重新開始訓練",
        status_code=303
    )


@router.post("/dashboard/training/batch/{batch_id}/start-all")
async def training_batch_start_all(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db)
):
    """開始批次中所有待開始的訓練"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    push_service = PushService(db)

    user_trainings = batch_service.get_batch_users(batch_id)
    started_count = 0

    for ut in user_trainings:
        if ut.status == TrainingStatus.PENDING.value:
            batch_service.start_training(ut)
            push_service.push_to_training(ut)
            started_count += 1

    return RedirectResponse(
        url=f"/dashboard/training/batch/{batch_id}?success=已開始 {started_count} 個訓練",
        status_code=303
    )
