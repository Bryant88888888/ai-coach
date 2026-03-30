"""權限管理服務"""
import hashlib
import secrets
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.admin import (
    AdminAccount, AdminRole,
    ALL_PERMISSIONS, SIDEBAR_ITEMS, DEFAULT_ROLES
)
from app.config import get_settings


class PermissionService:
    """管理員帳號、角色與權限服務"""

    def __init__(self, db: Session):
        self.db = db

    # ===== 密碼管理 =====

    @staticmethod
    def hash_password(password: str) -> str:
        """雜湊密碼，返回 salt_hex:hash_hex 格式"""
        salt = secrets.token_hex(16)
        hash_value = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"{salt}:{hash_value}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """驗證密碼是否正確"""
        try:
            salt, stored_hash = password_hash.split(":", 1)
            computed_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            return secrets.compare_digest(computed_hash, stored_hash)
        except (ValueError, AttributeError):
            return False

    # ===== AdminAccount CRUD =====

    def get_admin_by_username(self, username: str) -> AdminAccount | None:
        return self.db.query(AdminAccount).filter(AdminAccount.username == username).first()

    def get_admin_by_id(self, admin_id: int) -> AdminAccount | None:
        return self.db.query(AdminAccount).filter(AdminAccount.id == admin_id).first()

    def get_all_admins(self) -> list[AdminAccount]:
        return self.db.query(AdminAccount).order_by(AdminAccount.created_at).all()

    def create_admin(self, username: str, password: str, display_name: str,
                     role_id: int | None = None, is_super_admin: bool = False) -> AdminAccount:
        """建立管理員帳號"""
        admin = AdminAccount(
            username=username,
            password_hash=self.hash_password(password),
            display_name=display_name,
            role_id=role_id,
            is_super_admin=is_super_admin,
            is_active=True,
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)
        return admin

    def update_admin(self, admin_id: int, **kwargs) -> AdminAccount | None:
        """更新管理員帳號"""
        admin = self.get_admin_by_id(admin_id)
        if not admin:
            return None

        # 如果要取消超管或停用，檢查是否為最後一個活躍超管
        if "is_super_admin" in kwargs and not kwargs["is_super_admin"] and admin.is_super_admin:
            if not self._has_other_active_super_admin(admin_id):
                raise ValueError("無法取消最後一個超級管理員的權限")

        if "is_active" in kwargs and not kwargs["is_active"] and admin.is_active:
            if admin.is_super_admin and not self._has_other_active_super_admin(admin_id):
                raise ValueError("無法停用最後一個超級管理員")

        # 密碼特殊處理
        if "password" in kwargs:
            password = kwargs.pop("password")
            if password:  # 空字串表示不更改
                admin.password_hash = self.hash_password(password)

        for key, value in kwargs.items():
            if hasattr(admin, key):
                setattr(admin, key, value)

        self.db.commit()
        self.db.refresh(admin)
        return admin

    def delete_admin(self, admin_id: int) -> bool:
        """刪除管理員帳號"""
        admin = self.get_admin_by_id(admin_id)
        if not admin:
            return False

        if admin.is_super_admin and not self._has_other_active_super_admin(admin_id):
            raise ValueError("無法刪除最後一個超級管理員")

        self.db.delete(admin)
        self.db.commit()
        return True

    def toggle_admin_active(self, admin_id: int) -> AdminAccount | None:
        """切換管理員啟用狀態"""
        admin = self.get_admin_by_id(admin_id)
        if not admin:
            return None

        new_active = not admin.is_active
        if not new_active and admin.is_super_admin:
            if not self._has_other_active_super_admin(admin_id):
                raise ValueError("無法停用最後一個超級管理員")

        admin.is_active = new_active
        self.db.commit()
        self.db.refresh(admin)
        return admin

    def _has_other_active_super_admin(self, exclude_id: int) -> bool:
        """檢查是否有其他活躍的超級管理員"""
        count = self.db.query(AdminAccount).filter(
            AdminAccount.id != exclude_id,
            AdminAccount.is_super_admin == True,
            AdminAccount.is_active == True,
        ).count()
        return count > 0

    # ===== AdminRole CRUD =====

    def get_all_roles(self) -> list[AdminRole]:
        return self.db.query(AdminRole).order_by(AdminRole.created_at).all()

    def get_role_by_id(self, role_id: int) -> AdminRole | None:
        return self.db.query(AdminRole).filter(AdminRole.id == role_id).first()

    def create_role(self, name: str, description: str, permissions: list[str]) -> AdminRole:
        """建立角色"""
        # 過濾無效權限
        valid_perms = [p for p in permissions if p in ALL_PERMISSIONS]
        role = AdminRole(
            name=name,
            description=description,
            permissions=json.dumps(valid_perms),
        )
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def update_role(self, role_id: int, **kwargs) -> AdminRole | None:
        """更新角色"""
        role = self.get_role_by_id(role_id)
        if not role:
            return None

        if "permissions" in kwargs:
            perms = kwargs.pop("permissions")
            valid_perms = [p for p in perms if p in ALL_PERMISSIONS]
            role.permissions = json.dumps(valid_perms)

        for key, value in kwargs.items():
            if hasattr(role, key) and key != "is_system":
                setattr(role, key, value)

        self.db.commit()
        self.db.refresh(role)
        return role

    def delete_role(self, role_id: int) -> bool:
        """刪除角色（系統角色和有帳號使用的角色不可刪除）"""
        role = self.get_role_by_id(role_id)
        if not role:
            return False

        if role.is_system:
            raise ValueError("系統角色不可刪除")

        account_count = self.db.query(AdminAccount).filter(AdminAccount.role_id == role_id).count()
        if account_count > 0:
            raise ValueError(f"此角色還有 {account_count} 個帳號在使用，請先移除")

        self.db.delete(role)
        self.db.commit()
        return True

    # ===== 權限檢查 =====

    def has_permission(self, admin: AdminAccount, permission: str) -> bool:
        """檢查管理員是否有指定權限"""
        if not admin or not admin.is_active:
            return False
        return admin.has_permission(permission)

    def get_permissions(self, admin: AdminAccount) -> list[str]:
        """取得管理員的所有權限列表"""
        if not admin or not admin.is_active:
            return []
        return admin.get_permissions()

    def get_visible_sidebar(self, admin: AdminAccount) -> list[dict]:
        """根據權限過濾側邊欄項目"""
        permissions = self.get_permissions(admin)
        visible = []

        for item in SIDEBAR_ITEMS:
            if "group" in item:
                # 群組項目：過濾子項目
                visible_items = [
                    sub for sub in item["items"]
                    if sub["permission"] in permissions
                ]
                if visible_items:
                    visible.append({
                        "group": item["group"],
                        "icon": item["icon"],
                        "keys": [sub["key"] for sub in visible_items],
                        "items": visible_items,
                    })
            else:
                # 單一項目
                if item["permission"] in permissions:
                    visible.append(item)

        return visible

    # ===== 資料種子 =====

    def seed_default_roles(self) -> None:
        """建立預設角色（僅在無角色時執行）"""
        if self.db.query(AdminRole).count() > 0:
            return

        for name, config in DEFAULT_ROLES.items():
            role = AdminRole(
                name=name,
                description=config["description"],
                permissions=json.dumps(config["permissions"]),
                is_system=True,
            )
            self.db.add(role)

        self.db.commit()

    def seed_super_admin_from_env(self) -> None:
        """從 .env 設定建立超級管理員（僅在無帳號時執行）"""
        if self.db.query(AdminAccount).count() > 0:
            return

        settings = get_settings()
        self.create_admin(
            username=settings.admin_username,
            password=settings.admin_password,
            display_name="超級管理員",
            role_id=None,
            is_super_admin=True,
        )
