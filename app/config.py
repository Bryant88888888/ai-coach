from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """應用程式設定"""

    # LINE Bot 設定
    line_channel_access_token: str = ""
    line_channel_secret: str = ""

    # OpenAI 設定
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # 資料庫設定
    database_url: str = "sqlite:///./aicoach.db"

    # 應用程式設定
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """取得設定（使用快取）"""
    return Settings()
