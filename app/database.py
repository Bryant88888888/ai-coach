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
    from app.models import user, day, message, push_log, leave_request  # noqa: F401
    # checkfirst=True: 如果表已存在就跳過，避免多 worker 競爭問題
    Base.metadata.create_all(bind=engine, checkfirst=True)
    # 執行資料庫遷移（加入缺少的欄位）
    run_migrations()


def run_migrations():
    """執行資料庫遷移（加入缺少的欄位）"""
    from sqlalchemy import text, inspect

    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        # 檢查並加入 users.current_round 欄位
        if 'users' in table_names:
            columns = [col['name'] for col in inspector.get_columns('users')]

            if 'current_round' not in columns:
                try:
                    with engine.connect() as conn:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS current_round INTEGER DEFAULT 0"
                        ))
                        conn.commit()
                        print("Migration: Added 'current_round' column to users table")
                except Exception as e:
                    print(f"Migration note: {e}")

        # 檢查並加入 leave_requests 新欄位
        if 'leave_requests' in table_names:
            columns = [col['name'] for col in inspector.get_columns('leave_requests')]

            with engine.connect() as conn:
                if 'applicant_name' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS applicant_name VARCHAR(100)"
                        ))
                        print("Migration: Added 'applicant_name' column to leave_requests table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'line_display_name' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS line_display_name VARCHAR(100)"
                        ))
                        print("Migration: Added 'line_display_name' column to leave_requests table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'line_picture_url' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS line_picture_url VARCHAR(500)"
                        ))
                        print("Migration: Added 'line_picture_url' column to leave_requests table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

    except Exception as e:
        # 避免 migration 錯誤導致應用程式無法啟動
        print(f"Migration warning: {e}")
