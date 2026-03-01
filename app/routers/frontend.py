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
from app.services.course_service import CourseService
from app.models.leave_request import LeaveRequest, LeaveStatus
from app.models.user import User, UserRole
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

    # 訓練批次統計
    batch_stats = {
        "active": db.query(TrainingBatch).filter(TrainingBatch.is_active == True).count(),
        "in_training": db.query(UserTraining).filter(UserTraining.status == TrainingStatus.ACTIVE.value).count(),
        "pending": db.query(UserTraining).filter(UserTraining.status == TrainingStatus.PENDING.value).count(),
        "completed": db.query(UserTraining).filter(UserTraining.status == TrainingStatus.COMPLETED.value).count()
    }

    stats = {
        "total_users": total_users,
        "active_users": active_users,
        "completed_users": completed_users,
        "completion_rate": round(completed_users / total_users * 100, 1) if total_users > 0 else 0,
        "day_distribution": day_distribution,
        "batch_stats": batch_stats
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
async def user_detail(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """用戶詳情頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_service = UserService(db)
    message_service = MessageService(db)
    course_service = CourseService(db)

    user = user_service.get_user_by_line_id(line_user_id)
    if not user:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "用戶不存在"
        }, status_code=404)

    messages = message_service.get_user_messages(user.id)
    stats = message_service.get_user_stats(user.id)

    # 取得用戶的所有訓練
    user_trainings = user.trainings if user.trainings else []

    # 取得所有課程版本（從課程表和訓練批次表合併）
    course_versions = course_service.get_course_versions()

    # 也從訓練批次取得版本
    batch_versions = db.query(TrainingBatch.course_version).distinct().all()
    batch_version_list = [v[0] for v in batch_versions if v[0]]

    # 合併並去重
    all_versions = list(set(course_versions + batch_version_list))
    all_versions.sort()

    # 如果沒有任何版本，至少提供 v1
    if not all_versions:
        all_versions = ["v1"]

    # 取得每個版本的課程天數範圍
    version_days = {}
    for version in all_versions:
        courses = course_service.get_courses_by_version(version)
        if courses:
            max_day = max(c.day for c in courses)
            version_days[version] = list(range(0, max_day + 1))
        else:
            version_days[version] = list(range(0, 15))  # 預設 Day 0 到 Day 14

    return templates.TemplateResponse("user_detail.html", {
        "request": request,
        "active_page": "users",
        "user": user,
        "messages": messages,
        "stats": stats,
        "user_trainings": user_trainings,
        "course_versions": all_versions,
        "version_days": version_days,
        "success_message": success,
        "error_message": error
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
async def days_list(
    request: Request,
    db: Session = Depends(get_db),
    version: str = None,
    success: str = None,
    error: str = None
):
    """課程管理頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)

    # 取得所有版本
    versions = course_service.get_course_versions()
    if not versions:
        versions = ["v1"]

    # 預設使用第一個版本
    current_version = version if version and version in versions else versions[0]

    # 取得該版本的課程
    courses = course_service.get_courses_by_version(current_version)
    days = [course.to_dict() for course in courses]

    # 取得版本統計
    version_stats = course_service.get_version_stats()

    return templates.TemplateResponse("days.html", {
        "request": request,
        "active_page": "days",
        "days": days,
        "versions": versions,
        "current_version": current_version,
        "version_stats": version_stats,
        "success_message": success,
        "error_message": error
    })


@router.get("/dashboard/days/create", response_class=HTMLResponse)
async def day_create_page(
    request: Request,
    db: Session = Depends(get_db),
    version: str = "v1"
):
    """新增課程頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)
    versions = course_service.get_course_versions()
    if not versions:
        versions = ["v1"]

    # 取得該版本已有的最大 day 數
    courses = course_service.get_courses_by_version(version)
    next_day = max([c.day for c in courses], default=-1) + 1

    return templates.TemplateResponse("day_edit.html", {
        "request": request,
        "active_page": "days",
        "day": {
            "day": next_day,
            "title": "",
            "goal": "",
            "type": "assessment",
            "opening_a": "",
            "opening_b": "",
            "criteria": [],
            "min_rounds": 3,
            "max_rounds": 5,
            "teaching_content": ""
        },
        "is_new": True,
        "current_version": version,
        "versions": versions
    })


@router.post("/dashboard/days/create")
async def day_create_save(
    request: Request,
    db: Session = Depends(get_db),
    day: int = Form(...),
    title: str = Form(...),
    goal: str = Form(None),
    opening_a: str = Form(None),
    opening_b: str = Form(None),
    criteria: str = Form(None),
    min_rounds: int = Form(3),
    max_rounds: int = Form(5),
    lesson_content: str = Form(None),
    teaching_content: str = Form(None),
    system_prompt: str = Form(None),
    course_version: str = Form("v1")
):
    """儲存新課程"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)

    try:
        # 檢查是否已存在相同版本和 day
        existing = course_service.get_course_by_day(day, course_version)
        if existing:
            return RedirectResponse(
                url=f"/dashboard/days?version={course_version}&error=Day {day} 在版本 {course_version} 中已存在",
                status_code=303
            )

        # 根據填寫的欄位自動決定課程類型
        has_opening = bool(opening_a and opening_a.strip()) or bool(opening_b and opening_b.strip())
        has_teaching = bool(teaching_content and teaching_content.strip())
        course_type = "teaching" if has_teaching and not has_opening else "assessment"

        # 建立課程
        criteria_text = criteria.strip() if criteria else None
        course_service.create_course(
            day=day,
            title=title.strip(),
            course_version=course_version,
            goal=goal.strip() if goal else None,
            type=course_type,
            opening_a=opening_a.strip() if opening_a else None,
            opening_b=opening_b.strip() if opening_b else None,
            criteria=criteria_text,
            min_rounds=min_rounds,
            max_rounds=max_rounds,
            lesson_content=lesson_content.strip() if lesson_content else None,
            teaching_content=teaching_content.strip() if teaching_content else None,
            system_prompt=system_prompt.strip() if system_prompt else None
        )

        return RedirectResponse(
            url=f"/dashboard/days?version={course_version}&success=成功新增 Day {day} 課程",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/days?version={course_version}&error=新增失敗：{str(e)}",
            status_code=303
        )


@router.get("/dashboard/days/{day}/edit", response_class=HTMLResponse)
async def day_edit_page(
    request: Request,
    day: int,
    db: Session = Depends(get_db),
    version: str = "v1"
):
    """課程編輯頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)
    course = course_service.get_course_by_day(day, version)

    if not course:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Day {day} 在版本 {version} 中不存在"
        }, status_code=404)

    versions = course_service.get_course_versions()

    return templates.TemplateResponse("day_edit.html", {
        "request": request,
        "active_page": "days",
        "day": course.to_dict(),
        "course_id": course.id,
        "is_new": False,
        "current_version": version,
        "versions": versions
    })


@router.post("/dashboard/days/{day}/edit")
async def day_edit_save(
    request: Request,
    day: int,
    db: Session = Depends(get_db),
    course_id: int = Form(...),
    title: str = Form(...),
    goal: str = Form(None),
    opening_a: str = Form(None),
    opening_b: str = Form(None),
    criteria: str = Form(None),
    min_rounds: int = Form(3),
    max_rounds: int = Form(5),
    lesson_content: str = Form(None),
    teaching_content: str = Form(None),
    system_prompt: str = Form(None),
    course_version: str = Form("v1")
):
    """儲存課程編輯"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)
    course = course_service.get_course(course_id)

    if not course:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"課程不存在"
        }, status_code=404)

    try:
        # 根據填寫的欄位自動決定課程類型
        has_opening = bool(opening_a and opening_a.strip()) or bool(opening_b and opening_b.strip())
        has_teaching = bool(teaching_content and teaching_content.strip())
        course_type = "teaching" if has_teaching and not has_opening else "assessment"

        # 更新課程
        criteria_text = criteria.strip() if criteria else None
        course_service.update_course(
            course_id=course_id,
            title=title.strip(),
            goal=goal.strip() if goal else None,
            type=course_type,
            opening_a=opening_a.strip() if opening_a else None,
            opening_b=opening_b.strip() if opening_b else None,
            criteria=criteria_text,
            min_rounds=min_rounds,
            max_rounds=max_rounds,
            lesson_content=lesson_content.strip() if lesson_content else None,
            teaching_content=teaching_content.strip() if teaching_content else None,
            system_prompt=system_prompt.strip() if system_prompt else None
        )

        # 重新取得更新後的課程資料
        course = course_service.get_course(course_id)
        versions = course_service.get_course_versions()

        return templates.TemplateResponse("day_edit.html", {
            "request": request,
            "active_page": "days",
            "day": course.to_dict(),
            "course_id": course.id,
            "is_new": False,
            "current_version": course_version,
            "versions": versions,
            "success": True
        })
    except Exception as e:
        versions = course_service.get_course_versions()
        return templates.TemplateResponse("day_edit.html", {
            "request": request,
            "active_page": "days",
            "day": course.to_dict(),
            "course_id": course.id,
            "is_new": False,
            "current_version": course_version,
            "versions": versions,
            "error": f"儲存失敗：{str(e)}"
        })


