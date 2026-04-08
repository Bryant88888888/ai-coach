from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
from datetime import datetime, date, timezone
import uuid
import os
import secrets

from app.database import get_db
from app.config import get_settings
from app.services.user_service import UserService
from app.services.message_service import MessageService
from app.services.push_service import PushService
from app.services.auth_service import AuthService
from app.services.line_service import LineService
from app.services.course_service import CourseService
from app.services.permission_service import PermissionService
from app.services.morning_report_service import MorningReportService
from app.models.leave_request import LeaveRequest, LeaveStatus
from app.models.user import User, UserRole
from app.models.admin import AdminAccount
from app.models.morning_report import MorningReport
from app.models.training_batch import TrainingBatch
from app.models.user_training import UserTraining, TrainingStatus
from app.models.info_form import InfoFormSubmission
from app.services.training_batch_service import TrainingBatchService
from app.services.storage_service import upload_proof_file

# 設定模板目錄
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(tags=["前端頁面"])


def get_current_admin(request: Request, db: Session) -> AdminAccount | None:
    """從 session 取得目前登入的管理員，未登入返回 None"""
    admin_id = request.session.get("admin_id")
    if admin_id:
        perm_service = PermissionService(db)
        admin = perm_service.get_admin_by_id(admin_id)
        if admin and admin.is_active:
            return admin
        # 帳號不存在或已停用，清除 session
        request.session.clear()
        return None

    # 向下相容：舊 session 只有 authenticated=True
    if request.session.get("authenticated"):
        perm_service = PermissionService(db)
        username = request.session.get("username", "admin")
        admin = perm_service.get_admin_by_username(username)
        if admin and admin.is_active:
            # 遷移 session 到新格式
            request.session["admin_id"] = admin.id
            request.session["display_name"] = admin.display_name
            request.session["is_super_admin"] = admin.is_super_admin
            return admin
        request.session.clear()

    return None


