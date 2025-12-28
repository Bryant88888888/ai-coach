from sqlalchemy.orm import Session
from app.models.user import User, UserStatus, Persona
from typing import Optional


class UserService:
    """用戶管理服務"""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_line_id(self, line_user_id: str) -> Optional[User]:
        """透過 LINE User ID 取得用戶"""
        return self.db.query(User).filter(User.line_user_id == line_user_id).first()

    def create_user(
        self,
        line_user_id: str,
        line_display_name: Optional[str] = None,
        line_picture_url: Optional[str] = None,
        name: Optional[str] = None
    ) -> User:
        """建立新用戶"""
        user = User(
            line_user_id=line_user_id,
            line_display_name=line_display_name,
            line_picture_url=line_picture_url,
            name=name,
            current_day=0,
            status=UserStatus.ACTIVE.value,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_or_create_user(
        self,
        line_user_id: str,
        line_display_name: Optional[str] = None,
        line_picture_url: Optional[str] = None
    ) -> tuple[User, bool]:
        """
        取得或建立用戶
        回傳: (user, is_new) - is_new 表示是否為新建立的用戶
        """
        user = self.get_user_by_line_id(line_user_id)
        if user:
            # 更新 LINE 資料（如果有變更）
            updated = False
            if line_display_name and user.line_display_name != line_display_name:
                user.line_display_name = line_display_name
                updated = True
            if line_picture_url and user.line_picture_url != line_picture_url:
                user.line_picture_url = line_picture_url
                updated = True
            if updated:
                self.db.commit()
                self.db.refresh(user)
            return user, False
        return self.create_user(line_user_id, line_display_name, line_picture_url), True

    def update_progress(self, user: User, new_day: int) -> User:
        """更新用戶訓練進度"""
        user.current_day = new_day
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_persona(self, user: User, persona: str) -> User:
        """
        設定用戶 Persona（經驗類別）

        Args:
            user: 用戶物件
            persona: "A" 或 "B" 或完整值
        """
        # 轉換為完整的 Persona 值
        if persona == "A":
            user.persona = Persona.A_NO_EXPERIENCE.value
        elif persona == "B":
            user.persona = Persona.B_HAS_EXPERIENCE.value
        else:
            user.persona = persona

        self.db.commit()
        self.db.refresh(user)
        return user

    def classify_persona(self, user: User, first_message: str) -> str:
        """
        根據用戶第一句話分類 Persona

        A（無經驗）特徵：
        - 問安全相關：「會不會很危險？」「安全嗎？」
        - 擔心害怕：「我很怕」「會不會被...」
        - 詢問基本問題

        B（有經驗）特徵：
        - 問待遇：「節薪多少？」「抽成怎麼算？」
        - 問制度：「有保障嗎？」「可以日領嗎？」
        - 比較其他店：「跟XX店比...」
        """
        message_lower = first_message.lower()

        # 有經驗的關鍵字
        experienced_keywords = [
            "節薪", "抽成", "日領", "週領", "保障", "底薪",
            "之前", "以前", "做過", "待過", "其他店", "別家",
            "制服店", "禮服店", "便服店", "酒店", "ktv",
            "框", "加鐘", "節數", "檯費",
        ]

        # 無經驗的關鍵字
        inexperienced_keywords = [
            "危險", "安全", "害怕", "怕", "擔心",
            "色情", "會不會", "是不是", "第一次",
            "不知道", "不了解", "新手", "沒做過",
        ]

        # 計算關鍵字匹配
        exp_score = sum(1 for kw in experienced_keywords if kw in message_lower)
        inexp_score = sum(1 for kw in inexperienced_keywords if kw in message_lower)

        # 判斷 Persona
        if exp_score > inexp_score:
            persona = Persona.B_HAS_EXPERIENCE.value
        else:
            persona = Persona.A_NO_EXPERIENCE.value

        # 更新用戶 Persona
        return self.set_persona(user, persona).persona

    def get_all_users(self) -> list[User]:
        """取得所有用戶"""
        return self.db.query(User).all()

    def get_active_users(self) -> list[User]:
        """取得所有活躍用戶"""
        return self.db.query(User).filter(User.status == UserStatus.ACTIVE.value).all()
