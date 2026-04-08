"""模擬練習路由

提供模擬練習的 API 端點和前端頁面。
包含：練習者自用頁面 + 主管管理檢視 + 資料匯出
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.services.simulation_service import SimulationService
from app.routers.frontend import get_current_admin, require_permission, build_template_context
from app.models.admin import AdminAccount

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/dashboard/simulation", tags=["模擬練習"])

simulation_service = SimulationService()


# ===== 練習者頁面 =====

@router.get("/", response_class=HTMLResponse)
async def simulation_page(request: Request, db: Session = Depends(get_db)):
    """模擬練習主頁（自己的歷史記錄）"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)

    data = simulation_service.list_sessions(db, admin_id=admin.id)
    context = build_template_context(request, admin, db, active_page="simulation",
                                     sessions=data["sessions"], total=data["total"])
    return templates.TemplateResponse("simulation.html", context)


@router.get("/practice", response_class=HTMLResponse)
async def simulation_practice_page(request: Request, db: Session = Depends(get_db)):
    """模擬練習對話介面"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)

    session_id = request.query_params.get("session_id")
    context = build_template_context(request, admin, db, active_page="simulation",
                                     session_id=session_id)
    return templates.TemplateResponse("simulation_practice.html", context)


@router.get("/review/{session_id}", response_class=HTMLResponse)
async def simulation_review_page(request: Request, session_id: int,
                                 db: Session = Depends(get_db)):
    """練習回顧頁面（自己的）"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=303)

    detail = simulation_service.get_session_detail(db, session_id, admin_id=admin.id)
    if not detail:
        return RedirectResponse(url="/dashboard/simulation?error=找不到此練習記錄", status_code=303)

    context = build_template_context(request, admin, db, active_page="simulation",
                                     detail=detail)
    return templates.TemplateResponse("simulation_review.html", context)


# ===== 主管管理頁面 =====

@router.get("/manage", response_class=HTMLResponse)
async def simulation_manage_page(request: Request, db: Session = Depends(get_db)):
    """主管檢視所有人的練習記錄"""
    result = require_permission(request, db, "simulation:manage")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    # 讀取篩選參數
    filter_admin_id = request.query_params.get("admin_id", "")
    filter_grade = request.query_params.get("grade", "")
    filter_difficulty = request.query_params.get("difficulty", "")

    data = simulation_service.list_all_sessions(
        db,
        filter_admin_id=int(filter_admin_id) if filter_admin_id else None,
        filter_grade=filter_grade or None,
        filter_difficulty=filter_difficulty or None,
    )

    # 取得所有管理員（篩選下拉用）
    all_admins = db.query(AdminAccount).filter(AdminAccount.is_active == True).all()

    context = build_template_context(
        request, admin, db, active_page="simulation_manage",
        sessions=data["sessions"], total=data["total"],
        all_admins=all_admins,
        filter_admin_id=filter_admin_id,
        filter_grade=filter_grade,
        filter_difficulty=filter_difficulty,
    )
    return templates.TemplateResponse("simulation_manage.html", context)


@router.get("/manage/review/{session_id}", response_class=HTMLResponse)
async def simulation_manage_review_page(request: Request, session_id: int,
                                        db: Session = Depends(get_db)):
    """主管檢視特定練習的對話記錄（可看所有人的）"""
    result = require_permission(request, db, "simulation:manage")
    if isinstance(result, RedirectResponse):
        return result
    admin = result

    detail = simulation_service.get_session_detail(db, session_id, is_manager=True)
    if not detail:
        return RedirectResponse(url="/dashboard/simulation/manage?error=找不到此練習記錄", status_code=303)

    context = build_template_context(request, admin, db, active_page="simulation_manage",
                                     detail=detail, is_manager_view=True)
    return templates.TemplateResponse("simulation_review.html", context)


# ===== API 端點 =====

@router.post("/api/start")
async def api_start_session(request: Request, db: Session = Depends(get_db)):
    """開始新的模擬練習"""
    admin = get_current_admin(request, db)
    if not admin:
        return JSONResponse({"error": "未登入"}, status_code=401)

    body = await request.json()
    difficulty = body.get("difficulty", "random")

    try:
        result = simulation_service.start_session(
            db, difficulty=difficulty, admin_id=admin.id
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"生成失敗：{str(e)}"}, status_code=500)


@router.post("/api/message")
async def api_send_message(request: Request, db: Session = Depends(get_db)):
    """發送訊息給模擬諮詢者"""
    admin = get_current_admin(request, db)
    if not admin:
        return JSONResponse({"error": "未登入"}, status_code=401)

    body = await request.json()
    session_id = body.get("session_id")
    message = body.get("message", "").strip()

    if not session_id or not message:
        return JSONResponse({"error": "缺少 session_id 或 message"}, status_code=400)

    try:
        result = simulation_service.send_message(db, session_id, message, admin_id=admin.id)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"回覆失敗：{str(e)}"}, status_code=500)


@router.post("/api/end")
async def api_end_session(request: Request, db: Session = Depends(get_db)):
    """結束練習並取得評分"""
    admin = get_current_admin(request, db)
    if not admin:
        return JSONResponse({"error": "未登入"}, status_code=401)

    body = await request.json()
    session_id = body.get("session_id")

    if not session_id:
        return JSONResponse({"error": "缺少 session_id"}, status_code=400)

    try:
        result = simulation_service.end_session(db, session_id, admin_id=admin.id)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"評分失敗：{str(e)}"}, status_code=500)


@router.get("/api/detail/{session_id}")
async def api_session_detail(session_id: int, request: Request,
                             db: Session = Depends(get_db)):
    """取得 Session 完整資料"""
    admin = get_current_admin(request, db)
    if not admin:
        return JSONResponse({"error": "未登入"}, status_code=401)

    detail = simulation_service.get_session_detail(db, session_id, admin_id=admin.id)
    if not detail:
        return JSONResponse({"error": "找不到此練習記錄"}, status_code=404)

    return JSONResponse(detail)


@router.get("/api/export/{session_id}")
async def api_export_session(session_id: int, request: Request,
                             db: Session = Depends(get_db)):
    """匯出完整 Session 資料（JSON 格式，含所有原始資料）"""
    result = require_permission(request, db, "simulation:manage")
    if isinstance(result, RedirectResponse):
        return JSONResponse({"error": "無權限"}, status_code=403)

    export_data = simulation_service.export_session(db, session_id)
    if not export_data:
        return JSONResponse({"error": "找不到此練習記錄"}, status_code=404)

    return JSONResponse(
        export_data,
        headers={
            "Content-Disposition": f"attachment; filename=simulation_{session_id}.json"
        }
    )
