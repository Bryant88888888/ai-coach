from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum
import json


class UserStatus(str, enum.Enum):
    """用戶狀態"""
    ACTIVE = "Active"
    INACTIVE = "Inactive"


class Persona(str, enum.Enum):
    """用戶類別（經驗程度）"""
    A_NO_EXPERIENCE = "A_無經驗"      # 無經驗：保守、警戒心強
    B_HAS_EXPERIENCE = "B_有經驗"     # 有經驗：做過制服/禮服店


class UserRole(str, enum.Enum):
    """用戶角色"""
    TRAINEE = "trainee"           # 受訓者（預設）
    STAFF = "staff"               # 員工
    DUTY_MEMBER = "duty_member"   # 值日生
    MANAGER = "manager"           # 主管
    ADMIN = "admin"               # 管理員


class User(Base):
    """用戶資料表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, index=True, nullable=False)
    line_display_name = Column(String(100), nullable=True)  # LINE 顯示名稱
    line_picture_url = Column(String(500), nullable=True)   # LINE 大頭貼
    real_name = Column(String(100), nullable=True)          # 本名
    name = Column(String(100), nullable=True)               # 舊欄位，保留相容性
    current_day = Column(Integer, default=0)
    current_round = Column(Integer, default=0)  # 當天訓練的對話輪數
    status = Column(String(20), default=UserStatus.ACTIVE.value)
    persona = Column(String(20), nullable=True)
    notification_enabled = Column(Boolean, default=True)  # 是否接收課程通知
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 新增欄位：統一用戶系統
    roles = Column(Text, default='["trainee"]')  # JSON array: trainee, staff, duty_member, manager, admin
    phone = Column(String(20), nullable=True)  # 電話號碼
    nickname = Column(String(100), nullable=True)  # 暱稱（綽號）
    registered_at = Column(DateTime(timezone=True), nullable=True)  # 正式註冊時間
    manager_notification_enabled = Column(Boolean, default=True)  # 主管通知設定

    # 關聯
    messages = relationship("Message", back_populates="user", order_by="Message.created_at.desc()")
    trainings = relationship("UserTraining", back_populates="user", order_by="UserTraining.created_at.desc()")
    leave_requests = relationship("LeaveRequest", back_populates="user", order_by="LeaveRequest.created_at.desc()")
    duty_schedules = relationship("DutySchedule", back_populates="user", order_by="DutySchedule.duty_date.desc()")

    def __repr__(self):
        return f"<User(id={self.id}, line_user_id={self.line_user_id}, current_day={self.current_day})>"

    @property
    def status_enum(self) -> UserStatus:
        """取得狀態的 Enum 值"""
        return UserStatus(self.status) if self.status else UserStatus.ACTIVE

    @property
    def persona_enum(self) -> Persona | None:
        """取得 Persona 的 Enum 值"""
        return Persona(self.persona) if self.persona else None

    @property
    def active_training(self):
        """取得目前進行中的訓練"""
        for training in self.trainings:
            if training.status == "active":
                return training
        return None

    @property
    def display_name(self) -> str:
        """取得顯示名稱（優先 LINE 名稱）"""
        return self.line_display_name or self.real_name or self.name or "未命名"

    # ===== 角色管理方法 =====

    def get_roles(self) -> list[str]:
        """取得用戶的所有角色"""
        if not self.roles:
            return ["trainee"]
        try:
            return json.loads(self.roles)
        except (json.JSONDecodeError, TypeError):
            return ["trainee"]

    def has_role(self, role: str) -> bool:
        """檢查用戶是否有指定角色"""
        return role in self.get_roles()

    def add_role(self, role: str) -> None:
        """為用戶添加角色"""
        roles = self.get_roles()
        if role not in roles:
            roles.append(role)
            self.roles = json.dumps(roles)

    def remove_role(self, role: str) -> None:
        """移除用戶的角色"""
        roles = self.get_roles()
        if role in roles:
            roles.remove(role)
            if not roles:
                roles = ["trainee"]  # 至少保留 trainee 角色
            self.roles = json.dumps(roles)

    @property
    def is_manager(self) -> bool:
        """是否為主管"""
        return self.has_role(UserRole.MANAGER.value)

    @property
    def is_admin(self) -> bool:
        """是否為管理員"""
        return self.has_role(UserRole.ADMIN.value)

    @property
    def is_duty_member(self) -> bool:
        """是否為值日生"""
        return self.has_role(UserRole.DUTY_MEMBER.value)

    @property
    def is_staff(self) -> bool:
        """是否為員工"""
        return self.has_role(UserRole.STAFF.value)