@router.post("/dashboard/days/{course_id}/delete")
async def day_delete(
    request: Request,
    course_id: int,
    db: Session = Depends(get_db)
):
    """刪除課程"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)
    course = course_service.get_course(course_id)

    if not course:
        return RedirectResponse(
            url="/dashboard/days?error=課程不存在",
            status_code=303
        )

    version = course.course_version
    day = course.day

    try:
        course_service.hard_delete_course(course_id)
        return RedirectResponse(
            url=f"/dashboard/days?version={version}&success=已刪除 Day {day} 課程",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/days?version={version}&error=刪除失敗：{str(e)}",
            status_code=303
        )


@router.post("/dashboard/days/version/create")
async def version_create(
    request: Request,
    db: Session = Depends(get_db),
    version_name: str = Form(...)
):
    """建立新的空白課程版本"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)

    # 檢查版本是否已存在
    existing = course_service.get_courses_by_version(version_name)
    if existing:
        return RedirectResponse(
            url=f"/dashboard/days?error=版本 {version_name} 已存在",
            status_code=303
        )

    # 建立一個空的版本（創建一個 Day 0 作為起始點）
    try:
        course_service.create_course(
            day=0,
            title="訓練開始",
            course_version=version_name,
            goal="歡迎開始訓練",
            type="teaching",
            teaching_content="歡迎來到訓練課程！請依照指示完成每日訓練。"
        )
        return RedirectResponse(
            url=f"/dashboard/days?version={version_name}&success=已成功建立版本 {version_name}",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/days?error=建立失敗：{str(e)}",
            status_code=303
        )


