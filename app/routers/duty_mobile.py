"""
手機版值日專區路由

提供給 LINE LIFF 使用的手機版頁面和 API
"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional
import uuid
import os

from app.database import get_db
from app.config import get_settings
from app.services.user_service import UserService
from app.services.duty_service import DutyService
from app.models.duty_schedule import DutySchedule, DutyScheduleStatus
from app.models.duty_rule import DutyRule
from app.models.user import User

# 設定模板目錄
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/duty/my", tags=["手機版值日專區"])


def get_user_by_line_id(line_user_id: str, db: Session):
    """透過 LINE User ID 取得用戶"""
    user_service = UserService(db)
    return user_service.get_user_by_line_id(line_user_id)


# ===== 頁面路由 =====

def get_duty_liff_id():
    """取得值日專區的 LIFF ID（優先用專用的，否則用通用的）"""
    settings = get_settings()
    return settings.liff_id_duty or settings.liff_id


@router.get("", response_class=HTMLResponse)
async def duty_mobile_home(request: Request, db: Session = Depends(get_db)):
    """值日專區首頁"""
    return templates.TemplateResponse("duty_mobile.html", {
        "request": request,
        "liff_id": get_duty_liff_id()
    })


@router.get("/schedule", response_class=HTMLResponse)
async def duty_mobile_schedule(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = None
):
    """我的排班頁面"""
    return templates.TemplateResponse("duty_mobile_schedule.html", {
        "request": request,
        "liff_id": get_duty_liff_id()
    })


@router.get("/report", response_class=HTMLResponse)
async def duty_mobile_report(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = None,
    schedule_id: int = None
):
    """值日回報頁面"""
    return templates.TemplateResponse("duty_mobile_report.html", {
        "request": request,
        "liff_id": get_duty_liff_id(),
        "schedule_id": schedule_id
    })


@router.get("/swap", response_class=HTMLResponse)
async def duty_mobile_swap(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = None
):
    """換班申請頁面"""
    return templates.TemplateResponse("duty_mobile_swap.html", {
        "request": request,
        "liff_id": get_duty_liff_id()
    })


@router.get("/swap/respond", response_class=HTMLResponse)
async def duty_mobile_swap_respond(
    request: Request,
    swap_id: int = None,
    db: Session = Depends(get_db)
):
    """換班回應頁面（對方審核用）"""
    return templates.TemplateResponse("duty_mobile_swap_respond.html", {
        "request": request,
        "liff_id": get_duty_liff_id(),
        "swap_id": swap_id
    })


@router.get("/complaint", response_class=HTMLResponse)
async def duty_mobile_complaint(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = None
):
    """檢舉回報頁面"""
    return templates.TemplateResponse("duty_mobile_complaint.html", {
        "request": request,
        "liff_id": get_duty_liff_id()
    })


@router.get("/history", response_class=HTMLResponse)
async def duty_mobile_history(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = None
):
    """我的記錄頁面"""
    return templates.TemplateResponse("duty_mobile_history.html", {
        "request": request,
        "liff_id": get_duty_liff_id()
    })


# ===== API 路由 =====

@router.get("/api/data")
async def get_my_duty_data(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """
    取得用戶的值日相關資料

    Returns:
        - is_my_duty_today: 今天是否輪到我
        - today_duty: 今日值日生列表
        - my_upcoming: 我未來的排班
    """
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(
            status_code=404,
            content={"error": "用戶不存在"}
        )

    duty_service = DutyService(db)
    today = date.today()

    # 今日值日生
    today_schedules = duty_service.get_schedule_by_date(today)
    today_duty = []
    is_my_duty_today = False

    for schedule in today_schedules:
        if schedule.user_id == user.id:
            is_my_duty_today = True
        today_duty.append({
            "user_id": schedule.user_id,
            "display_name": schedule.user.display_name,
            "picture_url": schedule.user.line_picture_url,
            "status": schedule.status,
            "status_display": schedule.status_display
        })

    # 我未來的排班（包含今天，最多顯示 5 筆）
    my_schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == user.id,
        DutySchedule.duty_date >= today
    ).order_by(DutySchedule.duty_date).limit(5).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    my_upcoming = []
    for schedule in my_schedules:
        weekday_idx = schedule.duty_date.weekday()
        my_upcoming.append({
            "id": schedule.id,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "status": schedule.status,
            "status_display": schedule.status_display
        })

    return {
        "is_my_duty_today": is_my_duty_today,
        "today_duty": today_duty,
        "my_upcoming": my_upcoming
    }


@router.get("/api/schedule")
async def get_my_schedule(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得我的所有排班（未來 + 過去 30 天）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    today = date.today()
    past_30_days = today - timedelta(days=30)

    schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == user.id,
        DutySchedule.duty_date >= past_30_days
    ).order_by(DutySchedule.duty_date.desc()).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    result = []
    for schedule in schedules:
        weekday_idx = schedule.duty_date.weekday()
        is_past = schedule.duty_date < today
        result.append({
            "id": schedule.id,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "status": schedule.status,
            "status_display": schedule.status_display,
            "is_past": is_past,
            "is_today": schedule.duty_date == today
        })

    return {"schedules": result}


@router.get("/api/reportable")
async def get_reportable_schedules(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得可回報的排班（今日或近期未回報的）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    today = date.today()
    yesterday = today - timedelta(days=1)

    # 取得今天和昨天狀態為 scheduled 的排班
    schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == user.id,
        DutySchedule.duty_date >= yesterday,
        DutySchedule.duty_date <= today,
        DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
    ).order_by(DutySchedule.duty_date.desc()).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    result = []
    for schedule in schedules:
        weekday_idx = schedule.duty_date.weekday()
        result.append({
            "id": schedule.id,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "is_today": schedule.duty_date == today
        })

    return {"schedules": result}


@router.post("/api/report")
async def submit_duty_report(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    schedule_id: int = Form(...),
    report_text: str = Form(None),
    photo: UploadFile = File(None)
):
    """提交值日回報"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)

    # 驗證排班
    schedule = db.query(DutySchedule).filter(
        DutySchedule.id == schedule_id,
        DutySchedule.user_id == user.id
    ).first()

    if not schedule:
        return JSONResponse(status_code=404, content={"error": "找不到該排班或非您的排班"})

    # 處理照片上傳
    photo_urls = []
    if photo and photo.filename:
        settings = get_settings()
        upload_dir = Path("app/static/uploads/duty")
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 生成檔名
        ext = Path(photo.filename).suffix
        filename = f"duty_{schedule_id}_{uuid.uuid4().hex[:8]}{ext}"
        file_path = upload_dir / filename

        # 儲存檔案
        with open(file_path, "wb") as f:
            content = await photo.read()
            f.write(content)

        photo_urls.append(f"duty/{filename}")

    # 提交回報
    try:
        report = duty_service.submit_report(
            schedule_id=schedule_id,
            user_id=user.id,
            report_text=report_text,
            photo_urls=photo_urls if photo_urls else None
        )
        return {"success": True, "message": "回報成功", "report_id": report.id}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/api/swap-options")
