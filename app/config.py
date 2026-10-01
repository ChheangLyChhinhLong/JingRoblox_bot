from functools import lru_cache
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    telegram_admin_ids: str = ""
    supabase_url: str
    supabase_service_role_key: str
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    khpay_api_key: str
    khpay_base_url: str = "https://khpay.site/api/v1"
    khpay_webhook_secret: str = ""
    khpay_webhook_url: str = ""
    public_base_url: str = ""
    stock_encryption_key: str
    stock_notification_chat_ids: str = ""
    support_username: str = ""
    poll_interval_seconds: int = 20
    port: int = 10000

    @property
    def admin_ids(self) -> set[int]:
        return {int(value.strip()) for value in self.telegram_admin_ids.split(",") if value.strip()}

    @property
    def app_base_url(self) -> str | None:
        value = self.public_base_url.strip() or self.khpay_webhook_url.strip()
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            return None
        return f"https://{parsed.netloc}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
