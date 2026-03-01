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
    from app.models import user, day, message, push_log, leave_request, manager  # noqa: F401
    from app.models import training_batch, user_training, course  # noqa: F401
    from app.models import duty_config, duty_schedule, duty_report, duty_complaint, duty_rule  # noqa: F401

    # 使用 try-except 處理多 worker 同時啟動時的競爭條件
    try:
        # checkfirst=True: 如果表已存在就跳過
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        # 忽略 "table already exists" 或 "duplicate key" 錯誤
        error_msg = str(e).lower()
        if "already exists" in error_msg or "duplicate" in error_msg:
            print(f"資料庫表已存在，跳過建立: {e}")
        else:
            raise e

    # 執行資料庫遷移（加入缺少的欄位）
    run_migrations()


def run_migrations():
    """執行資料庫遷移（加入缺少的欄位）"""
    from sqlalchemy import text, inspect

    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        # 檢查並加入 users 新欄位
        if 'users' in table_names:
            columns = [col['name'] for col in inspector.get_columns('users')]

            with engine.connect() as conn:
                if 'current_round' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS current_round INTEGER DEFAULT 0"
                        ))
                        print("Migration: Added 'current_round' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'line_display_name' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS line_display_name VARCHAR(100)"
                        ))
                        print("Migration: Added 'line_display_name' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'line_picture_url' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS line_picture_url VARCHAR(500)"
                        ))
                        print("Migration: Added 'line_picture_url' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'real_name' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS real_name VARCHAR(100)"
                        ))
                        print("Migration: Added 'real_name' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                # 統一用戶系統新欄位
                if 'roles' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS roles TEXT DEFAULT '[\"trainee\"]'"
                        ))
                        print("Migration: Added 'roles' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'phone' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)"
                        ))
                        print("Migration: Added 'phone' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'nickname' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS nickname VARCHAR(100)"
                        ))
                        print("Migration: Added 'nickname' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'registered_at' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP WITH TIME ZONE"
                        ))
                        print("Migration: Added 'registered_at' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'manager_notification_enabled' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS manager_notification_enabled BOOLEAN DEFAULT TRUE"
                        ))
                        print("Migration: Added 'manager_notification_enabled' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'position' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(50)"
                        ))
                        print("Migration: Added 'position' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

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

                if 'proof_deadline' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS proof_deadline TIMESTAMP WITH TIME ZONE"
                        ))
                        print("Migration: Added 'proof_deadline' column to leave_requests table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

        # 檢查並加入 user_trainings 新欄位
        if 'user_trainings' in table_names:
            columns = [col['name'] for col in inspector.get_columns('user_trainings')]

            with engine.connect() as conn:
                if 'attempt_started_at' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE user_trainings ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMP WITH TIME ZONE"
                        ))
                        print("Migration: Added 'attempt_started_at' column to user_trainings table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                if 'testing_day' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE user_trainings ADD COLUMN IF NOT EXISTS testing_day INTEGER"
                        ))
                        print("Migration: Added 'testing_day' column to user_trainings table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

        # 檢查並加入 courses 新欄位
        if 'courses' in table_names:
            columns = [col['name'] for col in inspector.get_columns('courses')]

            with engine.connect() as conn:
                if 'lesson_content' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS lesson_content TEXT"
                        ))
                        print("Migration: Added 'lesson_content' column to courses table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

    except Exception as e:
        # 避免 migration 錯誤導致應用程式無法啟動
        print(f"Migration warning: {e}")