async def get_swap_options(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得換班選項（我的待換排班 + 可換的對象）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)
    today = date.today()

    # 我的排班（今日+未來，可申請換班）
    now = datetime.now()
    my_schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == user.id,
        DutySchedule.duty_date >= today,
        DutySchedule.status == DutyScheduleStatus.SCHEDULED.value
    ).order_by(DutySchedule.duty_date).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    my_swappable = []
    for schedule in my_schedules:
        # 當日換班需在下午 5 點前
        if schedule.duty_date == today and now.hour >= 17:
            continue
        weekday_idx = schedule.duty_date.weekday()
        is_today = schedule.duty_date == today
        my_swappable.append({
            "id": schedule.id,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "config_id": schedule.config_id,
            "is_today": is_today,
            "deadline_note": "今日 17:00 前可換" if is_today else "",
        })

    # 取得同 config 的排班人員作為可換對象（不只是所有值日生）
    config_ids = list(set(s.config_id for s in my_schedules))
    rule_user_ids = set()
    if config_ids:
        rules = db.query(DutyRule).filter(
            DutyRule.rule_type == 'duty',
            DutyRule.config_id.in_(config_ids)
        ).all()
        rule_user_ids = set(r.user_id for r in rules)

    # 同時也包含所有值日生角色的人（確保兼容性）
    duty_members = duty_service.get_duty_members()
    all_candidate_ids = rule_user_ids | set(m.id for m in duty_members)

    other_members = []
    added_ids = set()
    for m in duty_members:
        if m.id != user.id and m.id in all_candidate_ids:
            other_members.append({
                "id": m.id,
                "display_name": m.nickname or m.real_name or m.display_name,
                "real_name": m.real_name or "",
                "nickname": m.nickname or "",
                "picture_url": m.line_picture_url
            })
            added_ids.add(m.id)
    # 也加入規則中有但不在 duty_members 的人
    for uid in rule_user_ids:
        if uid != user.id and uid not in added_ids:
            u = db.query(User).filter(User.id == uid).first()
            if u:
                other_members.append({
                    "id": u.id,
                    "display_name": u.nickname or u.real_name or u.display_name,
                    "real_name": u.real_name or "",
                    "nickname": u.nickname or "",
                    "picture_url": u.line_picture_url
                })

    return {
        "my_schedules": my_swappable,
        "other_members": other_members
    }


