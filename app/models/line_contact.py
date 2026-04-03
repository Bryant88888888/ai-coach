from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import json

from app.models.user import NOTIFICATION_CATEGORIES, ALL_NOTIFICATION_CATEGORIES


class LineContact(Base):
    """LINE 聯絡人（透過 webhook 加好友建立，可接收推播）"""
    __tablename__ = "line_contacts"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False, index=True)
    line_display_name = Column(String(100), nullable=True)
    line_picture_url = Column(String(500), nullable=True)

    # 主管通知設定
    is_manager = Column(Boolean, default=False)
    manager_notification_enabled = Column(Boolean, default=True)
    manager_notification_categories = Column(Text, nullable=True)  # JSON array

    # 連結到已註冊用戶
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", backref="line_contact", foreign_keys=[user_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def display_name(self):
        """顯示名稱"""
        return self.line_display_name or f"LINE User {self.id}"

    def get_notification_categories(self):
        """取得訂閱的通知類別"""
        if self.manager_notification_categories is None:
            return ALL_NOTIFICATION_CATEGORIES
        try:
            return json.loads(self.manager_notification_categories)
        except (json.JSONDecodeError, TypeError):
            return ALL_NOTIFICATION_CATEGORIES

    def set_notification_categories(self, categories):
        """設定訂閱的通知類別"""
        self.manager_notification_categories = json.dumps(categories)

    def has_notification_category(self, category):
        """檢查是否訂閱指定通知類別"""
        return category in self.get_notification_categories()
