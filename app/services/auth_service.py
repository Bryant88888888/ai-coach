"""認證服務"""
from app.config import get_settings


class AuthService:
    """Admin 認證服務"""

    def __init__(self):
        settings = get_settings()
        self.admin_username = settings.admin_username
        self.admin_password = settings.admin_password

    def verify_credentials(self, username: str, password: str) -> bool:
        """驗證帳號密碼"""
        return (
            username == self.admin_username and
            password == self.admin_password
        )


def get_auth_service() -> AuthService:
    """取得認證服務實例"""
    return AuthService()