@router.post("/api/swap-request")
async def submit_swap_request(
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    schedule_id: int = Form(...),
    target_user_id: int = Form(...),
    reason: str = Form(None)
):
    """提交換班申請（建立申請，等待對方審核）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    # 檢查當日換班時間限制（下午 5 點前）
    schedule = db.query(DutySchedule).filter(DutySchedule.id == schedule_id).first()
    if schedule and schedule.duty_date == date.today() and datetime.now().hour >= 17:
        return JSONResponse(status_code=400, content={"error": "當日換班需在下午 5 點前申請"})

    duty_service = DutyService(db)
    result = duty_service.create_swap_request(
        requester_id=user.id,
        schedule_id=schedule_id,
        target_user_id=target_user_id,
        reason=reason
    )

    if not result["success"]:
        return JSONResponse(status_code=400, content={"error": result["error"]})

    return {
        "success": True,
        "message": "換班申請已送出，等待對方確認",
        "conflict": result.get("conflict", False),
        "swap_id": result["swap"].id
    }


@router.get("/api/swap-pending")
async def get_swap_pending(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得待我回應的換班申請"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)
    pending_swaps = duty_service.get_pending_swaps_for_user(user.id)

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    result = []
    for swap in pending_swaps:
        schedule = swap.schedule
        requester = swap.requester
        if not schedule or not requester:
            continue
        conflict = duty_service.check_swap_conflict(user.id, schedule.duty_date, schedule.config_id)
        result.append({
            "id": swap.id,
            "requester_name": (requester.real_name or requester.display_name or "未知"),
            "requester_picture": requester.line_picture_url,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[schedule.duty_date.weekday()]}",
            "reason": swap.reason,
            "conflict": conflict,
            "created_at": swap.created_at.strftime("%m/%d %H:%M") if swap.created_at else ""
        })

    return {"pending_swaps": result}


@router.post("/api/swap-respond")
async def respond_swap_request(
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    swap_id: int = Form(...),
    approved: str = Form(...),
    note: str = Form(None)
):
    """回應換班申請（同意/拒絕）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)
    is_approved = approved.lower() in ("true", "1", "yes")

    result = duty_service.respond_swap(
        swap_id=swap_id,
        responder_id=user.id,
        approved=is_approved,
        note=note
    )

    if not result["success"]:
        return JSONResponse(status_code=400, content={"error": result["error"]})

    status_text = "已同意" if is_approved else "已拒絕"
    return {"success": True, "message": f"換班申請{status_text}"}


