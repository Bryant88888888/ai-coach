"""
主管資料遷移腳本

將 managers 表的資料遷移到 users 表的角色系統：
- 若 line_user_id 已存在於 users：為該用戶添加 manager 角色
- 若不存在：創建新 user 記錄並設定 manager 角色

執行方式：
    python -m app.scripts.migrate_managers
"""

import sys
import os

# 確保專案根目錄在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import SessionLocal, engine
from app.models.user import User, UserRole
from app.models.manager import Manager
from sqlalchemy import inspect
import json


def migrate_managers():
    """執行主管資料遷移"""
    db = SessionLocal()

    try:
        # 檢查 managers 表是否存在
        inspector = inspect(engine)
        if 'managers' not in inspector.get_table_names():
            print("✅ managers 表不存在，無需遷移")
            return

        # 取得所有主管
        managers = db.query(Manager).all()
        if not managers:
            print("✅ managers 表為空，無需遷移")
            return

        print(f"📋 找到 {len(managers)} 位主管需要遷移")

        migrated_count = 0
        created_count = 0
        skipped_count = 0

        for manager in managers:
            # 檢查 users 表是否已有此 LINE ID
            existing_user = db.query(User).filter(
                User.line_user_id == manager.line_user_id
            ).first()

            if existing_user:
                # 用戶已存在，添加 manager 角色
                if not existing_user.has_role(UserRole.MANAGER.value):
                    existing_user.add_role(UserRole.MANAGER.value)
                    existing_user.manager_notification_enabled = manager.is_active

                    # 如果用戶沒有名字，使用主管名字
                    if not existing_user.real_name and manager.name:
                        existing_user.real_name = manager.name

                    db.commit()
                    print(f"  ✅ 已將主管角色添加到現有用戶: {manager.name} ({manager.line_user_id[:10]}...)")
                    migrated_count += 1
                else:
                    print(f"  ⏭️ 用戶已有主管角色: {manager.name} ({manager.line_user_id[:10]}...)")
                    skipped_count += 1
            else:
                # 用戶不存在，創建新用戶
                new_user = User(
                    line_user_id=manager.line_user_id,
                    real_name=manager.name,
                    roles=json.dumps([UserRole.TRAINEE.value, UserRole.MANAGER.value]),
                    manager_notification_enabled=manager.is_active,
                    registered_at=manager.created_at
                )
                db.add(new_user)
                db.commit()
                print(f"  ✨ 已創建新用戶並設定主管角色: {manager.name} ({manager.line_user_id[:10]}...)")
                created_count += 1

        print("\n" + "=" * 50)
        print(f"📊 遷移完成:")
        print(f"   - 更新現有用戶: {migrated_count} 位")
        print(f"   - 創建新用戶: {created_count} 位")
        print(f"   - 已跳過（重複）: {skipped_count} 位")
        print("=" * 50)

        print("\n⚠️  注意：managers 表已保留，如確認遷移成功可手動刪除")
        print("    刪除命令: DROP TABLE managers;")

    except Exception as e:
        print(f"❌ 遷移失敗: {e}")
        db.rollback()
        raise

    finally:
        db.close()


def verify_migration():
    """驗證遷移結果"""
    db = SessionLocal()

    try:
        # 統計有主管角色的用戶
        users_with_manager_role = db.query(User).filter(
            User.roles.contains('"manager"')
        ).all()

        print(f"\n📊 驗證結果:")
        print(f"   目前有 {len(users_with_manager_role)} 位用戶具有主管角色")

        for user in users_with_manager_role:
            notification_status = "開啟" if user.manager_notification_enabled else "關閉"
            print(f"   - {user.display_name}: 通知{notification_status}")

    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("🔄 開始遷移主管資料到用戶表...")
    print("=" * 50 + "\n")

    migrate_managers()
    verify_migration()