def require_permission(request: Request, db: Session, permission: str) -> AdminAccount | RedirectResponse:
    """檢查登入 + 指定權限。成功返回 AdminAccount，失敗返回 RedirectResponse"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)
    if not admin.has_permission(permission):
        return RedirectResponse(url="/dashboard?error=您沒有此頁面的權限", status_code=303)
    return admin


def build_template_context(request: Request, admin: AdminAccount, db: Session,
                           active_page: str, **extra) -> dict:
    """建立模板上下文，包含側邊欄和權限資料"""
    perm_service = PermissionService(db)
    return {
        "request": request,
        "active_page": active_page,
        "sidebar_items": perm_service.get_visible_sidebar(admin),
        "admin": admin,
        "admin_permissions": perm_service.get_permissions(admin),
        "success_message": request.query_params.get("success"),
        "error_message": request.query_params.get("error"),
        **extra,
    }



@router.get("/debug/duty-rules")
async def debug_duty_rules(db: Session = Depends(get_db)):
    """臨時 debug：查看值日規則和店家狀態"""
    from app.models.duty_rule import DutyRule
    from app.models.duty_config import DutyConfig
    from app.models.duty_schedule import DutySchedule
    rules = db.query(DutyRule).filter(DutyRule.rule_type == 'duty').all()
    configs = db.query(DutyConfig).all()
    weekday_names = ['一', '二', '三', '四', '五', '六', '日']

    # 查看本月排班
    today = date.today()
    month_start = date(today.year, today.month, 1)
    schedules = db.query(DutySchedule).filter(
        DutySchedule.duty_date >= month_start,
        DutySchedule.duty_date <= today,
    ).order_by(DutySchedule.duty_date).limit(30).all()

    return {
        "configs": [{"id": c.id, "name": c.name, "is_active": c.is_active} for c in configs],
        "rules": [{"id": r.id, "weekday": f"星期{weekday_names[r.weekday]}", "user_id": r.user_id, "user_name": r.user.real_name if r.user else None, "config_id": r.config_id} for r in rules],
        "rules_count": len(rules),
        "recent_schedules": [{
            "id": s.id,
            "date": s.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[s.duty_date.weekday()]}",
            "user_id": s.user_id,
            "user_name": s.user.real_name if s.user else None,
            "config_id": s.config_id,
            "config_name": s.config.name if s.config else None,
            "status": s.status,
        } for s in schedules],
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    """登入頁面"""
    if get_current_admin(request, db):
        return RedirectResponse(url="/dashboard", status_code=303)
    settings = get_settings()
    liff_id = settings.liff_id_admin or settings.liff_id
    return templates.TemplateResponse("login.html", {
        "request": request,
        "liff_id": liff_id,
    })


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    """處理登入（支援 LINE ID 或帳密）"""
    form_data = await request.form()
    line_user_id = form_data.get("line_user_id", "")
    username = form_data.get("username", "")
    password = form_data.get("password", "")

    perm_service = PermissionService(db)
    settings = get_settings()
    liff_id = settings.liff_id_admin or settings.liff_id
    admin = None

    if line_user_id:
        # LINE 登入模式
        admin = perm_service.get_admin_by_line_user_id(line_user_id)
        if not admin:
            # 檢查 User 表
            user = db.query(User).filter(User.line_user_id == line_user_id).first()
            if not user:
                return templates.TemplateResponse("login.html", {
                    "request": request, "error": "您不是本公司員工，無法登入", "liff_id": liff_id,
                })
            if not user.real_name:
                return templates.TemplateResponse("login.html", {
                    "request": request, "error": "請先填寫員工資料後再登入", "liff_id": liff_id,
                })
            if not user.is_approved:
                return templates.TemplateResponse("login.html", {
                    "request": request, "error": "您的帳號尚在審核中，請等待主管開通", "liff_id": liff_id,
                })
            # 已開通但沒有 AdminAccount（理論上不應該，開通時就建了）→ 補建
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "帳號異常，請聯繫管理者", "liff_id": liff_id,
            })
        if not admin.is_active:
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "您的帳號已停用，請聯繫管理者", "liff_id": liff_id,
            })
    elif username and password:
        # 傳統帳密登入（向後兼容）
        admin = perm_service.get_admin_by_username(username)
        if not admin or not admin.is_active or not perm_service.verify_password(password, admin.password_hash):
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "帳號或密碼錯誤", "liff_id": liff_id,
            })
    else:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "登入資訊不完整", "liff_id": liff_id,
        })

    # 設定 session
    request.session["authenticated"] = True
    request.session["admin_id"] = admin.id
    request.session["username"] = admin.username
    request.session["display_name"] = admin.display_name
    request.session["is_super_admin"] = admin.is_super_admin
    admin.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """登出"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """儀表板首頁（所有登入用戶都能進入，內容根據權限顯示）"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)

    # 沒有 dashboard:view 權限 → 顯示空白歡迎頁
    if not admin.has_permission("dashboard:view"):
        ctx = build_template_context(request, admin, db, "dashboard")
        ctx["no_dashboard_permission"] = True
        return templates.TemplateResponse("dashboard.html", ctx)

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

    # ========== 招募績效統計 ==========
    import json as json_lib
    import calendar

    def months_ago(dt, n):
        """回傳 n 個月前的月初日期"""
        y, m = dt.year, dt.month
        for _ in range(n):
            m -= 1
            if m < 1:
                m = 12
                y -= 1
        return datetime(y, m, 1)

    now = datetime.utcnow()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = months_ago(now, 1)

    pr_submissions = db.query(InfoFormSubmission).filter(
        InfoFormSubmission.form_type == "公關版本"
    ).order_by(InfoFormSubmission.created_at.desc()).all()

    # 解析所有提交
    parsed_recruits = []
    for sub in pr_submissions:
        try:
            data = json_lib.loads(sub.form_data)
            manager = data.get("manager", "").strip()
            if not manager:
                continue
            # 統一為 naive datetime 處理
            cat = sub.created_at
            if cat and cat.tzinfo is not None:
                cat = cat.replace(tzinfo=None)
            parsed_recruits.append({
                "manager": manager,
                "stage_name": data.get("stage_name") or data.get("real_name") or "未知",
                "store": data.get("store", ""),
                "status": data.get("status", ""),
                "created_at": cat,
            })
        except Exception:
            continue

    total_pr = len(parsed_recruits)
    current_month_recruits = [r for r in parsed_recruits if r["created_at"] and r["created_at"] >= current_month_start]
    last_month_recruits = [r for r in parsed_recruits if r["created_at"] and last_month_start <= r["created_at"] < current_month_start]
    current_month_count = len(current_month_recruits)
    last_month_count = len(last_month_recruits)
    month_delta = round((current_month_count - last_month_count) / last_month_count * 100, 1) if last_month_count > 0 else (100.0 if current_month_count > 0 else 0)
    contract_count = len([r for r in parsed_recruits if r["status"] == "合約"])
    white_paper_count = len([r for r in parsed_recruits if r["status"] == "白紙"])
    contract_rate = round(contract_count / total_pr * 100, 1) if total_pr > 0 else 0

    # 近 12 個月趨勢
    monthly_trend = []
    for i in range(11, -1, -1):
        m_start = months_ago(now, i)
        label = m_start.strftime("%Y/%m")
        if i > 0:
            m_end = months_ago(now, i - 1)
        else:
            # 本月結束 = 下個月月初
            y, mo = m_start.year, m_start.month + 1
            if mo > 12:
                mo = 1
                y += 1
            m_end = datetime(y, mo, 1)
        count = len([r for r in parsed_recruits if r["created_at"] and m_start <= r["created_at"] < m_end])
        monthly_trend.append({"label": label, "count": count})

    # 經紀人個別統計
    agent_map = {}
    for r in parsed_recruits:
        name = r["manager"]
        if name not in agent_map:
            agent_map[name] = {
                "name": name,
                "total_count": 0,
                "current_month_count": 0,
                "last_month_count": 0,
                "contract_count": 0,
                "latest_date": None,
                "recruits": [],
            }
        a = agent_map[name]
        a["total_count"] += 1
        if r["status"] == "合約":
            a["contract_count"] += 1
        if r["created_at"] and r["created_at"] >= current_month_start:
            a["current_month_count"] += 1
        if r["created_at"] and last_month_start <= r["created_at"] < current_month_start:
            a["last_month_count"] += 1
        if a["latest_date"] is None or (r["created_at"] and r["created_at"] > a["latest_date"]):
            a["latest_date"] = r["created_at"]
        a["recruits"].append({
            "name": r["stage_name"],
            "store": r["store"],
            "status": r["status"],
            "date": r["created_at"].strftime("%m/%d") if r["created_at"] else "",
        })

    # 計算衍生欄位與排名
    agent_stats = sorted(agent_map.values(), key=lambda x: x["total_count"], reverse=True)
    agent_stats_by_month = sorted(agent_map.values(), key=lambda x: x["current_month_count"], reverse=True)

    for i, a in enumerate(agent_stats):
        a["rank_total"] = i + 1
        a["contract_rate"] = round(a["contract_count"] / a["total_count"] * 100, 1) if a["total_count"] > 0 else 0
        lm = a["last_month_count"]
        cm = a["current_month_count"]
        a["monthly_delta"] = round((cm - lm) / lm * 100, 1) if lm > 0 else (100.0 if cm > 0 else 0)

        # 趨勢判斷：以前好現在差 / 穩定成長 / 持平 / 下滑
        if lm > 0 and cm == 0:
            a["trend"] = "declining"      # 上月有進人，本月掛零
            a["trend_label"] = "本月掛零"
        elif lm > 0 and cm < lm:
            a["trend"] = "slowing"        # 有在進但比上月少
            a["trend_label"] = "較上月減少"
        elif cm > lm:
            a["trend"] = "growing"        # 成長中
            a["trend_label"] = "成長中"
        elif cm == lm and cm > 0:
            a["trend"] = "stable"         # 持平
            a["trend_label"] = "持平"
        elif a["total_count"] > 0 and cm == 0 and lm == 0:
            a["trend"] = "inactive"       # 連續兩月無進人
            a["trend_label"] = "已停滯"
        else:
            a["trend"] = "new"
            a["trend_label"] = "新進"

    # 合約率排名
    agent_stats_by_contract = sorted(agent_map.values(), key=lambda x: x.get("contract_rate", 0), reverse=True)
    for i, a in enumerate(agent_stats_by_contract):
        agent_map[a["name"]]["rank_contract"] = i + 1

    for i, a in enumerate(agent_stats_by_month):
        agent_map[a["name"]]["rank_current"] = i + 1

    # Tier 分級（含警示）
    n = len(agent_stats)
    for a in agent_stats:
        rc = a.get("rank_current", 999)
        rt = a["rank_total"]
        trend = a.get("trend", "")

        # 優先判斷警示狀態
        if trend in ("declining", "inactive") and a["current_month_count"] == 0:
            a["tier"] = "warning"  # 需要關注
        elif rc == 1 and a["current_month_count"] >= 1:
            a["tier"] = "fire"
        elif rt <= max(1, n * 0.25):
            a["tier"] = "gold"
        elif rt <= max(2, n * 0.5):
            a["tier"] = "silver"
        elif rt <= max(3, n * 0.75):
            a["tier"] = "bronze"
        else:
            a["tier"] = "standard"

    # 本月最佳經紀人
    top_agent_month = agent_stats_by_month[0] if agent_stats_by_month and agent_stats_by_month[0]["current_month_count"] > 0 else None

    # Chart.js 資料
    agent_chart_data = [{"name": a["name"], "count": a["total_count"], "tier": a["tier"]} for a in agent_stats[:10]]

    # 店家分佈統計
    store_counts = {}
    for r in parsed_recruits:
        store = r.get("store", "").strip()
        if store:
            store_counts[store] = store_counts.get(store, 0) + 1
    store_distribution = sorted(store_counts.items(), key=lambda x: x[1], reverse=True)
    store_chart_data = [{"name": s, "count": c} for s, c in store_distribution[:10]]

    # 異動資料統計
    transfer_submissions = db.query(InfoFormSubmission).filter(
        InfoFormSubmission.form_type == "異動資料"
    ).order_by(InfoFormSubmission.created_at.desc()).all()

    transfers = []
    transfer_flow = {}  # { "經紀人A → 經紀人B": count }
    for sub in transfer_submissions:
        try:
            data = json_lib.loads(sub.form_data)
            cat = sub.created_at
            if cat and cat.tzinfo is not None:
                cat = cat.replace(tzinfo=None)
            t = {
                "old_store": data.get("old_store", ""),
                "old_stage_name": data.get("old_stage_name", ""),
                "old_manager": data.get("old_manager", ""),
                "new_store": data.get("new_store", ""),
                "new_stage_name": data.get("new_stage_name", ""),
                "new_manager": data.get("new_manager", ""),
                "status": data.get("status", ""),
                "note": data.get("note", ""),
                "date": cat.strftime("%m/%d") if cat else "",
                "created_at": cat,
            }
            transfers.append(t)
            # 經紀人流動統計
            om = t["old_manager"].strip()
            nm = t["new_manager"].strip()
            if om and nm and om != nm:
                key = f"{om} → {nm}"
                transfer_flow[key] = transfer_flow.get(key, 0) + 1
        except Exception:
            continue

    transfer_flow_sorted = sorted(transfer_flow.items(), key=lambda x: x[1], reverse=True)

    # 最近動態（合併進人+異動，取最近 15 筆）
    recent_activities = []
    for r in parsed_recruits:
        if r["created_at"]:
            recent_activities.append({
                "type": "recruit",
                "date": r["created_at"],
                "date_str": r["created_at"].strftime("%m/%d %H:%M"),
                "name": r["stage_name"],
                "manager": r["manager"],
                "store": r["store"],
                "status": r["status"],
            })
    for t in transfers:
        if t["created_at"]:
            recent_activities.append({
                "type": "transfer",
                "date": t["created_at"],
                "date_str": t["created_at"].strftime("%m/%d %H:%M"),
                "name": t["old_stage_name"],
                "old_manager": t["old_manager"],
                "new_manager": t["new_manager"],
                "old_store": t["old_store"],
                "new_store": t["new_store"],
            })
    recent_activities.sort(key=lambda x: x["date"], reverse=True)
    recent_activities = recent_activities[:15]

    recruitment = {
        "total_pr": total_pr,
        "current_month_count": current_month_count,
        "last_month_count": last_month_count,
        "month_delta": month_delta,
        "contract_count": contract_count,
        "white_paper_count": white_paper_count,
        "contract_rate": contract_rate,
        "monthly_trend_json": json_lib.dumps(monthly_trend, ensure_ascii=False),
        "agent_chart_json": json_lib.dumps(agent_chart_data, ensure_ascii=False),
        "store_chart_json": json_lib.dumps(store_chart_data, ensure_ascii=False),
        "top_agent": top_agent_month,
    }

    ctx = build_template_context(request, admin, db, "dashboard")
    ctx.update({
        "stats": stats,
        "recent_messages": recent_messages,
        "push_stats": push_stats,
        "unresponded_pushes": unresponded_pushes,
        "recruitment": recruitment,
        "agent_stats": agent_stats,
        "transfers": transfers[:20],
        "transfer_flow": transfer_flow_sorted[:10],
        "recent_activities": recent_activities,
        "current_month_label": now.strftime("%Y 年 %m 月"),
    })
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/dashboard/users", response_class=HTMLResponse)
async def users_list(request: Request, db: Session = Depends(get_db)):
    """用戶列表頁面"""
    result = require_permission(request, db, "users:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    user_service = UserService(db)
    users = user_service.get_all_users()

    return templates.TemplateResponse("users.html", build_template_context(
        request, admin, db, "users",
        users=users,
    ))


@router.get("/dashboard/users/{line_user_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    line_user_id: str,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """用戶詳情頁面"""
    result = require_permission(request, db, "users:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    user_service = UserService(db)
    message_service = MessageService(db)
    course_service = CourseService(db)

    user = user_service.get_user_by_line_id(line_user_id)
    if not user:
        return templates.TemplateResponse("error.html", build_template_context(
            request, admin, db, "users",
            error="用戶不存在",
        ), status_code=404)

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

    return templates.TemplateResponse("user_detail.html", build_template_context(
        request, admin, db, "users",
        user=user,
        messages=messages,
        stats=stats,
        user_trainings=user_trainings,
        course_versions=all_versions,
        version_days=version_days,
    ))


@router.get("/dashboard/messages", response_class=HTMLResponse)
async def messages_list(request: Request, db: Session = Depends(get_db)):
    """對話記錄頁面"""
    result = require_permission(request, db, "messages:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    message_service = MessageService(db)
    messages = message_service.get_all_messages(limit=200)

    return templates.TemplateResponse("messages.html", build_template_context(
        request, admin, db, "messages",
        messages=messages,
    ))


@router.get("/dashboard/days", response_class=HTMLResponse)
async def days_list(
    request: Request,
    db: Session = Depends(get_db),
    version: str = None,
    success: str = None,
    error: str = None
):
    """課程管理頁面"""
    result = require_permission(request, db, "courses:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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

    return templates.TemplateResponse("days.html", build_template_context(
        request, admin, db, "days",
        days=days,
        versions=versions,
        current_version=current_version,
        version_stats=version_stats,
    ))


@router.get("/dashboard/days/create", response_class=HTMLResponse)
async def day_create_page(
    request: Request,
    db: Session = Depends(get_db),
    version: str = "v1"
):
    """新增課程頁面"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    course_service = CourseService(db)
    versions = course_service.get_course_versions()
    if not versions:
        versions = ["v1"]

    # 取得該版本已有的最大 day 數
    courses = course_service.get_courses_by_version(version)
    next_day = max([c.day for c in courses], default=-1) + 1

    return templates.TemplateResponse("day_edit.html", build_template_context(
        request, admin, db, "days",
        day={
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
        is_new=True,
        current_version=version,
        versions=versions,
    ))


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
    course_version: str = Form("v1"),
    concept_content: str = Form(None),
    script_content: str = Form(None),
    task_content: str = Form(None),
    passing_score: int = Form(60),
):
    """儲存新課程"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
            system_prompt=system_prompt.strip() if system_prompt else None,
            concept_content=concept_content.strip() if concept_content else None,
            script_content=script_content.strip() if script_content else None,
            task_content=task_content.strip() if task_content else None,
            passing_score=passing_score,
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
    result = require_permission(request, db, "courses:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    course_service = CourseService(db)
    course = course_service.get_course_by_day(day, version)

    if not course:
        return templates.TemplateResponse("error.html", build_template_context(
            request, admin, db, "days",
            error=f"Day {day} 在版本 {version} 中不存在",
        ), status_code=404)

    versions = course_service.get_course_versions()

    return templates.TemplateResponse("day_edit.html", build_template_context(
        request, admin, db, "days",
        day=course.to_dict(),
        course_id=course.id,
        is_new=False,
        current_version=version,
        versions=versions,
    ))


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
    course_version: str = Form("v1"),
    concept_content: str = Form(None),
    script_content: str = Form(None),
    task_content: str = Form(None),
    passing_score: int = Form(60),
):
    """儲存課程編輯"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    course_service = CourseService(db)
    course = course_service.get_course(course_id)

    if not course:
        return templates.TemplateResponse("error.html", build_template_context(
            request, admin, db, "days",
            error="課程不存在",
        ), status_code=404)

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
            system_prompt=system_prompt.strip() if system_prompt else None,
            concept_content=concept_content.strip() if concept_content else None,
            script_content=script_content.strip() if script_content else None,
            task_content=task_content.strip() if task_content else None,
            passing_score=passing_score,
        )

        # 重新取得更新後的課程資料
        course = course_service.get_course(course_id)
        versions = course_service.get_course_versions()

        return templates.TemplateResponse("day_edit.html", build_template_context(
            request, admin, db, "days",
            day=course.to_dict(),
            course_id=course.id,
            is_new=False,
            current_version=course_version,
            versions=versions,
            success=True,
        ))
    except Exception as e:
        versions = course_service.get_course_versions()
        return templates.TemplateResponse("day_edit.html", build_template_context(
            request, admin, db, "days",
            day=course.to_dict(),
            course_id=course.id,
            is_new=False,
            current_version=course_version,
            versions=versions,
            error=f"儲存失敗：{str(e)}",
        ))


@router.post("/dashboard/days/{course_id}/delete")
async def day_delete(
    request: Request,
    course_id: int,
    db: Session = Depends(get_db)
):
    """刪除課程"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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



@router.get("/dashboard/leave", response_class=HTMLResponse)
async def leave_manage(request: Request, db: Session = Depends(get_db)):
    """請假管理頁面（管理員）"""
    result = require_permission(request, db, "leave:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 取得所有請假申請
    leave_requests = db.query(LeaveRequest).order_by(LeaveRequest.created_at.desc()).all()

    # 統計
    pending_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.PENDING.value).count()
    approved_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.APPROVED.value).count()
    rejected_count = db.query(LeaveRequest).filter(LeaveRequest.status == LeaveStatus.REJECTED.value).count()

    return templates.TemplateResponse("leave_manage.html", build_template_context(
        request, admin, db, "leave",
        leave_requests=leave_requests,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
    ))


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


@router.get("/api/verify-employee")
async def verify_employee(line_user_id: str, app: str = None, db: Session = Depends(get_db)):
    """驗證 LINE ID 是否為已註冊且已開通的員工（供外部專案呼叫）

    參數:
        line_user_id: LINE User ID
        app: 要驗證的應用名稱（如 pdf_signing），會額外檢查該應用的存取權限
    """
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)
    if not user or not user.real_name or not user.is_approved:
        return {"authorized": False}

    # 如果指定了 app，檢查該應用的存取權限
    if app == "pdf_signing":
        permissions = user.get_pdf_permissions()
        if not permissions:
            return {"authorized": False, "reason": "no_app_access"}
        return {
            "authorized": True,
            "name": user.real_name,
            "nickname": user.nickname,
            "phone": user.phone,
            "permissions": permissions,
        }

    return {
        "authorized": True,
        "name": user.real_name,
        "nickname": user.nickname,
        "phone": user.phone,
    }


@router.get("/api/leave/profile")
async def leave_profile_lookup(line_user_id: str, db: Session = Depends(get_db)):
    """根據 LINE ID 查詢員工資料（供請假表單自動帶入）"""
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)
    if not user or not user.real_name:
        return {"found": False}
    return {"found": True, "real_name": user.real_name}


@router.post("/leave")
async def leave_apply_submit(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
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
            "liff_id": settings.liff_id_leave or settings.liff_id,
            "is_public": True,
            "error": "當日請假需在下午 5 點前提出申請，請選擇其他日期"
        })

    try:
        # 根據 LINE ID 查找使用者（必須已註冊）
        user = user_service.get_user_by_line_id(line_user_id)
        if not user or not user.real_name:
            return templates.TemplateResponse("leave_form.html", {
                "request": request,
                "liff_id": settings.liff_id_leave or settings.liff_id,
                "is_public": True,
                "error": "您尚未完成員工註冊，請先完成註冊後再申請請假"
            })

        full_name = user.real_name

        # 處理檔案上傳到 Supabase Storage
        proof_url = None
        if proof_file and proof_file.filename:
            proof_url = await upload_proof_file(proof_file)

        leave_request = LeaveRequest(
            user_id=user.id,
            applicant_name=full_name,
            line_display_name=user.line_display_name,
            line_picture_url=user.line_picture_url,
            leave_type=leave_type,
            leave_date=leave_date,
            reason=reason if leave_type == "事假" else None,
            proof_file=proof_url if leave_type == "病假" else None,
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
        # 上傳到 Supabase Storage
        proof_url = await upload_proof_file(proof_file)

        # 更新資料庫
        leave_request.proof_file = proof_url
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
    result = require_permission(request, db, "leave:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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


# ========== 主管管理（使用 LineContact） ==========

@router.get("/dashboard/managers", response_class=HTMLResponse)
async def managers_list(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """主管管理頁面 - 使用 LineContact（可推播的 LINE 聯絡人）"""
    from app.models.line_contact import LineContact
    result = require_permission(request, db, "managers:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 從 line_contacts 查詢主管
    managers = db.query(LineContact).filter(
        LineContact.is_manager == True
    ).order_by(LineContact.created_at.desc()).all()

    # 取得所有非主管的 LineContact（用於新增主管時選擇）
    all_users = db.query(LineContact).filter(
        LineContact.is_manager == False
    ).order_by(LineContact.line_display_name).all()

    from app.models.user import NOTIFICATION_CATEGORIES
    return templates.TemplateResponse("managers.html", build_template_context(
        request, admin, db, "managers",
        managers=managers,
        all_users=all_users,
        notification_categories=NOTIFICATION_CATEGORIES,
    ))


@router.post("/dashboard/managers/add")
async def manager_add(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Form(None),
    name: str = Form(None),
    line_user_id: str = Form(None)
):
    """新增主管 - 從 LineContact 選擇或輸入新的 LINE ID"""
    from app.models.line_contact import LineContact
    result = require_permission(request, db, "managers:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    if user_id:
        # 從現有 LineContact 設為主管
        contact = db.query(LineContact).filter(LineContact.id == user_id).first()
        if not contact:
            return RedirectResponse(
                url="/dashboard/managers?error=聯絡人不存在",
                status_code=303
            )

        if contact.is_manager:
            return RedirectResponse(
                url=f"/dashboard/managers?error=此聯絡人已是主管",
                status_code=303
            )

        contact.is_manager = True
        contact.manager_notification_enabled = True
        db.commit()

        return RedirectResponse(
            url=f"/dashboard/managers?success=已將「{contact.display_name}」設為主管",
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

        # 檢查是否已存在於 line_contacts
        existing = db.query(LineContact).filter(LineContact.line_user_id == line_user_id).first()
        if existing:
            if existing.is_manager:
                return RedirectResponse(
                    url=f"/dashboard/managers?error=此聯絡人已是主管（{existing.display_name}）",
                    status_code=303
                )
            existing.is_manager = True
            existing.manager_notification_enabled = True
            db.commit()
            return RedirectResponse(
                url=f"/dashboard/managers?success=已將「{existing.display_name}」設為主管",
                status_code=303
            )
        else:
            # 建立新的 LineContact
            new_contact = LineContact(
                line_user_id=line_user_id,
                line_display_name=name.strip() if name else None,
                is_manager=True,
                manager_notification_enabled=True,
            )
            db.add(new_contact)
            db.commit()
            return RedirectResponse(
                url=f"/dashboard/managers?success=已成功新增主管「{name or line_user_id[:10]}...」",
                status_code=303
            )

    return RedirectResponse(
        url="/dashboard/managers?error=請選擇聯絡人或輸入 LINE User ID",
        status_code=303
    )


@router.post("/dashboard/managers/{contact_id}/toggle")
async def manager_toggle(
    request: Request,
    contact_id: int,
    db: Session = Depends(get_db)
):
    """切換主管通知狀態"""
    from app.models.line_contact import LineContact
    result = require_permission(request, db, "managers:edit")
    if isinstance(result, RedirectResponse):
        return result

    contact = db.query(LineContact).filter(LineContact.id == contact_id).first()
    if contact and contact.is_manager:
        contact.manager_notification_enabled = not contact.manager_notification_enabled
        db.commit()
        status = "啟用" if contact.manager_notification_enabled else "停用"
        return RedirectResponse(
            url=f"/dashboard/managers?success=已{status}「{contact.display_name}」的通知",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/managers", status_code=303)


@router.post("/dashboard/managers/{contact_id}/categories")
async def manager_update_categories(
    request: Request,
    contact_id: int,
    db: Session = Depends(get_db),
):
    """更新主管通知類別"""
    from app.models.line_contact import LineContact
    result = require_permission(request, db, "managers:edit")
    if isinstance(result, RedirectResponse):
        return result

    form = await request.form()
    categories = form.getlist("categories")

    contact = db.query(LineContact).filter(LineContact.id == contact_id).first()
    if contact and contact.is_manager:
        from app.models.user import ALL_NOTIFICATION_CATEGORIES
        if set(categories) >= set(ALL_NOTIFICATION_CATEGORIES):
            contact.manager_notification_categories = None
        else:
            contact.set_notification_categories(categories)
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/managers?success=已更新「{contact.display_name}」的通知類別",
            status_code=303
        )

    return RedirectResponse(url="/dashboard/managers", status_code=303)


@router.post("/dashboard/managers/{contact_id}/delete")
async def manager_delete(
    request: Request,
    contact_id: int,
    db: Session = Depends(get_db)
):
    """移除主管角色"""
    from app.models.line_contact import LineContact
    result = require_permission(request, db, "managers:edit")
    if isinstance(result, RedirectResponse):
        return result

    contact = db.query(LineContact).filter(LineContact.id == contact_id).first()
    if contact and contact.is_manager:
        name = contact.display_name
        contact.is_manager = False
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
    result = require_permission(request, db, "training:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    batch_service = TrainingBatchService(db)
    batches = batch_service.get_all_batches()

    # 計算每個批次的統計資料
    batch_stats = {}
    for batch in batches:
        batch_stats[batch.id] = batch_service.get_batch_stats(batch.id)

    return templates.TemplateResponse("training.html", build_template_context(
        request, admin, db, "training",
        batches=batches,
        batch_stats=batch_stats,
    ))


@router.post("/dashboard/training/batch/create")
async def training_batch_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    description: str = Form(None),
    course_version: str = Form("v1")
):
    """建立新的訓練批次"""
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    batch_service = TrainingBatchService(db)
    batch = batch_service.get_batch(batch_id)

    if not batch:
        return templates.TemplateResponse("error.html", build_template_context(
            request, admin, db, "training",
            error="找不到此訓練批次",
        ), status_code=404)

    # 取得批次中的用戶訓練
    user_trainings = batch_service.get_batch_users(batch_id)
    stats = batch_service.get_batch_stats(batch_id)

    # 取得所有未加入此批次的用戶（用於新增用戶）
    user_service = UserService(db)
    all_users = user_service.get_all_users()
    batch_user_ids = {ut.user_id for ut in user_trainings}
    available_users = [u for u in all_users if u.id not in batch_user_ids]

    return templates.TemplateResponse("training_batch.html", build_template_context(
        request, admin, db, "training",
        batch=batch,
        user_trainings=user_trainings,
        stats=stats,
        available_users=available_users,
    ))


@router.post("/dashboard/training/batch/{batch_id}/toggle")
async def training_batch_toggle(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db)
):
    """切換批次啟用狀態"""
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "training:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "users:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "users:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "users:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "users:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
            from app.services.line_service import get_pushable_line_id
            pushable_id = get_pushable_line_id(user, db)
            if not pushable_id:
                return RedirectResponse(
                    url=f"/dashboard/users/{line_user_id}?error=此用戶無可推播的 LINE ID",
                    status_code=303
                )
            push_service._send_push_message(
                user_id=pushable_id,
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
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    # 取得統計資料
    duty_stats = duty_service.get_duty_stats()
    duty_members = duty_service.get_duty_members()

    pending_swaps = duty_service.get_all_swaps(status="pending")

    stats = {
        "duty_members": len(duty_members),
        "pending_reports": duty_stats.get("pending_reports", 0),
        "pending_complaints": duty_stats.get("pending_complaints", 0),
        "pending_swaps": len(pending_swaps),
        "approved": duty_stats.get("approved", 0)
    }

    # 今日值日
    today_duty = duty_service.get_today_duty()

    return templates.TemplateResponse("duty.html", build_template_context(
        request, admin, db, "duty",
        stats=stats,
        today_duty=today_duty,
    ))


@router.get("/dashboard/duty/members", response_class=HTMLResponse)
async def duty_members_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    """值日生名單頁面 - 只列出已填寫員工資料的用戶"""
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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

    return templates.TemplateResponse("duty_members.html", build_template_context(
        request, admin, db, "duty",
        all_users=registered_users,
        duty_member_ids=duty_member_ids,
    ))


@router.post("/dashboard/duty/members/update")
async def duty_members_update(
    request: Request,
    db: Session = Depends(get_db)
):
    """批次更新值日生名單"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)
    config = duty_service.get_config()

    # 載入所有店家設定及其排班規則
    store_configs = duty_service.get_store_configs()
    store_rules = {}
    for sc in store_configs:
        store_rules[sc.id] = duty_service.get_rules('duty', config_id=sc.id)

    # 載入無 config_id 的舊規則（向後兼容）
    legacy_duty_rules = duty_service.get_rules('duty', config_id=None)
    leader_rules = duty_service.get_rules('leader')

    # 載入可選人員
    duty_eligible = duty_service.get_eligible_users('duty')
    leader_eligible = duty_service.get_eligible_users('leader')

    return templates.TemplateResponse("duty_config.html", build_template_context(
        request, admin, db, "duty",
        config=config,
        store_configs=store_configs,
        store_rules=store_rules,
        legacy_duty_rules=legacy_duty_rules,
        leader_rules=leader_rules,
        duty_eligible=duty_eligible,
        leader_eligible=leader_eligible,
    ))


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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    form_data = await request.form()
    rule_type = form_data.get("rule_type", "duty")
    config_id_raw = form_data.get("config_id", "")
    config_id = int(config_id_raw) if config_id_raw else None

    weekday_user_map = {}
    for i in range(7):
        raw = form_data.get(f"weekday_{i}", "")
        if raw:
            weekday_user_map[i] = [int(uid) for uid in raw.split(",") if uid.strip()]
        else:
            weekday_user_map[i] = []

    duty_service = DutyService(db)
    duty_service.save_rules(rule_type, weekday_user_map, config_id=config_id)

    type_label = "值日生" if rule_type == "duty" else "組長"
    store_name = ""
    if config_id:
        sc = duty_service.get_config(config_id)
        if sc:
            store_name = f"（{sc.name}）"
    return RedirectResponse(
        url=f"/dashboard/duty/config?success={type_label}{store_name}排班規則已儲存",
        status_code=303
    )


@router.post("/dashboard/duty/store/create")
async def duty_store_create(
    request: Request,
    db: Session = Depends(get_db),
    store_name: str = Form(...)
):
    """新增店家"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result

    duty_service = DutyService(db)
    duty_service.create_store_config(store_name.strip())

    return RedirectResponse(
        url=f"/dashboard/duty/config?success=已新增店家「{store_name.strip()}」",
        status_code=303
    )


@router.post("/dashboard/duty/store/{config_id}/delete")
async def duty_store_delete(
    request: Request,
    config_id: int,
    db: Session = Depends(get_db)
):
    """刪除店家"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result

    duty_service = DutyService(db)
    deleted = duty_service.delete_store_config(config_id)

    if deleted:
        return RedirectResponse(
            url="/dashboard/duty/config?success=店家已刪除",
            status_code=303
        )
    return RedirectResponse(
        url="/dashboard/duty/config?error=刪除失敗",
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
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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

    # 取得所有排班設定（for 新增排班選單）
    duty_configs = db.query(DutyConfig).filter(DutyConfig.is_active == True).all()

    ctx = build_template_context(request, admin, db, "duty")
    ctx.update({
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
        "duty_configs": duty_configs,
    })
    return templates.TemplateResponse("duty_schedule.html", ctx)


@router.post("/dashboard/duty/schedule/generate")
async def duty_schedule_generate(
    request: Request,
    db: Session = Depends(get_db),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    """自動生成排班"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    # 對所有店家各自生成排班
    store_configs = duty_service.get_store_configs()
    if not store_configs:
        return RedirectResponse(
            url="/dashboard/duty/schedule?error=請先建立店家排班設定",
            status_code=303
        )

    try:
        total = 0
        details = []
        for sc in store_configs:
            if sc.is_active:
                schedules = duty_service.auto_generate_schedule(sc.id, start_date, end_date)
                total += len(schedules)
                details.append(f"{sc.name}:{len(schedules)}筆")
        detail_str = "，".join(details) if details else ""
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?success=已生成 {total} 筆排班（{detail_str}）",
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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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


@router.post("/dashboard/duty/schedule/add")
async def duty_schedule_add(
    request: Request,
    db: Session = Depends(get_db),
    duty_date: str = Form(...),
    config_id: int = Form(...),
    user_id: int = Form(...)
):
    """手動新增排班"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result

    from app.models.duty_schedule import DutySchedule, DutyScheduleStatus

    try:
        schedule = DutySchedule(
            config_id=config_id,
            user_id=user_id,
            duty_date=date.fromisoformat(duty_date),
            status=DutyScheduleStatus.SCHEDULED.value
        )
        db.add(schedule)
        db.commit()

        target_date = date.fromisoformat(duty_date)
        return RedirectResponse(
            url=f"/dashboard/duty/schedule?year={target_date.year}&month={target_date.month}&success=已新增排班",
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
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    pending_reports = duty_service.get_pending_reports()

    # 已審核（最近 20 件）
    reviewed_reports = db.query(DutyReport).filter(
        DutyReport.status != DutyReportStatus.PENDING.value
    ).order_by(DutyReport.reviewed_at.desc()).limit(20).all()

    return templates.TemplateResponse("duty_reports.html", build_template_context(
        request, admin, db, "duty",
        pending_reports=pending_reports,
        reviewed_reports=reviewed_reports,
    ))


@router.post("/dashboard/duty/reports/{report_id}/review")
async def duty_report_review(
    request: Request,
    report_id: int,
    db: Session = Depends(get_db),
    status: str = Form(...),
    note: str = Form(None)
):
    """審核回報"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    # 透過 admin 的 line_user_id 找到對應的 user
    reviewer_id = None
    if admin.line_user_id:
        linked_user = db.query(User).filter(User.line_user_id == admin.line_user_id).first()
        if linked_user:
            reviewer_id = linked_user.id

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
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    pending_complaints = duty_service.get_pending_complaints()

    # 已處理（最近 20 件）
    handled_complaints = db.query(DutyComplaint).filter(
        DutyComplaint.status != DutyComplaintStatus.PENDING.value
    ).order_by(DutyComplaint.handled_at.desc()).limit(20).all()

    return templates.TemplateResponse("duty_complaints.html", build_template_context(
        request, admin, db, "duty",
        pending_complaints=pending_complaints,
        handled_complaints=handled_complaints,
    ))


@router.post("/dashboard/duty/complaints/{complaint_id}/handle")
async def duty_complaint_handle(
    request: Request,
    complaint_id: int,
    db: Session = Depends(get_db),
    status: str = Form(...),
    note: str = Form(None)
):
    """處理檢舉"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)

    # 透過 admin 的 line_user_id 找到對應的 user
    handler_id = None
    if admin.line_user_id:
        linked_user = db.query(User).filter(User.line_user_id == admin.line_user_id).first()
        if linked_user:
            handler_id = linked_user.id

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


# ========== 換班申請管理 ==========

@router.get("/dashboard/duty/swaps", response_class=HTMLResponse)
async def duty_swaps_page(
    request: Request,
    db: Session = Depends(get_db),
    status_filter: str = None,
    success: str = None,
    error: str = None
):
    """換班申請管理頁面"""
    result = require_permission(request, db, "duty:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)
    swaps = duty_service.get_all_swaps(status=status_filter if status_filter else None)

    return templates.TemplateResponse("duty_swaps.html", build_template_context(
        request, admin, db, "duty",
        swaps=swaps,
        status_filter=status_filter or "all",
        success_message=success,
        error_message=error
    ))


@router.post("/dashboard/duty/swaps/{swap_id}/force")
async def duty_swap_force(
    request: Request,
    swap_id: int,
    db: Session = Depends(get_db),
    action: str = Form(...),
    note: str = Form(None)
):
    """管理員強制核准/拒絕換班申請"""
    result = require_permission(request, db, "duty:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    duty_service = DutyService(db)
    approved = action == "approve"

    res = duty_service.admin_force_swap(
        swap_id=swap_id,
        approved=approved,
        note=note
    )

    if res["success"]:
        action_text = "核准" if approved else "拒絕"
        return RedirectResponse(
            url=f"/dashboard/duty/swaps?success=已{action_text}換班申請",
            status_code=303
        )

    return RedirectResponse(
        url=f"/dashboard/duty/swaps?error={res['error']}",
        status_code=303
    )


# ========== 人事資料填寫表單（LINE LIFF）==========

@router.get("/profile/info-form", response_class=HTMLResponse)
async def info_form_page(request: Request):
    """人事資料填寫表單頁面（LINE 內使用）"""
    settings = get_settings()
    liff_id = settings.liff_id_info_form or settings.liff_id

    return templates.TemplateResponse("info_form.html", {
        "request": request,
        "liff_id": liff_id,
        "today_date": date.today().isoformat(),
    })


@router.post("/api/info-form")
async def submit_info_form(
    request: Request,
    db: Session = Depends(get_db)
):
    """提交人事資料表單（公關版本/經紀人版本/異動資料）"""
    import json

    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "無效的請求資料"}

    line_user_id = data.get("line_user_id")
    form_type = data.get("form_type")

    if not line_user_id or not form_type:
        return {"success": False, "error": "缺少必要欄位"}

    # 查找用戶
    user_service = UserService(db)
    user = user_service.get_user_by_line_id(line_user_id)
    user_id = user.id if user else None

    # 儲存表單資料
    submission = InfoFormSubmission(
        user_id=user_id,
        line_user_id=line_user_id,
        form_type=form_type,
        form_data=json.dumps(data, ensure_ascii=False)
    )
    db.add(submission)
    db.commit()

    # 通知訂閱「人事資料」的主管
    try:
        submitter_name = data.get("real_name") or data.get("nickname") or "未知"
        line_service = LineService()
        line_service.notify_managers_info_form(form_type, submitter_name, db)
    except Exception as e:
        print(f"人事資料通知發送失敗: {e}")

    # 根據版本建立 PDF 簽署任務
    SIGNING_API = "https://pdf-signing-tool.onrender.com"
    FORM_TEMPLATES = {
        "公關版本": [
            {"id": "2f81eedd-fdf8-4399-9b73-19a3b1b1e469", "name": "人力媒合暨合作契約書"},
            {"id": "f328a610-7264-4e4b-8492-99ffc8640a75", "name": "應徵人事資料"},
            {"id": "7b8e6f7b-891a-43e1-86a5-3ca25416007c", "name": "合約封面"},
        ],
        "經紀人版本": [
            {"id": "7b8e6f7b-891a-43e1-86a5-3ca25416007c", "name": "合約封面"},
            {"id": "cdc4f5fa-b58e-47ee-be09-0450b4bc3536", "name": "開發部切結書"},
            {"id": "cf822e17-dade-4a4d-b500-b787f53d5f20", "name": "開發部契約書（正職）"},
        ],
    }

    signing_tasks = []
    templates = FORM_TEMPLATES.get(form_type, [])
    if templates:
        signer_name = data.get("real_name", "").strip() or data.get("nickname", "").strip()
        if signer_name:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    for tmpl in templates:
                        try:
                            resp = await client.post(
                                f"{SIGNING_API}/api/signing-tasks",
                                json={"template_id": tmpl["id"], "signer_name": signer_name}
                            )
                            if resp.status_code == 200:
                                result = resp.json()
                                signing_tasks.append({
                                    "name": tmpl["name"],
                                    "url": f"{SIGNING_API}{result.get('signing_url', '')}",
                                })
                                print(f"簽署任務已建立: {tmpl['name']} for {signer_name}")
                            else:
                                print(f"建立 {tmpl['name']} 失敗: {resp.status_code}")
                        except Exception as e:
                            print(f"建立 {tmpl['name']} 失敗: {e}")
            except Exception as e:
                print(f"建立簽署任務失敗: {e}")

    return {"success": True, "id": submission.id, "signing_tasks": signing_tasks}


# ========== 人事資料（後台）==========

@router.get("/dashboard/profiles", response_class=HTMLResponse)
async def profiles_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """人事資料列表頁面"""
    result = require_permission(request, db, "profiles:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 取得已填寫員工資料的用戶
    registered_users = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != ""
    ).order_by(User.real_name).all()

    return templates.TemplateResponse("profiles.html", build_template_context(
        request, admin, db, "profiles",
        users=registered_users,
    ))


@router.post("/dashboard/profiles/{user_id}/edit")
async def profiles_edit(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """編輯員工人事資料"""
    result = require_permission(request, db, "profiles:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

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


@router.post("/dashboard/admin/pdf/add")
async def pdf_permission_add(
    request: Request,
    db: Session = Depends(get_db),
):
    """新增員工 PDF 簽署權限"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    form = await request.form()
    user_id = form.get("user_id")
    permissions = form.getlist("permissions")

    if not user_id:
        return RedirectResponse(url="/dashboard/admin?error=請選擇員工&tab=apps", status_code=303)

    from app.models.user import PDF_PERMISSIONS
    valid_perms = [p for p in permissions if p in PDF_PERMISSIONS]
    if not valid_perms:
        return RedirectResponse(url="/dashboard/admin?error=請至少選擇一個權限&tab=apps", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return RedirectResponse(url="/dashboard/admin?error=找不到該員工&tab=apps", status_code=303)

    if user.get_pdf_permissions():
        return RedirectResponse(
            url=f"/dashboard/admin?error=「{user.real_name}」已有 PDF 權限，請直接編輯&tab=apps",
            status_code=303
        )

    user.set_pdf_permissions(valid_perms)
    db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin?success=已授予「{user.real_name}」{len(valid_perms)} 項 PDF 權限&tab=apps",
        status_code=303
    )


@router.post("/dashboard/admin/pdf/{user_id}/update")
async def pdf_permission_update(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新員工 PDF 簽署權限"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    form = await request.form()
    permissions = form.getlist("permissions")

    from app.models.user import PDF_PERMISSIONS
    valid_perms = [p for p in permissions if p in PDF_PERMISSIONS]

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/dashboard/admin?error=找不到該員工&tab=apps", status_code=303)

    if not valid_perms:
        user.pdf_signing_permissions = None
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/admin?success=已移除「{user.real_name}」的所有 PDF 權限&tab=apps",
            status_code=303
        )

    user.set_pdf_permissions(valid_perms)
    db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin?success=已更新「{user.real_name}」的 PDF 權限（{len(valid_perms)} 項）&tab=apps",
        status_code=303
    )


@router.post("/dashboard/admin/pdf/{user_id}/remove")
async def pdf_permission_remove(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """移除員工 PDF 簽署權限"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/dashboard/admin?error=找不到該員工&tab=apps", status_code=303)

    name = user.real_name
    user.pdf_signing_permissions = None
    db.commit()
    return RedirectResponse(
        url=f"/dashboard/admin?success=已移除「{name}」的 PDF 簽署權限&tab=apps",
        status_code=303
    )


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

    # 新人預設未開通
    user.is_approved = False

    db.commit()
    db.refresh(user)

    # 自動連結 LineContact（用 line_display_name 比對加好友時建立的記錄）
    try:
        from app.models.line_contact import LineContact
        names_to_match = [n for n in [
            real_name.strip() if real_name else "",
            nickname.strip() if nickname else "",
            line_display_name.strip() if line_display_name else "",
        ] if n]

        if names_to_match:
            # 找名稱吻合的 LineContact（未連結，或連結到未註冊的舊帳號）
            contact = db.query(LineContact).filter(
                LineContact.line_display_name.in_(names_to_match)
            ).first()
            if contact and contact.user_id != user.id:
                contact.user_id = user.id
                db.commit()
                print(f"✅ 自動連結 LineContact: {contact.line_display_name} → {user.real_name}")
    except Exception as e:
        print(f"LineContact 連結失敗（不影響註冊）: {e}")

    # 通知主管有新人報到
    try:
        line_service = LineService()
        line_service.notify_managers_new_employee(user, db)
    except Exception as e:
        print(f"新人通知發送失敗: {e}")

    return {"success": True}


# ========== 權限管理 ==========

@router.get("/dashboard/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    """權限管理頁面"""
    result = require_permission(request, db, "admin:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    perm_service = PermissionService(db)
    from app.models.admin import PERMISSION_REGISTRY

    all_admins = perm_service.get_all_admins()
    all_roles = perm_service.get_all_roles()

    # 計算每個角色使用的帳號數
    role_account_counts = {}
    for role in all_roles:
        role_account_counts[role.id] = len([a for a in all_admins if a.role_id == role.id])

    # 按分組整理權限
    permission_groups = {}
    for perm_key, perm_info in PERMISSION_REGISTRY.items():
        group = perm_info["group"]
        if group not in permission_groups:
            permission_groups[group] = []
        permission_groups[group].append({"key": perm_key, "label": perm_info["label"]})

    # 取得所有已註冊員工（用於新增管理員時選擇）
    employees = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != "",
        User.line_user_id.isnot(None),
    ).order_by(User.real_name).all()

    # 取得有 PDF 簽署權限的員工
    pdf_users = db.query(User).filter(
        User.pdf_signing_permissions.isnot(None),
    ).order_by(User.real_name).all()

    # 取得沒有 PDF 權限的已註冊員工（用於新增時選擇）
    pdf_available_employees = db.query(User).filter(
        User.real_name.isnot(None),
        User.real_name != "",
        User.pdf_signing_permissions.is_(None),
    ).order_by(User.real_name).all()

    from app.models.user import PDF_PERMISSIONS

    return templates.TemplateResponse("admin.html", build_template_context(
        request, admin, db, "admin",
        all_admins=all_admins,
        all_roles=all_roles,
        role_account_counts=role_account_counts,
        permission_groups=permission_groups,
        permission_registry=PERMISSION_REGISTRY,
        employees=employees,
        pdf_users=pdf_users,
        pdf_available_employees=pdf_available_employees,
        pdf_permissions=PDF_PERMISSIONS,
    ))


@router.post("/dashboard/admin/accounts/create")
async def admin_account_create(request: Request, db: Session = Depends(get_db)):
    """建立管理員帳號（從員工列表選擇）"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    form_data = await request.form()
    employee_line_id = form_data.get("employee_line_id", "")
    display_name = form_data.get("display_name", "")
    role_id_raw = form_data.get("role_id", "")
    is_super_admin = form_data.get("is_super_admin") == "on"

    perm_service = PermissionService(db)

    if not employee_line_id:
        return RedirectResponse(
            url="/dashboard/admin?error=請選擇員工&tab=accounts",
            status_code=303
        )

    # 檢查 LINE ID 是否已綁定
    if perm_service.get_admin_by_line_user_id(employee_line_id):
        return RedirectResponse(
            url="/dashboard/admin?error=此員工已有管理員帳號&tab=accounts",
            status_code=303
        )

    # 從 User 表取得員工資訊
    user = db.query(User).filter(User.line_user_id == employee_line_id).first()
    if not user:
        return RedirectResponse(
            url="/dashboard/admin?error=找不到該員工&tab=accounts",
            status_code=303
        )

    final_display_name = display_name.strip() or user.nickname or user.real_name or "管理員"
    username = f"line_{employee_line_id[:16]}"  # 自動生成 username

    try:
        actual_role_id = int(role_id_raw) if role_id_raw and int(role_id_raw) > 0 else None
        admin = perm_service.create_admin(
            username=username,
            password=secrets.token_hex(16),  # 隨機密碼（LINE 登入不需要）
            display_name=final_display_name,
            role_id=actual_role_id,
            is_super_admin=is_super_admin,
        )
        # 綁定 LINE User ID
        admin.line_user_id = employee_line_id
        db.commit()

        return RedirectResponse(
            url=f"/dashboard/admin?success=已建立管理員「{final_display_name}」&tab=accounts",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=accounts",
            status_code=303
        )


@router.post("/dashboard/admin/accounts/{admin_id}/edit")
async def admin_account_edit(
    admin_id: int, request: Request, db: Session = Depends(get_db),
    display_name: str = Form(...), role_id: int = Form(None),
    password: str = Form(""), is_super_admin: bool = Form(False),
):
    """編輯管理員帳號"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    perm_service = PermissionService(db)
    try:
        actual_role_id = role_id if role_id and role_id > 0 else None
        perm_service.update_admin(
            admin_id,
            display_name=display_name,
            role_id=actual_role_id,
            password=password,
            is_super_admin=is_super_admin,
        )
        return RedirectResponse(
            url=f"/dashboard/admin?success=已更新帳號設定&tab=accounts",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=accounts",
            status_code=303
        )


@router.post("/dashboard/admin/accounts/{admin_id}/delete")
async def admin_account_delete(admin_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除管理員帳號"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 不能刪除自己
    if admin.id == admin_id:
        return RedirectResponse(
            url="/dashboard/admin?error=無法刪除自己的帳號&tab=accounts",
            status_code=303
        )

    perm_service = PermissionService(db)
    try:
        target = perm_service.get_admin_by_id(admin_id)
        name = target.display_name if target else "未知"
        perm_service.delete_admin(admin_id)
        return RedirectResponse(
            url=f"/dashboard/admin?success=已刪除帳號「{name}」&tab=accounts",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=accounts",
            status_code=303
        )


@router.post("/dashboard/admin/accounts/{admin_id}/toggle")
async def admin_account_toggle(admin_id: int, request: Request, db: Session = Depends(get_db)):
    """切換管理員啟用狀態"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 不能停用自己
    if admin.id == admin_id:
        return RedirectResponse(
            url="/dashboard/admin?error=無法停用自己的帳號&tab=accounts",
            status_code=303
        )

    perm_service = PermissionService(db)
    try:
        target = perm_service.toggle_admin_active(admin_id)
        status = "啟用" if target.is_active else "停用"
        return RedirectResponse(
            url=f"/dashboard/admin?success=已{status}帳號「{target.display_name}」&tab=accounts",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=accounts",
            status_code=303
        )


@router.post("/dashboard/admin/roles/create")
async def admin_role_create(request: Request, db: Session = Depends(get_db)):
    """建立角色"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    permissions = form.getlist("permissions")

    if not name:
        return RedirectResponse(
            url="/dashboard/admin?error=角色名稱不能為空&tab=roles",
            status_code=303
        )

    perm_service = PermissionService(db)
    try:
        perm_service.create_role(name=name, description=description, permissions=permissions)
        return RedirectResponse(
            url=f"/dashboard/admin?success=已建立角色「{name}」&tab=roles",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=roles",
            status_code=303
        )


@router.post("/dashboard/admin/roles/{role_id}/edit")
async def admin_role_edit(role_id: int, request: Request, db: Session = Depends(get_db)):
    """編輯角色"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    form = await request.form()
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    permissions = form.getlist("permissions")

    perm_service = PermissionService(db)
    try:
        perm_service.update_role(role_id, name=name, description=description, permissions=permissions)
        return RedirectResponse(
            url=f"/dashboard/admin?success=已更新角色「{name}」&tab=roles",
            status_code=303
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=roles",
            status_code=303
        )


@router.post("/dashboard/admin/roles/{role_id}/delete")
async def admin_role_delete(role_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除角色"""
    result = require_permission(request, db, "admin:edit")
    if isinstance(result, RedirectResponse):
        return result

    perm_service = PermissionService(db)
    try:
        role = perm_service.get_role_by_id(role_id)
        name = role.name if role else "未知"
        perm_service.delete_role(role_id)
        return RedirectResponse(
            url=f"/dashboard/admin?success=已刪除角色「{name}」&tab=roles",
            status_code=303
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/dashboard/admin?error={str(e)}&tab=roles",
            status_code=303
        )


# ===== 早會日報表 =====

@router.get("/dashboard/morning-report", response_class=HTMLResponse)
async def morning_report_page(
    request: Request,
    db: Session = Depends(get_db),
    report_date: str = None,
    leader_filter: str = None,
):
    """早會日報表頁面（員工用 morning:edit 即可進入填表）"""
    result = require_permission(request, db, "morning:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 安全解析參數
    try:
        leader_filter_id = int(leader_filter) if leader_filter else None
    except (ValueError, TypeError):
        leader_filter_id = None

    service = MorningReportService(db)
    today = date.today()
    try:
        selected_date = date.fromisoformat(report_date) if report_date else today
    except (ValueError, TypeError):
        selected_date = today

    # 取得所有組長（用於篩選）
    leaders = service.get_all_leaders()

    # 取得當天所有報表
    reports = service.get_reports_by_date(selected_date, leader_id=leader_filter_id)
    reported_user_ids = {r.user_id for r in reports}

    # 取得出勤統計
    attendance = service.get_attendance_stats(selected_date, leader_id=leader_filter_id)

    # 取得所有活躍員工（用於顯示誰未填）
    if leader_filter_id:
        all_members = service.get_team_members(leader_filter_id)
    else:
        all_members = service.get_all_active_users()

    # 區分已填寫和未填寫
    filled_members = [m for m in all_members if m.id in reported_user_ids]
    unfilled_members = [m for m in all_members if m.id not in reported_user_ids]

    # 報表 map（user_id → report）
    report_map = {r.user_id: r for r in reports}

    # 取得當前登入者對應的 User
    current_user = None
    my_report = None
    if admin.line_user_id:
        current_user = db.query(User).filter(User.line_user_id == admin.line_user_id).first()
        if current_user:
            my_report = service.get_report(current_user.id, selected_date)

    ctx = build_template_context(request, admin, db, "morning")
    ctx.update({
        "selected_date": selected_date.isoformat(),
        "today": today.isoformat(),
        "leaders": leaders,
        "leader_filter": leader_filter_id,
        "attendance": attendance,
        "reports": reports,
        "report_map": report_map,
        "filled_members": filled_members,
        "unfilled_members": unfilled_members,
        "current_user": current_user,
        "my_report": my_report,
    })
    return templates.TemplateResponse("morning_report.html", ctx)


@router.post("/dashboard/morning-report/submit")
async def morning_report_submit(request: Request, db: Session = Depends(get_db)):
    """提交/更新早會日報表（支援多筆檢討和分享）"""
    result = require_permission(request, db, "morning:edit")
    if isinstance(result, RedirectResponse):
        return result

    admin = result
    form = await request.form()
    user_id_raw = form.get("user_id", "")
    report_date_str = form.get("report_date", "")

    user_id = int(user_id_raw) if user_id_raw else 0
    if not user_id and admin.line_user_id:
        current_user = db.query(User).filter(User.line_user_id == admin.line_user_id).first()
        if current_user:
            user_id = current_user.id

    if not user_id or not report_date_str:
        return RedirectResponse(url="/dashboard/morning-report?error=缺少必要資訊", status_code=303)

    try:
        report_date_val = date.fromisoformat(report_date_str)
    except (ValueError, TypeError):
        return RedirectResponse(url="/dashboard/morning-report?error=日期格式錯誤", status_code=303)

    leader_id_raw = form.get("leader_id", "")
    try:
        leader_id_val = int(leader_id_raw) if leader_id_raw else None
    except ValueError:
        leader_id_val = None

    # 解析多筆檢討
    # 解析多筆檢討（檢查所有欄位是否存在該 index）
    reviews = []
    for idx in range(50):  # 最多 50 筆
        fields = {k: form.get(f"review_{k}_{idx}", "") for k in
                  ["category", "description", "impact", "solution", "responsible", "deadline", "status"]}
        if not any(fields.values()):
            if idx > 0:
                break  # index 0 之後沒資料就停止
            continue
        fields["status"] = fields["status"] or "未處理"
        reviews.append(fields)

    # 解析多筆分享
    shares = []
    for idx in range(50):
        fields = {k: form.get(f"share_{k}_{idx}", "") for k in
                  ["category", "situation", "solution", "lesson", "scenario", "rating", "note"]}
        if not any(fields.values()):
            if idx > 0:
                break
            continue
        rating = None
        try:
            if fields["rating"]:
                rating = max(1, min(5, int(fields["rating"])))
        except (ValueError, TypeError):
            pass
        fields["rating"] = rating
        shares.append(fields)

    service = MorningReportService(db)
    service.submit_report(user_id, report_date_val, leader_id=leader_id_val, reviews=reviews, shares=shares)

    return RedirectResponse(
        url=f"/dashboard/morning-report?success=日報表已提交",
        status_code=303
    )


@router.get("/dashboard/morning-report/stats", response_class=HTMLResponse)
async def morning_report_stats_page(
    request: Request,
    db: Session = Depends(get_db),
    year: int = None,
    month: int = None,
    leader_filter: str = None,
):
    """早會日報表統計頁面"""
    result = require_permission(request, db, "morning:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    try:
        leader_filter_id = int(leader_filter) if leader_filter else None
    except (ValueError, TypeError):
        leader_filter_id = None

    today = date.today()
    selected_year = year or today.year
    selected_month = month or today.month

    service = MorningReportService(db)
    leaders = service.get_all_leaders()

    monthly = service.get_monthly_stats(selected_year, selected_month, leader_id=leader_filter_id)
    review_stats = service.get_review_stats(selected_year, selected_month, leader_id=leader_filter_id)
    share_stats = service.get_share_stats(selected_year, selected_month, leader_id=leader_filter_id)

    ctx = build_template_context(request, admin, db, "morning")
    ctx.update({
        "selected_year": selected_year,
        "selected_month": selected_month,
        "leaders": leaders,
        "leader_filter": leader_filter_id,
        "monthly": monthly,
        "review_stats": review_stats,
        "share_stats": share_stats,
    })
    return templates.TemplateResponse("morning_report_stats.html", ctx)


# ===== 人事表單後台 =====

@router.get("/dashboard/info-forms", response_class=HTMLResponse)
async def info_forms_page(
    request: Request,
    db: Session = Depends(get_db),
    form_type: str = None,
    search: str = None,
):
    """人事表單列表頁"""
    result = require_permission(request, db, "info_form:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    import json as json_module

    query = db.query(InfoFormSubmission).order_by(InfoFormSubmission.created_at.desc())

    if form_type and form_type in ("公關版本", "經紀人版本", "異動資料"):
        query = query.filter(InfoFormSubmission.form_type == form_type)

    submissions = query.all()

    # 解析 JSON 並篩選搜尋
    parsed = []
    for sub in submissions:
        try:
            data = json_module.loads(sub.form_data) if sub.form_data else {}
        except (json_module.JSONDecodeError, TypeError):
            data = {}

        if search:
            search_lower = search.lower()
            searchable = " ".join(str(v) for v in data.values()).lower()
            if search_lower not in searchable:
                continue

        parsed.append({
            "id": sub.id,
            "form_type": sub.form_type,
            "data": data,
            "created_at": sub.created_at,
            "user": sub.user,
        })

    ctx = build_template_context(request, admin, db, "info_forms")
    ctx.update({
        "submissions": parsed,
        "form_type_filter": form_type or "",
        "search": search or "",
    })
    return templates.TemplateResponse("info_forms.html", ctx)


@router.post("/dashboard/info-forms/{submission_id}/delete")
async def info_form_delete(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """刪除人事表單"""
    result = require_permission(request, db, "info_form:edit")
    if isinstance(result, RedirectResponse):
        return result

    sub = db.query(InfoFormSubmission).filter(InfoFormSubmission.id == submission_id).first()
    if sub:
        db.delete(sub)
        db.commit()
        return RedirectResponse(url="/dashboard/info-forms?success=已刪除", status_code=303)
    return RedirectResponse(url="/dashboard/info-forms?error=找不到記錄", status_code=303)


# ==================== 模擬人設管理 ====================

@router.get("/dashboard/personas", response_class=HTMLResponse)
async def personas_page(
    request: Request,
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None,
    version: str = "v1",
):
    """模擬人設管理頁面"""
    result = require_permission(request, db, "courses:view")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    from app.models.scenario_persona import ScenarioPersona
    personas = (
        db.query(ScenarioPersona)
        .filter(ScenarioPersona.course_version == version)
        .order_by(ScenarioPersona.sort_order, ScenarioPersona.id)
        .all()
    )

    return templates.TemplateResponse("personas.html", build_template_context(
        request, admin, db, "personas",
        personas=personas,
        current_version=version,
        success_message=success,
        error_message=error,
    ))


@router.post("/dashboard/personas/create")
async def persona_create(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(...),
    behavior_traits: str = Form(None),
    opening_templates: str = Form(None),
    difficulty_level: int = Form(1),
    course_version: str = Form("v1"),
):
    """建立模擬人設"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result

    import json
    from app.models.scenario_persona import ScenarioPersona

    try:
        # 將換行分隔的文字轉為 JSON 陣列
        traits_json = None
        if behavior_traits and behavior_traits.strip():
            traits_list = [t.strip() for t in behavior_traits.strip().split('\n') if t.strip()]
            traits_json = json.dumps(traits_list, ensure_ascii=False)

        openings_json = None
        if opening_templates and opening_templates.strip():
            openings_list = [o.strip() for o in opening_templates.strip().split('\n') if o.strip()]
            openings_json = json.dumps(openings_list, ensure_ascii=False)

        persona = ScenarioPersona(
            name=name.strip(),
            code=code.strip(),
            description=description.strip(),
            behavior_traits=traits_json,
            opening_templates=openings_json,
            difficulty_level=difficulty_level,
            course_version=course_version,
        )
        db.add(persona)
        db.commit()

        return RedirectResponse(
            url=f"/dashboard/personas?version={course_version}&success=已建立人設「{name}」",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/personas?version={course_version}&error=建立失敗：{str(e)}",
            status_code=303,
        )


@router.get("/dashboard/personas/{persona_id}/edit", response_class=HTMLResponse)
async def persona_edit_page(
    request: Request,
    persona_id: int,
    db: Session = Depends(get_db),
):
    """編輯人設頁面"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    from app.models.scenario_persona import ScenarioPersona
    persona = db.query(ScenarioPersona).filter(ScenarioPersona.id == persona_id).first()
    if not persona:
        return RedirectResponse(url="/dashboard/personas?error=人設不存在", status_code=303)

    return templates.TemplateResponse("persona_edit.html", build_template_context(
        request, admin, db, "personas",
        persona=persona,
    ))


@router.post("/dashboard/personas/{persona_id}/edit")
async def persona_edit_save(
    request: Request,
    persona_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(...),
    behavior_traits: str = Form(None),
    opening_templates: str = Form(None),
    difficulty_level: int = Form(1),
    is_active: bool = Form(True),
):
    """儲存人設編輯"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result

    import json
    from app.models.scenario_persona import ScenarioPersona
    persona = db.query(ScenarioPersona).filter(ScenarioPersona.id == persona_id).first()
    if not persona:
        return RedirectResponse(url="/dashboard/personas?error=人設不存在", status_code=303)

    try:
        traits_json = None
        if behavior_traits and behavior_traits.strip():
            traits_list = [t.strip() for t in behavior_traits.strip().split('\n') if t.strip()]
            traits_json = json.dumps(traits_list, ensure_ascii=False)

        openings_json = None
        if opening_templates and opening_templates.strip():
            openings_list = [o.strip() for o in opening_templates.strip().split('\n') if o.strip()]
            openings_json = json.dumps(openings_list, ensure_ascii=False)

        persona.name = name.strip()
        persona.code = code.strip()
        persona.description = description.strip()
        persona.behavior_traits = traits_json
        persona.opening_templates = openings_json
        persona.difficulty_level = difficulty_level
        persona.is_active = is_active
        db.commit()

        return RedirectResponse(
            url=f"/dashboard/personas?version={persona.course_version}&success=已更新人設「{name}」",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/dashboard/personas?version={persona.course_version}&error=更新失敗：{str(e)}",
            status_code=303,
        )


@router.post("/dashboard/personas/{persona_id}/delete")
async def persona_delete(
    request: Request,
    persona_id: int,
    db: Session = Depends(get_db),
):
    """刪除人設"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result

    from app.models.scenario_persona import ScenarioPersona
    persona = db.query(ScenarioPersona).filter(ScenarioPersona.id == persona_id).first()
    if persona:
        version = persona.course_version
        db.delete(persona)
        db.commit()
        return RedirectResponse(url=f"/dashboard/personas?version={version}&success=已刪除人設", status_code=303)
    return RedirectResponse(url="/dashboard/personas?error=找不到人設", status_code=303)


@router.post("/dashboard/personas/{persona_id}/toggle")
async def persona_toggle(
    request: Request,
    persona_id: int,
    db: Session = Depends(get_db),
):
    """切換人設啟用狀態"""
    result = require_permission(request, db, "courses:edit")
    if isinstance(result, RedirectResponse):
        return result

    from app.models.scenario_persona import ScenarioPersona
    persona = db.query(ScenarioPersona).filter(ScenarioPersona.id == persona_id).first()
    if persona:
        persona.is_active = not persona.is_active
        db.commit()
        status = "啟用" if persona.is_active else "停用"
        return RedirectResponse(
            url=f"/dashboard/personas?version={persona.course_version}&success=已{status}「{persona.name}」",
            status_code=303,
        )
    return RedirectResponse(url="/dashboard/personas?error=找不到人設", status_code=303)
