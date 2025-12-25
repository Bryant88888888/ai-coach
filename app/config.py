from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """應用程式設定"""

    # LINE Bot 設定
    line_channel_access_token: str = ""
    line_channel_secret: str = ""

    # Anthropic Claude 設定
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    # 資料庫設定
    database_url: str = "sqlite:///./aicoach.db"

    # 應用程式設定
    debug: bool = False

    # Cron Job 設定（可選，用於驗證排程請求）
    cron_secret: str = ""

    # Admin 後台設定
    admin_username: str = "admin"
    admin_password: str = "ilovetaiwan"
    session_secret_key: str = "aicoach-secret-key-change-in-production-2024"

    # LIFF 設定（LINE 前端框架）
    liff_id: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """取得設定（使用快取）"""
    return Settings()