@router.post("/dashboard/days/version/duplicate")
async def version_duplicate(
    request: Request,
    db: Session = Depends(get_db),
    from_version: str = Form(...),
    to_version: str = Form(...)
):
    """複製課程版本"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    course_service = CourseService(db)

    try:
        course_service.duplicate_version(from_version, to_version)
        return RedirectResponse(
            url=f"/dashboard/days?version={to_version}&success=已成功複製版本 {from_version} 到 {to_version}",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/days?version={from_version}&error={str(e)}",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/days?version={from_version}&error=複製失敗：{str(e)}",
            status_code=303
        )


@router.post("/dashboard/days/seed")
async def seed_courses_route(
    request: Request,
    db: Session = Depends(get_db),
    version: str = Form("v1"),
    force: bool = Form(False)
):
    """從靜態資料匯入課程到資料庫"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        from app.data.days_data import DAYS_DATA
        course_service = CourseService(db)

        # 檢查版本是否已存在
        existing = course_service.get_courses_by_version(version)
        if existing and not force:
            return RedirectResponse(
                url=f"/dashboard/days?version={version}&error=版本 {version} 已存在，請勾選「覆蓋」選項",
                status_code=303
            )

        # 如果 force 模式，先刪除舊資料
        if force and existing:
            for course in existing:
                course_service.hard_delete_course(course.id)

        # 匯入課程
        for day_data in DAYS_DATA:
            course_service.create_course(
                course_version=version,
                day=day_data["day"],
                title=day_data["title"],
                goal=day_data.get("goal"),
                type="teaching" if day_data.get("type") == "teaching" else "assessment",
                opening_a=day_data.get("opening_a"),
                opening_b=day_data.get("opening_b"),
                criteria="\n".join(day_data.get("criteria", [])) if day_data.get("criteria") else None,
                min_rounds=day_data.get("min_rounds", 3),
                max_rounds=day_data.get("max_rounds", 5),
                teaching_content=day_data.get("teaching_content")
            )

        return RedirectResponse(
            url=f"/dashboard/days?version={version}&success=已成功匯入 {len(DAYS_DATA)} 個課程到版本 {version}",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/days?error=匯入失敗：{str(e)}",
            status_code=303
        )


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
    # 優先使用請假專用 LIFF ID，否則用通用的
    liff_id = settings.liff_id_leave or settings.liff_id

    return templates.TemplateResponse("leave_form.html", {
        "request": request,
        "liff_id": liff_id,
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


# ========== 主管管理（統一用戶系統） ==========

@router.get("/dashboard/managers", response_class=HTMLResponse)
async def managers_list(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """主管管理頁面 - 使用統一用戶系統"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 從 users 表查詢有 manager 角色的用戶
    managers = db.query(User).filter(
        User.roles.contains('"manager"')
    ).order_by(User.created_at.desc()).all()

    # 取得所有用戶（用於新增主管時選擇）
    all_users = db.query(User).filter(
        ~User.roles.contains('"manager"')
    ).order_by(User.line_display_name).all()

    return templates.TemplateResponse("managers.html", {
        "request": request,
        "active_page": "managers",
        "managers": managers,
        "all_users": all_users,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/managers/add")
async def manager_add(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Form(None),
    name: str = Form(None),
    line_user_id: str = Form(None)
):
    """新增主管 - 可從現有用戶選擇或輸入新的 LINE ID"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    if user_id:
        # 從現有用戶添加主管角色
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return RedirectResponse(
                url="/dashboard/managers?error=用戶不存在",
                status_code=303
            )

        if user.has_role(UserRole.MANAGER.value):
            return RedirectResponse(
                url=f"/dashboard/managers?error=此用戶已是主管",
                status_code=303
            )

        user.add_role(UserRole.MANAGER.value)
        user.manager_notification_enabled = True
        db.commit()

        return RedirectResponse(
            url=f"/dashboard/managers?success=已將「{user.display_name}」設為主管",
            status_code=303
        )

    elif line_user_id:
        # 透過 LINE ID 新增
        line_user_id = line_user_id.strip()
        if not line_user_id.startswith("U") or len(line_user_id) != 33:
            return RedirectResponse(
                url="/dashboard/managers?error=LINE User ID 格式不正確（應為 U 開頭的 33 字元）",
                status_code=303
            )

        # 檢查用戶是否已存在
        existing_user = db.query(User).filter(User.line_user_id == line_user_id).first()
        if existing_user:
            if existing_user.has_role(UserRole.MANAGER.value):
                return RedirectResponse(
                    url=f"/dashboard/managers?error=此用戶已是主管（{existing_user.display_name}）",
                    status_code=303
                )
            # 添加主管角色
            existing_user.add_role(UserRole.MANAGER.value)
            existing_user.manager_notification_enabled = True
            if name and not existing_user.real_name:
                existing_user.real_name = name.strip()
            db.commit()
            return RedirectResponse(
                url=f"/dashboard/managers?success=已將「{existing_user.display_name}」設為主管",
                status_code=303
            )
        else:
            # 創建新用戶
            import json
            new_user = User(
                line_user_id=line_user_id,
                real_name=name.strip() if name else None,
                roles=json.dumps([UserRole.TRAINEE.value, UserRole.MANAGER.value]),
                manager_notification_enabled=True
            )
            db.add(new_user)
            db.commit()
            return RedirectResponse(
                url=f"/dashboard/managers?success=已成功新增主管「{name or line_user_id[:10]}...」",
                status_code=303
            )

    return RedirectResponse(
        url="/dashboard/managers?error=請選擇用戶或輸入 LINE User ID",
        status_code=303
    )


@router.post("/dashboard/managers/{user_id}/toggle")
async def manager_toggle(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    """切換主管通知狀態"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(User).filter(User.id == user_id).first()
    if user and user.has_role(UserRole.MANAGER.value):
        user.manager_notification_enabled = not user.manager_notification_enabled
        db.commit()
        status = "啟用" if user.manager_notification_enabled else "停用"
        return RedirectResponse(
            url=f"/dashboard/managers?success=已{status}「{user.display_name}」的通知",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/managers", status_code=303)


@router.post("/dashboard/managers/{user_id}/delete")
async def manager_delete(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db)
):
    """移除主管角色（不刪除用戶）"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user = db.query(User).filter(User.id == user_id).first()
    if user and user.has_role(UserRole.MANAGER.value):
        name = user.display_name
        user.remove_role(UserRole.MANAGER.value)
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/managers?success=已移除「{name}」的主管角色",
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


@router.post("/dashboard/training/batch/{batch_id}/add-all-users")
async def training_batch_add_all_users(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
    auto_start_all: bool = Form(False)
):
    """將所有未加入的用戶加入訓練批次"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    batch_service = TrainingBatchService(db)
    user_service = UserService(db)
    push_service = PushService(db)

    batch = batch_service.get_batch(batch_id)
    if not batch:
        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?error=批次不存在",
            status_code=303
        )

    # 取得所有用戶
    all_users = user_service.get_all_users()

    # 取得已在此批次的用戶 ID
    existing_trainings = batch_service.get_batch_users(batch_id)
    existing_user_ids = {ut.user_id for ut in existing_trainings}

    # 篩選出未加入的用戶
    available_users = [u for u in all_users if u.id not in existing_user_ids]

    if not available_users:
        return RedirectResponse(
            url=f"/dashboard/training/batch/{batch_id}?error=沒有可加入的用戶",
            status_code=303
        )

    added_count = 0
    for user in available_users:
        try:
            user_training = batch_service.add_user_to_batch(user.id, batch_id, auto_start=auto_start_all)
            if auto_start_all:
                push_service.push_to_training(user_training)
            added_count += 1
        except Exception:
            continue

    return RedirectResponse(
        url=f"/dashboard/training/batch/{batch_id}?success=已將 {added_count} 位用戶加入批次",
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


# ========== 用戶訓練管理 ==========

@router.post("/dashboard/users/{line_user_id}/toggle-notification")
async def user_toggle_notification(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """切換用戶課程通知狀態"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        return RedirectResponse(
            url="/dashboard/users?error=用戶不存在",
            status_code=303
        )

    # 切換通知狀態
    user.notification_enabled = not user.notification_enabled
    db.commit()

    status = "開啟" if user.notification_enabled else "關閉"
    return RedirectResponse(
        url=f"/dashboard/users/{line_user_id}?success=已{status}課程通知",
        status_code=303
    )


@router.post("/dashboard/users/{line_user_id}/update-training")
async def user_update_training(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db),
    training_id: int = Form(...),
    new_day: int = Form(...)
):
    """更新用戶訓練進度"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(
            url=f"/dashboard/users/{line_user_id}?error=找不到此訓練",
            status_code=303
        )

    # 更新訓練日
    old_day = user_training.current_day
    user_training.current_day = new_day
    user_training.current_round = 0  # 重置輪數
    db.commit()

    return RedirectResponse(
        url=f"/dashboard/users/{line_user_id}?success=已將訓練日從 Day {old_day} 調整為 Day {new_day}",
        status_code=303
    )


@router.post("/dashboard/users/{line_user_id}/send-training")
async def user_send_training(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db),
    training_id: int = Form(...),
    send_day: int = Form(...)
):
    """發送指定訓練的指定天數內容（使用圖卡格式）"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_training = db.query(UserTraining).filter(UserTraining.id == training_id).first()
    if not user_training:
        return RedirectResponse(
            url=f"/dashboard/users/{line_user_id}?error=找不到此訓練",
            status_code=303
        )

    push_service = PushService(db)

    # 更新訓練進度到指定天數
    user_training.current_day = send_day
    user_training.current_round = 0
    db.commit()

    # 發送圖卡
    result = push_service.send_training_card(training_id=training_id, day=send_day)

    if result["status"] == "success":
        return RedirectResponse(
            url=f"/dashboard/users/{line_user_id}?success=已發送 Day {send_day} 的訓練圖卡",
            status_code=303
        )
    else:
        return RedirectResponse(
            url=f"/dashboard/users/{line_user_id}?error=發送失敗：{result.get('reason', '未知錯誤')}",
            status_code=303
        )


@router.post("/dashboard/users/{line_user_id}/send-any-training")
async def user_send_any_training(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db),
    version: str = Form(...),
    day: int = Form(...),
    persona: str = Form("A")
):
    """發送任意版本/天數的訓練內容（使用圖卡格式）"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    user_service = UserService(db)
    push_service = PushService(db)

    user = user_service.get_user_by_line_id(line_user_id)
    if not user:
        return RedirectResponse(
            url=f"/dashboard/users?error=用戶不存在",
            status_code=303
        )

    # 檢查是否有進行中的訓練
    active_training = user.active_training
    if active_training:
        # 更新訓練進度到指定天數
        active_training.current_day = day
        active_training.current_round = 0
        active_training.persona = f"{persona}_經驗"
        db.commit()

        # 發送圖卡
        result = push_service.send_training_card(training_id=active_training.id, day=day)

        if result["status"] == "success":
            return RedirectResponse(
                url=f"/dashboard/users/{line_user_id}?success=已發送 Day {day} 的訓練圖卡",
                status_code=303
            )
        else:
            return RedirectResponse(
                url=f"/dashboard/users/{line_user_id}?error=發送失敗：{result.get('reason', '未知錯誤')}",
                status_code=303
            )
    else:
        # 沒有訓練，使用文字訊息（保留舊邏輯）
        opening_message = push_service.get_opening_message(
            day=day,
            persona=f"{persona}_",
            course_version=version
        )

        if not opening_message:
            return RedirectResponse(
                url=f"/dashboard/users/{line_user_id}?error=找不到 {version} 版本 Day {day} 的課程內容",
                status_code=303
            )

        try:
            push_service._send_push_message(
                user_id=user.line_user_id,
                message=opening_message
            )

            return RedirectResponse(
                url=f"/dashboard/users/{line_user_id}?success=已發送 {version} 版本 Day {day} 的訓練內容（注意：用戶無進行中訓練，已使用文字格式）",
                status_code=303
            )
        except Exception as e:
            return RedirectResponse(
                url=f"/dashboard/users/{line_user_id}?error=發送失敗：{str(e)}",
                status_code=303
            )


# ========== 值日生管理 ==========

from app.services.duty_service import DutyService
from app.models.duty_config import DutyConfig
from app.models.duty_schedule import DutySchedule
from app.models.duty_report import DutyReport, DutyReportStatus
from app.models.duty_complaint import DutyComplaint, DutyComplaintStatus


@router.get("/dashboard/duty", response_class=HTMLResponse)
async def duty_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """值日生管理首頁"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    # 取得統計資料
    duty_stats = duty_service.get_duty_stats()
    duty_members = duty_service.get_duty_members()

    stats = {
        "duty_members": len(duty_members),
        "pending_reports": duty_stats.get("pending_reports", 0),
        "pending_complaints": duty_stats.get("pending_complaints", 0),
        "approved": duty_stats.get("approved", 0)
    }

    # 今日值日
    today_duty = duty_service.get_today_duty()

    return templates.TemplateResponse("duty.html", {
        "request": request,
        "active_page": "duty",
        "stats": stats,
        "today_duty": today_duty,
        "success_message": success,
        "error_message": error
    })


@router.get("/dashboard/duty/members", response_class=HTMLResponse)
async def duty_members_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """值日生名單頁面 - 只列出已填寫員工資料的用戶"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 只取得已填寫員工資料的用戶（有 real_name 的用戶）
    registered_users = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != ""
    ).order_by(User.real_name).all()

    # 取得已設為值日生的用戶 ID 列表
    duty_member_ids = set()
    for user in registered_users:
        if user.has_role(UserRole.DUTY_MEMBER.value):
            duty_member_ids.add(user.id)

    return templates.TemplateResponse("duty_members.html", {
        "request": request,
        "active_page": "duty",
        "all_users": registered_users,
        "duty_member_ids": duty_member_ids,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/duty/members/update")
async def duty_members_update(
    request: Request,
    db: Session = Depends(get_db)
):
    """批次更新值日生名單"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 取得表單資料
    form_data = await request.form()
    selected_ids = set(int(id) for id in form_data.getlist("duty_members"))

    # 只取得已填寫員工資料的用戶
    all_users = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != ""
    ).all()

    added_count = 0
    removed_count = 0

    for user in all_users:
        is_currently_duty = user.has_role(UserRole.DUTY_MEMBER.value)
        should_be_duty = user.id in selected_ids

        if should_be_duty and not is_currently_duty:
            # 新增值日生角色
            user.add_role(UserRole.DUTY_MEMBER.value)
            added_count += 1
        elif not should_be_duty and is_currently_duty:
            # 移除值日生角色
            user.remove_role(UserRole.DUTY_MEMBER.value)
            removed_count += 1

    db.commit()

    message = f"已更新值日生名單"
    if added_count > 0:
        message += f"，新增 {added_count} 人"
    if removed_count > 0:
        message += f"，移除 {removed_count} 人"

    return RedirectResponse(
        url=f"/dashboard/duty/members?success={message}",
        status_code=303
    )