@router.post("/api/swap-cancel")
async def cancel_swap_request(
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    swap_id: int = Form(...)
):
    """取消我的換班申請"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)
    result = duty_service.cancel_swap(swap_id=swap_id, requester_id=user.id)

    if not result["success"]:
        return JSONResponse(status_code=400, content={"error": result["error"]})

    return {"success": True, "message": "換班申請已取消"}


@router.get("/api/swap-history")
async def get_swap_history(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得我的換班紀錄"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)

    # 我發起的申請
    my_requests = duty_service.get_my_swap_requests(user.id)
    # 別人對我的申請
    pending = duty_service.get_pending_swaps_for_user(user.id)

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']

    def swap_to_dict(swap, role):
        schedule = swap.schedule
        other = swap.target_user if role == "requester" else swap.requester
        return {
            "id": swap.id,
            "role": role,
            "other_name": (other.real_name or other.display_name or "未知") if other else "未知",
            "other_picture": other.line_picture_url if other else None,
            "duty_date": schedule.duty_date.isoformat() if schedule else "",
            "weekday": (f"星期{weekday_names[schedule.duty_date.weekday()]}") if schedule else "",
            "reason": swap.reason,
            "status": swap.status,
            "status_display": swap.status_display,
            "response_note": swap.response_note,
            "created_at": swap.created_at.strftime("%m/%d %H:%M") if swap.created_at else "",
            "responded_at": swap.responded_at.strftime("%m/%d %H:%M") if swap.responded_at else ""
        }

    result = []
    for swap in my_requests:
        result.append(swap_to_dict(swap, "requester"))
    for swap in pending:
        result.append(swap_to_dict(swap, "target"))

    # 按建立時間排序
    result.sort(key=lambda x: x["created_at"], reverse=True)

    return {"swap_history": result}


@router.get("/api/swap-detail")
async def get_swap_detail(
    swap_id: int,
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得單一換班申請詳情（回應頁面用）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)
    swap = duty_service.get_swap_by_id(swap_id)
    if not swap:
        return JSONResponse(status_code=404, content={"error": "找不到該換班申請"})

    # 驗證用戶是相關方
    if swap.requester_id != user.id and swap.target_user_id != user.id:
        return JSONResponse(status_code=403, content={"error": "無權查看此申請"})

    schedule = swap.schedule
    requester = swap.requester
    target = swap.target_user
    weekday_names = ['一', '二', '三', '四', '五', '六', '日']

    conflict = False
    if swap.target_user_id == user.id and schedule:
        conflict = duty_service.check_swap_conflict(user.id, schedule.duty_date, schedule.config_id)

    return {
        "id": swap.id,
        "requester_name": (requester.real_name or requester.display_name or "未知") if requester else "未知",
        "requester_picture": requester.line_picture_url if requester else None,
        "target_name": (target.real_name or target.display_name or "未知") if target else "未知",
        "target_picture": target.line_picture_url if target else None,
        "duty_date": schedule.duty_date.isoformat() if schedule else "",
        "weekday": (f"星期{weekday_names[schedule.duty_date.weekday()]}") if schedule else "",
        "reason": swap.reason,
        "status": swap.status,
        "status_display": swap.status_display,
        "response_note": swap.response_note,
        "conflict": conflict,
        "is_requester": swap.requester_id == user.id,
        "is_target": swap.target_user_id == user.id,
        "created_at": swap.created_at.strftime("%Y/%m/%d %H:%M") if swap.created_at else "",
        "responded_at": swap.responded_at.strftime("%Y/%m/%d %H:%M") if swap.responded_at else ""
    }


@router.get("/api/complaint-targets")
async def get_complaint_targets(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得可檢舉的對象（近 7 天有排班但未完成的人）"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    today = date.today()
    past_7_days = today - timedelta(days=7)

    # 取得近 7 天狀態為 missed 或 scheduled（過期）的排班
    schedules = db.query(DutySchedule).filter(
        DutySchedule.duty_date >= past_7_days,
        DutySchedule.duty_date < today,
        DutySchedule.user_id != user.id,
        DutySchedule.status.in_([
            DutyScheduleStatus.MISSED.value,
            DutyScheduleStatus.SCHEDULED.value
        ])
    ).order_by(DutySchedule.duty_date.desc()).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']
    targets = []
    for schedule in schedules:
        weekday_idx = schedule.duty_date.weekday()
        targets.append({
            "schedule_id": schedule.id,
            "user_id": schedule.user_id,
            "display_name": schedule.user.display_name,
            "picture_url": schedule.user.line_picture_url,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "status": schedule.status,
            "status_display": schedule.status_display
        })

    return {"targets": targets}


@router.post("/api/complaint")
async def submit_complaint(
    request: Request,
    db: Session = Depends(get_db),
    line_user_id: str = Form(...),
    schedule_id: int = Form(...),
    complaint_text: str = Form(...),
    photo: UploadFile = File(None)
):
    """提交檢舉"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    duty_service = DutyService(db)

    # 取得被檢舉的排班
    schedule = db.query(DutySchedule).filter(DutySchedule.id == schedule_id).first()
    if not schedule:
        return JSONResponse(status_code=404, content={"error": "找不到該排班"})

    # 處理照片上傳
    photo_urls = []
    if photo and photo.filename:
        upload_dir = Path("app/static/uploads/complaints")
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(photo.filename).suffix
        filename = f"complaint_{schedule_id}_{uuid.uuid4().hex[:8]}{ext}"
        file_path = upload_dir / filename

        with open(file_path, "wb") as f:
            content = await photo.read()
            f.write(content)

        photo_urls.append(f"complaints/{filename}")

    # 提交檢舉
    try:
        complaint = duty_service.submit_complaint(
            schedule_id=schedule_id,
            reporter_id=user.id,
            reported_user_id=schedule.user_id,
            complaint_text=complaint_text,
            photo_urls=photo_urls if photo_urls else None
        )
        return {"success": True, "message": "檢舉已提交", "complaint_id": complaint.id}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/api/history")
