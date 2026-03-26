from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Google Sheets
    google_service_account_json_path: str | None = None
    spreadsheet_id: str | None = None

    # Data source: "sheets" or "mockdb"
    data_source: str = "sheets"

    # Admin auth
    admin_password_hash: str | None = None
    secret_key: str = "changeme-replace-in-.env"

    # Discord OAuth (member onboarding)
    discord_client_id: str | None = None
    discord_client_secret: str | None = None
    discord_redirect_uri: str | None = None

    # OpenAI
    openai_api_key: str | None = None

    # GAS (mail sending)
    gas_webhook_url: str | None = None
    gas_webhook_secret: str | None = None

    # Gmail API（OAuth2 リフレッシュトークンで送信）
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_refresh_token: str | None = None
    gmail_from_address: str | None = None
    gmail_from_name: str | None = None

    # Discord Bot（チャンネル投稿用。Message Content Intent は不要）
    discord_bot_token: str | None = None

    # Development helpers
    enable_dev_login: bool = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

