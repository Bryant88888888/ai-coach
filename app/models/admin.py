"""管理員帳號與角色模型"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import json


class AdminRole(Base):
    """管理員角色表"""
    __tablename__ = "admin_roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    permissions = Column(Text, nullable=False, default="[]")  # JSON array of permission strings
    is_system = Column(Boolean, default=False)  # 系統角色不可刪除
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    accounts = relationship("AdminAccount", back_populates="role")

    def get_permissions(self) -> list[str]:
        """取得角色的所有權限"""
        if not self.permissions:
            return []
        try:
            return json.loads(self.permissions)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_permissions(self, perms: list[str]) -> None:
        """設定角色權限"""
        self.permissions = json.dumps(perms)

    def __repr__(self):
        return f"<AdminRole(id={self.id}, name={self.name})>"


class AdminAccount(Base):
    """管理員帳號表"""
    __tablename__ = "admin_accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # 格式: salt_hex:hash_hex（LINE 登入可免密碼）
    display_name = Column(String(100), nullable=False)
    line_user_id = Column(String(100), nullable=True, unique=True, index=True)  # LINE User ID（用於免密碼登入）
    role_id = Column(Integer, ForeignKey("admin_roles.id"), nullable=True)
    is_super_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    role = relationship("AdminRole", back_populates="accounts")

    def get_permissions(self) -> list[str]:
        """取得此帳號的所有權限（超管返回所有權限）"""
        if self.is_super_admin:
            return ALL_PERMISSIONS
        if self.role:
            return self.role.get_permissions()
        return []

    def has_permission(self, permission: str) -> bool:
        """檢查是否有指定權限"""
        if self.is_super_admin:
            return True
        return permission in self.get_permissions()

    def __repr__(self):
        return f"<AdminAccount(id={self.id}, username={self.username})>"


# ===== 權限定義 =====

# 所有可用權限（格式: page_key:action）
PERMISSION_REGISTRY = {
    "dashboard:view": {"label": "檢視儀表板", "group": "儀表板"},
    "users:view": {"label": "檢視用戶列表", "group": "人員管理"},
    "users:edit": {"label": "編輯用戶", "group": "人員管理"},
    "managers:view": {"label": "檢視主管設定", "group": "人員管理"},
    "managers:edit": {"label": "管理主管", "group": "人員管理"},
    "profiles:view": {"label": "檢視人事資料", "group": "人員管理"},
    "profiles:edit": {"label": "編輯人事資料", "group": "人員管理"},
    "courses:view": {"label": "檢視課程", "group": "教育訓練"},
    "courses:edit": {"label": "管理課程", "group": "教育訓練"},
    "training:view": {"label": "檢視訓練", "group": "教育訓練"},
    "training:edit": {"label": "管理訓練", "group": "教育訓練"},
    "messages:view": {"label": "檢視對話記錄", "group": "教育訓練"},
    "duty:view": {"label": "檢視排班", "group": "日常管理"},
    "duty:edit": {"label": "管理排班", "group": "日常管理"},
    "leave:view": {"label": "檢視請假", "group": "日常管理"},
    "leave:edit": {"label": "審核請假", "group": "日常管理"},
    "morning:view": {"label": "檢視早會日報", "group": "日常管理"},
    "morning:edit": {"label": "填寫早會日報", "group": "日常管理"},
    "admin:view": {"label": "檢視權限管理", "group": "系統管理"},
    "admin:edit": {"label": "管理帳號角色", "group": "系統管理"},
}

ALL_PERMISSIONS = list(PERMISSION_REGISTRY.keys())

# 側邊欄結構定義
SIDEBAR_ITEMS = [
    {"key": "dashboard", "label": "儀表板", "icon": "fa-chart-line", "url": "/dashboard", "permission": "dashboard:view"},
    {"group": "人員管理", "icon": "fa-people-group", "keys": ["users", "managers", "profiles"], "items": [
        {"key": "users", "label": "用戶列表", "icon": "fa-users", "url": "/dashboard/users", "permission": "users:view"},
        {"key": "managers", "label": "主管設定", "icon": "fa-user-tie", "url": "/dashboard/managers", "permission": "managers:view"},
        {"key": "profiles", "label": "人事資料", "icon": "fa-id-card", "url": "/dashboard/profiles", "permission": "profiles:view"},
    ]},
    {"group": "教育訓練", "icon": "fa-book-open", "keys": ["days", "training", "messages"], "items": [
        {"key": "days", "label": "課程管理", "icon": "fa-calendar-alt", "url": "/dashboard/days", "permission": "courses:view"},
        {"key": "training", "label": "訓練管理", "icon": "fa-graduation-cap", "url": "/dashboard/training", "permission": "training:view"},
        {"key": "messages", "label": "對話記錄", "icon": "fa-comments", "url": "/dashboard/messages", "permission": "messages:view"},
    ]},
    {"group": "日常管理", "icon": "fa-clipboard-list", "keys": ["duty", "leave", "morning"], "items": [
        {"key": "duty", "label": "排班管理", "icon": "fa-broom", "url": "/dashboard/duty", "permission": "duty:view"},
        {"key": "leave", "label": "請假管理", "icon": "fa-calendar-check", "url": "/dashboard/leave", "permission": "leave:view"},
        {"key": "morning", "label": "早會日報", "icon": "fa-clipboard-check", "url": "/dashboard/morning-report", "permission": "morning:view"},
    ]},
    {"group": "系統管理", "icon": "fa-gear", "keys": ["admin"], "items": [
        {"key": "admin", "label": "權限管理", "icon": "fa-shield-halved", "url": "/dashboard/admin", "permission": "admin:view"},
    ]},
]

# 預設角色範本
DEFAULT_ROLES = {
    "超級管理員": {
        "description": "擁有所有功能的完整存取權限",
        "permissions": list(PERMISSION_REGISTRY.keys()),
    },
    "組長": {
        "description": "可檢視與管理大部分功能，但無法管理系統設定",
        "permissions": [
            "dashboard:view",
            "users:view", "users:edit",
            "managers:view",
            "profiles:view", "profiles:edit",
            "training:view", "training:edit",
            "messages:view",
            "duty:view", "duty:edit",
            "leave:view", "leave:edit",
            "morning:view", "morning:edit",
        ],
    },
    "助理": {
        "description": "僅可檢視各頁面資料，無法進行編輯操作",
        "permissions": [
            "dashboard:view",
            "users:view",
            "managers:view",
            "profiles:view",
            "training:view",
            "messages:view",
            "duty:view",
            "leave:view",
            "morning:view",
        ],
    },
}