async def get_my_history(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得我的值日歷史記錄"""
    user = get_user_by_line_id(line_user_id, db)
    if not user:
        return JSONResponse(status_code=404, content={"error": "用戶不存在"})

    today = date.today()

    # 取得過去 90 天的排班
    past_90_days = today - timedelta(days=90)
    schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == user.id,
        DutySchedule.duty_date >= past_90_days,
        DutySchedule.duty_date < today
    ).order_by(DutySchedule.duty_date.desc()).all()

    weekday_names = ['一', '二', '三', '四', '五', '六', '日']

    # 統計
    total = len(schedules)
    completed = len([s for s in schedules if s.status in ['reported', 'approved']])
    missed = len([s for s in schedules if s.status == 'missed'])

    history = []
    for schedule in schedules:
        weekday_idx = schedule.duty_date.weekday()
        history.append({
            "id": schedule.id,
            "duty_date": schedule.duty_date.isoformat(),
            "weekday": f"星期{weekday_names[weekday_idx]}",
            "status": schedule.status,
            "status_display": schedule.status_display
        })

    return {
        "stats": {
            "total": total,
            "completed": completed,
            "missed": missed,
            "completion_rate": round(completed / total * 100, 1) if total > 0 else 0
        },
        "history": history
    }


# ===== 額外的 API 路由（放在 /api/duty 下）=====
# 這個會在 main.py 中另外註冊

api_router = APIRouter(prefix="/api/duty", tags=["值日 API"])

@api_router.get("/my-data")
async def api_get_my_duty_data(
    line_user_id: str,
    db: Session = Depends(get_db)
):
    """取得用戶的值日相關資料（給首頁用）"""
    return await get_my_duty_data(line_user_id, db)