@router.get("/dashboard/duty/config", response_class=HTMLResponse)
async def duty_config_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """排班設定頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)
    config = duty_service.get_config()

    # 載入排班規則
    duty_rules = duty_service.get_rules('duty')
    leader_rules = duty_service.get_rules('leader')

    # 載入可選人員
    duty_eligible = duty_service.get_eligible_users('duty')
    leader_eligible = duty_service.get_eligible_users('leader')

    return templates.TemplateResponse("duty_config.html", {
        "request": request,
        "active_page": "duty",
        "config": config,
        "duty_rules": duty_rules,
        "leader_rules": leader_rules,
        "duty_eligible": duty_eligible,
        "leader_eligible": leader_eligible,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/duty/config")
async def duty_config_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    members_per_day: int = Form(1),
    notify_time: str = Form("08:00"),
    tasks: str = Form(None)
):
    """建立排班設定"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    task_list = []
    if tasks:
        task_list = [t.strip() for t in tasks.strip().split("\n") if t.strip()]

    duty_service.create_config(
        name=name,
        members_per_day=members_per_day,
        notify_time=notify_time,
        tasks=task_list
    )

    return RedirectResponse(
        url="/dashboard/duty/config?success=排班設定已建立",
        status_code=303
    )


@router.post("/dashboard/duty/config/{config_id}")
async def duty_config_update(
    request: Request,
    config_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    members_per_day: int = Form(1),
    notify_time: str = Form("08:00"),
    tasks: str = Form(None),
    is_active: bool = Form(False)
):
    """更新排班設定"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    task_list = []
    if tasks:
        task_list = [t.strip() for t in tasks.strip().split("\n") if t.strip()]

    duty_service.update_config(
        config_id=config_id,
        name=name,
        members_per_day=members_per_day,
        notify_time=notify_time,
        tasks=task_list,
        is_active=is_active
    )

    return RedirectResponse(
        url="/dashboard/duty/config?success=排班設定已更新",
        status_code=303
    )


@router.post("/dashboard/duty/rules/save")
async def duty_rules_save(
    request: Request,
    db: Session = Depends(get_db)
):
    """儲存排班規則"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    form_data = await request.form()
    rule_type = form_data.get("rule_type", "duty")

    weekday_user_map = {}
    for i in range(7):
        raw = form_data.get(f"weekday_{i}", "")
        if raw:
            weekday_user_map[i] = [int(uid) for uid in raw.split(",") if uid.strip()]
        else:
            weekday_user_map[i] = []

    duty_service = DutyService(db)
    duty_service.save_rules(rule_type, weekday_user_map)

    type_label = "值日生" if rule_type == "duty" else "組長"
    return RedirectResponse(
        url=f"/dashboard/duty/config?success={type_label}排班規則已儲存",
        status_code=303
    )


