from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

# 建立資料庫引擎（根據資料庫類型設定不同參數）
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}  # SQLite 需要這個設定

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True  # 自動檢查連線是否有效
)

# 建立 Session 工廠
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 建立 Base 類別
Base = declarative_base()


def get_db():
    """取得資料庫 Session（依賴注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化資料庫（建立所有表）"""
    from app.models import user, day, message, push_log  # noqa: F401
    # checkfirst=True: 如果表已存在就跳過，避免多 worker 競爭問題
    Base.metadata.create_all(bind=engine, checkfirst=True)
