from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FastAPISecrets:
    """FastAPI アプリ側で利用する主な環境変数・シークレットの一覧。"""

    # Sheets / Google API
    GOOGLE_SERVICE_ACCOUNT_JSON_PATH: str = "GOOGLE_SERVICE_ACCOUNT_JSON_PATH"
    SPREADSHEET_ID: str = "SPREADSHEET_ID"

    # データソース切り替え
    DATA_SOURCE: str = "DATA_SOURCE"

    # アプリケーションシークレット
    ADMIN_PASSWORD_HASH: str = "ADMIN_PASSWORD_HASH"
    SECRET_KEY: str = "SECRET_KEY"

    # Discord OAuth
    DISCORD_CLIENT_ID: str = "DISCORD_CLIENT_ID"
    DISCORD_CLIENT_SECRET: str = "DISCORD_CLIENT_SECRET"
    DISCORD_REDIRECT_URI: str = "DISCORD_REDIRECT_URI"

    # OpenAI / AI 連携
    OPENAI_API_KEY: str = "OPENAI_API_KEY"


@dataclass(frozen=True)
class BotSecrets:
    """Discord Bot 側で利用する主な環境変数・シークレットの一覧。"""

    DISCORD_BOT_TOKEN: str = "DISCORD_BOT_TOKEN"
    OPENAI_API_KEY: str = "OPENAI_API_KEY"
    API_BASE_URL: str = "API_BASE_URL"


@dataclass(frozen=True)
class GASSecrets:
    """GAS 側で利用する主なシークレット・設定値の一覧（Apps Script プロパティとして管理想定）。"""

    # FastAPI 側の署名検証などに使う共有シークレット
    FASTAPI_WEBHOOK_SECRET: str = "FASTAPI_WEBHOOK_SECRET"

    # 認証メール・リマインドメールの送信元名など
    MAIL_FROM_NAME: str = "MAIL_FROM_NAME"