@router.get("/dashboard/duty/schedule", response_class=HTMLResponse)
async def duty_schedule_page(
    request: Request,
    db: Session = Depends(get_db),
    year: int = None,
    month: int = None,
    success: str = None,
    error: str = None
):
    """排班表頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)
    config = duty_service.get_config()

    # 預設當月
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    # 計算上下月
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # 取得月曆資料（不傳 config_id，顯示所有排班）
    calendar_data = duty_service.get_month_schedule(year, month)

    # 計算本月最後一天
    import calendar as cal_module
    _, last_day = cal_module.monthrange(year, month)
    end_of_month = date(year, month, last_day)

    # 取得值日生名單（for 換班選單）
    duty_members = duty_service.get_duty_members()

    return templates.TemplateResponse("duty_schedule.html", {
        "request": request,
        "active_page": "duty",
        "config": config,
        "calendar_data": calendar_data,
        "today": today.isoformat(),
        "today_year": today.year,
        "today_month": today.month,
        "today_day": today.day,
        "end_of_month": end_of_month.isoformat(),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "duty_members": duty_members,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/duty/schedule/generate")
async def duty_schedule_generate(
    request: Request,
    db: Session = Depends(get_db),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    """自動生成排班"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)
    config = duty_service.get_config()

    if not config:
        return RedirectResponse(
            url="/dashboard/duty/schedule?error=請先建立排班設定",
            status_code=303
        )

    try:
        schedules = duty_service.auto_generate_schedule(config.id, start_date, end_date)
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?success=已生成 {len(schedules)} 筆排班",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?error={str(e)}",
            status_code=303
        )


