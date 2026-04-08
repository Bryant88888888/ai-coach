from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
from app.config import get_settings
from app.database import init_db
from app.routers import webhook_router, admin_router, frontend_router, cron_router
from app.routers.duty_mobile import router as duty_mobile_router, api_router as duty_api_router
from app.routers.simulation import router as simulation_router


async def scheduler_loop():
    """內建排程器：台灣時間 17:00（UTC 09:00）觸發每日任務"""
    from datetime import datetime, timezone, timedelta
    TW = timezone(timedelta(hours=8))

    triggered_today = False
    while True:
        now = datetime.now(TW)
        is_target_time = now.hour == 17 and now.minute == 0
        is_workday = now.weekday() < 6  # 週一到六

        if is_target_time and is_workday and not triggered_today:
            triggered_today = True
            print(f"⏰ 排程觸發：台灣時間 {now.strftime('%Y-%m-%d %H:%M')}")
            try:
                from app.routers.cron import run_duty_announcement_background
                run_duty_announcement_background()
            except Exception as e:
                print(f"❌ 排程執行失敗: {e}")

        # 日期變了就重置
        if now.hour == 0 and now.minute == 0:
            triggered_today = False

        await asyncio.sleep(30)  # 每 30 秒檢查一次


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時：初始化資料庫
    print("🚀 正在初始化資料庫...")
    init_db()
    print("✅ 資料庫初始化完成")

    # 啟動內建排程器
    task = asyncio.create_task(scheduler_loop())
    print("⏰ 內建排程器已啟動（台灣 17:00 值日公告）")

    yield

    # 關閉時取消排程
    task.cancel()
    print("👋 應用程式關閉中...")


# 取得設定
settings = get_settings()

# 建立 FastAPI 應用程式
app = FastAPI(
    title="寶格教育訓練",
    description="透過 LINE Chatbot 進行新人訓練、話術演練、安全教育的 AI 系統",
    version="1.0.0",
    lifespan=lifespan,
)

# 掛載靜態檔案
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 設定 Session（認證用）
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    max_age=28800,  # 8 小時後過期，需重新登入
)

# 設定 CORS（跨域請求）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生產環境應該限制來源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(webhook_router)
# admin_router 已被 frontend_router 的 /dashboard/* 路由取代，不再掛載（舊 API 無認證保護）
app.include_router(frontend_router)
app.include_router(cron_router)
app.include_router(duty_mobile_router)
app.include_router(duty_api_router)
app.include_router(simulation_router)


@app.get("/")
async def root(request: Request):
    """根路徑 - 重導向到儀表板或登入頁"""
    if request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


@app.get("/health")
async def health():
    """健康檢查端點"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
