from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import get_settings
from app.database import init_db
from app.routers import webhook_router, admin_router, frontend_router, cron_router
from app.routers.duty_mobile import router as duty_mobile_router, api_router as duty_api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時：初始化資料庫
    print("🚀 正在初始化資料庫...")
    init_db()
    print("✅ 資料庫初始化完成")

    yield

    # 關閉時的清理工作（如果需要）
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
    max_age=86400 * 7,  # 7 天
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
app.include_router(admin_router)
app.include_router(frontend_router)
app.include_router(cron_router)
app.include_router(duty_mobile_router)
app.include_router(duty_api_router)


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