@router.post("/dashboard/duty/schedule/generate-leader")
async def duty_schedule_generate_leader(
    request: Request,
    db: Session = Depends(get_db),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    """自動生成駐店組長排班"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    try:
        schedules = duty_service.auto_generate_leader_schedule(start_date, end_date)
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?success=已生成 {len(schedules)} 筆組長排班",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?error={str(e)}",
            status_code=303
        )


@router.post("/dashboard/duty/schedule/swap")
async def duty_schedule_swap(
    request: Request,
    db: Session = Depends(get_db),
    schedule_id: int = Form(...),
    new_user_id: int = Form(...)
):
    """換班"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    try:
        schedule = duty_service.update_schedule(schedule_id, new_user_id)
        if schedule:
            return RedirectResponse(
                url=f"/dashboard/duty/schedule?success=已將排班更換為 {schedule.user.display_name}",
                status_code=303
            )
        else:
            return RedirectResponse(
                url="/dashboard/duty/schedule?error=找不到該排班",
                status_code=303
            )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?error={str(e)}",
            status_code=303
        )


@router.post("/dashboard/duty/schedule/delete")
async def duty_schedule_delete(
    request: Request,
    db: Session = Depends(get_db),
    schedule_id: int = Form(...)
):
    """刪除排班"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    try:
        success = duty_service.delete_schedule(schedule_id)
        if success:
            return RedirectResponse(
                url="/dashboard/duty/schedule?success=已刪除排班",
                status_code=303
            )
        else:
            return RedirectResponse(
                url="/dashboard/duty/schedule?error=找不到該排班或無法刪除",
                status_code=303
            )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?error={str(e)}",
            status_code=303
        )


@router.post("/dashboard/duty/schedule/clear")
async def duty_schedule_clear(
    request: Request,
    db: Session = Depends(get_db),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    """清除指定日期範圍的排班"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    try:
        count = duty_service.clear_schedules(start_date, end_date)
        if count > 0:
            return RedirectResponse(
                url=f"/dashboard/duty/schedule?success=已清除 {count} 筆排班",
                status_code=303
            )
        else:
            return RedirectResponse(
                url="/dashboard/duty/schedule?success=該日期範圍沒有可清除的排班",
                status_code=303
            )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?error={str(e)}",
            status_code=303
        )


