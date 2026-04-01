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
    from app.models import duty_config, duty_schedule, duty_report, duty_complaint, duty_rule, duty_swap  # noqa: F401
    from app.models import info_form  # noqa: F401
    from app.models import morning_report  # noqa: F401
    from app.models import admin  # noqa: F401

    # 使用 try-except 處理多 worker 同時啟動時的競爭條件
    try:
        # checkfirst=True: 如果表已存在就跳過
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception as e:
        # 忽略 "table already exists" 或 "duplicate key" 錯誤
        error_msg = str(e).lower()
        if "already exists" in error_msg or "duplicate" in error_msg:
            print(f"資料庫表已存在，跳過建立: {e}")
            # 嘗試單獨建立新表（避免舊表錯誤阻擋新表建立）
            try:
                from app.models.admin import AdminRole, AdminAccount
                Base.metadata.create_all(
                    bind=engine, checkfirst=True,
                    tables=[AdminRole.__table__, AdminAccount.__table__]
                )
            except Exception:
                pass
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

        # 角色遷移：主管→組長、刪除訓練管理員、新增超級管理員角色、修正員工權限
        if 'admin_roles' in table_names:
            with engine.connect() as conn:
                try:
                    # 主管 → 組長（僅早會日報權限）
                    conn.execute(text(
                        "UPDATE admin_roles SET name = '組長', description = '填寫早會日報、搜尋查看日報彙整', permissions = '[\"morning:view\", \"morning:edit\"]' WHERE name = '主管'"
                    ))
                    # 已改名的組長也更新權限
                    conn.execute(text(
                        "UPDATE admin_roles SET description = '填寫早會日報、搜尋查看日報彙整', permissions = '[\"morning:view\", \"morning:edit\"]' WHERE name = '組長'"
                    ))
                    # 刪除訓練管理員（如果沒有帳號在用）
                    conn.execute(text(
                        """DELETE FROM admin_roles WHERE name = '訓練管理員'
                           AND id NOT IN (SELECT DISTINCT role_id FROM admin_accounts WHERE role_id IS NOT NULL)"""
                    ))
                    # 員工權限修正
                    conn.execute(text(
                        "UPDATE admin_roles SET permissions = '[\"morning:edit\"]' WHERE name = '員工'"
                    ))
                    conn.commit()
                except Exception as e:
                    print(f"Migration note: {e}")

        # 檢查並更新 morning_reports 表（JSON 多筆格式）
        if 'morning_reports' in table_names:
            columns = [col['name'] for col in inspector.get_columns('morning_reports')]

            with engine.connect() as conn:
                # 新增 reviews/shares JSON 欄位
                if 'reviews' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE morning_reports ADD COLUMN IF NOT EXISTS reviews TEXT"))
                        print("Migration: Added 'reviews' column to morning_reports table")
                    except Exception as e:
                        print(f"Migration note: {e}")
                if 'shares' not in columns:
                    try:
                        conn.execute(text("ALTER TABLE morning_reports ADD COLUMN IF NOT EXISTS shares TEXT"))
                        print("Migration: Added 'shares' column to morning_reports table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                # 移除舊的單筆欄位（如果存在）
                for old_col in ['meeting_time', 'review_category', 'review_description', 'review_impact',
                                'review_solution', 'review_responsible', 'review_deadline', 'review_status',
                                'share_category', 'share_situation', 'share_solution', 'share_lesson',
                                'share_scenario', 'share_rating', 'share_note']:
                    if old_col in columns:
                        try:
                            conn.execute(text(f"ALTER TABLE morning_reports DROP COLUMN IF EXISTS {old_col}"))
                            print(f"Migration: Dropped old column '{old_col}' from morning_reports")
                        except Exception as e:
                            print(f"Migration note: {e}")

                conn.commit()

        # 檢查並加入 users 新欄位（所屬組長）
        if 'users' in table_names:
            columns = [col['name'] for col in inspector.get_columns('users')]

            if 'leader_id' not in columns:
                with engine.connect() as conn:
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS leader_id INTEGER REFERENCES users(id)"
                        ))
                        print("Migration: Added 'leader_id' column to users table")
                    except Exception as e:
                        print(f"Migration note: {e}")
                    conn.commit()

        # 檢查並加入 admin_accounts 新欄位（LINE 登入）
        if 'admin_accounts' in table_names:
            columns = [col['name'] for col in inspector.get_columns('admin_accounts')]

            with engine.connect() as conn:
                if 'line_user_id' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS line_user_id VARCHAR(100) UNIQUE"
                        ))
                        print("Migration: Added 'line_user_id' column to admin_accounts table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

        # 檢查並加入 duty_rules 新欄位（多店家支援）
        if 'duty_rules' in table_names:
            columns = [col['name'] for col in inspector.get_columns('duty_rules')]

            with engine.connect() as conn:
                if 'config_id' not in columns:
                    try:
                        conn.execute(text(
                            "ALTER TABLE duty_rules ADD COLUMN IF NOT EXISTS config_id INTEGER REFERENCES duty_configs(id)"
                        ))
                        print("Migration: Added 'config_id' column to duty_rules table")
                    except Exception as e:
                        print(f"Migration note: {e}")

                conn.commit()

        # 確保 duty_swaps 資料表存在（換班申請功能）
        if 'duty_swaps' not in table_names:
            with engine.connect() as conn:
                try:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS duty_swaps (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            requester_id INTEGER NOT NULL REFERENCES users(id),
                            target_user_id INTEGER NOT NULL REFERENCES users(id),
                            schedule_id INTEGER NOT NULL REFERENCES duty_schedules(id),
                            target_schedule_id INTEGER REFERENCES duty_schedules(id),
                            reason TEXT,
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            responded_at DATETIME,
                            response_note TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    conn.commit()
                    print("Migration: Created 'duty_swaps' table")
                except Exception as e:
                    print(f"Migration note: {e}")

    except Exception as e:
        # 避免 migration 錯誤導致應用程式無法啟動
        print(f"Migration warning: {e}")

    # 種子資料：建立預設角色與超級管理員
    try:
        seed_db = SessionLocal()
        try:
            from app.services.permission_service import PermissionService
            perm_service = PermissionService(seed_db)
            perm_service.seed_default_roles()
            perm_service.seed_super_admin_from_env()
        finally:
            seed_db.close()
    except Exception as e:
        print(f"Seed warning: {e}")