@router.get("/dashboard/duty/reports", response_class=HTMLResponse)
async def duty_reports_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """回報審核頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    pending_reports = duty_service.get_pending_reports()

    # 已審核（最近 20 件）
    reviewed_reports = db.query(DutyReport).filter(
        DutyReport.status != DutyReportStatus.PENDING.value
    ).order_by(DutyReport.reviewed_at.desc()).limit(20).all()

    return templates.TemplateResponse("duty_reports.html", {
        "request": request,
        "active_page": "duty",
        "pending_reports": pending_reports,
        "reviewed_reports": reviewed_reports,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/duty/reports/{report_id}/review")
async def duty_report_review(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    status: str = Form(...),
    note: str = Form(None)
):
    """審核回報"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    # 這裡應該要用登入用戶的 ID，暫時用 1
    reviewer_id = 1

    report = duty_service.review_report(
        report_id=report_id,
        reviewer_id=reviewer_id,
        status=status,
        note=note
    )

    if report:
        status_text = "通過" if status == "approved" else "拒絕"
        return RedirectResponse(
            url=f"/dashboard/duty/reports?success=已{status_text}回報",
            status_code=303
        )

    return RedirectResponse(
        url="/dashboard/duty/reports?error=審核失敗",
        status_code=303
    )


@router.get("/dashboard/duty/complaints", response_class=HTMLResponse)
async def duty_complaints_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """檢舉處理頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    pending_complaints = duty_service.get_pending_complaints()

    # 已處理（最近 20 件）
    handled_complaints = db.query(DutyComplaint).filter(
        DutyComplaint.status != DutyComplaintStatus.PENDING.value
    ).order_by(DutyComplaint.handled_at.desc()).limit(20).all()

    return templates.TemplateResponse("duty_complaints.html", {
        "request": request,
        "active_page": "duty",
        "pending_complaints": pending_complaints,
        "handled_complaints": handled_complaints,
        "success_message": success,
        "error_message": error
    })


@router.post("/dashboard/duty/complaints/{complaint_id}/handle")
async def duty_complaint_handle(
    request: Request,
    complaint_id: int,
    db: Session = Depends(get_db),
    status: str = Form(...),
    note: str = Form(None)
):
    """處理檢舉"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    duty_service = DutyService(db)

    # 這裡應該要用登入用戶的 ID，暫時用 1
    handler_id = 1

    complaint = duty_service.handle_complaint(
        complaint_id=complaint_id,
        handler_id=handler_id,
        status=status,
        note=note
    )

    if complaint:
        status_text = "處理完成" if status == "resolved" else "駁回"
        return RedirectResponse(
            url=f"/dashboard/duty/complaints?success=檢舉已{status_text}",
            status_code=303
        )

    return RedirectResponse(
        url="/dashboard/duty/complaints?error=處理失敗",
        status_code=303
    )


# ========== 人事資料填寫表單（LINE LIFF）==========

@router.get("/info-form", response_class=HTMLResponse)
async def info_form_page(request: Request):
    """人事資料填寫表單頁面（LINE 內使用）"""
    settings = get_settings()
    liff_id = settings.liff_id_info_form or settings.liff_id

    return templates.TemplateResponse("info_form.html", {
        "request": request,
        "liff_id": liff_id
    })


# ========== 人事資料（後台）==========

@router.get("/dashboard/profiles", response_class=HTMLResponse)
async def profiles_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """人事資料列表頁面"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    # 取得已填寫員工資料的用戶
    registered_users = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != ""
    ).order_by(User.real_name).all()

    return templates.TemplateResponse("profiles.html", {
        "request": request,
        "active_page": "profiles",
        "users": registered_users
    })


@router.post("/dashboard/profiles/{user_id}/edit")
async def profiles_edit(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """編輯員工人事資料"""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=303)

    form_data = await request.form()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/dashboard/profiles?error=找不到該用戶", status_code=303)

    real_name = form_data.get("real_name", "").strip()
    nickname = form_data.get("nickname", "").strip()
    phone = form_data.get("phone", "").strip()
    line_display_name = form_data.get("line_display_name", "").strip()
    position = form_data.get("position", "").strip()
    active_status = form_data.get("active_status", "Active").strip()

    if not real_name or not nickname or not phone:
        return RedirectResponse(url="/dashboard/profiles?error=所有欄位皆為必填", status_code=303)

    user.real_name = real_name
    user.nickname = nickname
    user.phone = phone
    user.position = position if position else None
    user.status = active_status
    if line_display_name:
        user.line_display_name = line_display_name

    db.commit()

    return RedirectResponse(url="/dashboard/profiles?success=已更新員工資料", status_code=303)


# ========== 員工資料（Profile LIFF）==========

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """員工資料頁面（需 LINE 登入）"""
    settings = get_settings()
    # 使用員工註冊專用 LIFF ID
    liff_id = settings.liff_id_profile or settings.liff_id

    return templates.TemplateResponse("profile_mobile.html", {
        "request": request,
        "liff_id": liff_id
    })


@router.get("/api/profile")
async def get_profile(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得用戶資料 API"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        return {"success": False, "error": "用戶不存在"}

    return {
        "success": True,
        "real_name": user.real_name,
        "phone": user.phone,
        "nickname": user.nickname,
        "registered": user.registered_at is not None
    }


@router.post("/api/profile")
async def save_profile(
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    line_display_name: str = Form(""),
    real_name: str = Form(...),
    phone: str = Form(...),
    nickname: str = Form(...)
):
    """儲存用戶資料 API"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)

    if not user:
        # 創建新用戶
        user = user_service.create_user(
            line_user_id=line_user_id
        )

    # 已註冊過的用戶不允許再次修改
    if user.registered_at:
        return {"success": False, "error": "您已填寫過員工資料，無法重複填寫"}

    # 更新資料
    if line_display_name.strip():
        user.line_display_name = line_display_name.strip()
    user.real_name = real_name.strip() if real_name else None
    user.phone = phone.strip() if phone else None
    user.nickname = nickname.strip() if nickname else None

    # 設置註冊時間（如果尚未設置）
    if not user.registered_at:
        user.registered_at = datetime.now(timezone.utc)

    db.commit()

    return {"success": True}
