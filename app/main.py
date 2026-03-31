import warnings

# requests の urllib3/chardet バージョン警告を無視（import 前に module 指定で登録）
warnings.filterwarnings("ignore", module="requests")
# 依存ライブラリ由来の Pydantic class-based config 非推奨警告を無視（自コードは ConfigDict 移行済み）
warnings.filterwarnings("ignore", message=".*class-based.*config.*deprecated.*")

from contextlib import asynccontextmanager
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.config import get_settings
from app.routers import admin as admin_router
from app.routers import member as member_router
from app.routers import busy as busy_router
from app.routers import auth as auth_router
from app.routers import bot_api as bot_api_router
from app.routers import notifications as notifications_router
from app.services.db import init_db
from app.services.reminder import build_reminder_messages


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: モックDBモードのときのみ SQLite を初期化
    settings = get_settings()
    if settings.data_source.lower() == "mockdb":
        init_db()
    yield
    # shutdown（必要ならここに処理を追加）


def create_app() -> FastAPI:
    app = FastAPI(title="ReNU Attendance & Shift Manager", lifespan=lifespan)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=templates_dir)

    app.include_router(admin_router.router)
    app.include_router(member_router.router)
    app.include_router(busy_router.router)
    app.include_router(auth_router.router)
    app.include_router(bot_api_router.router)
    app.include_router(notifications_router.router)

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        settings = get_settings()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "title": "ReNU 勤怠・シフト管理",
                "dev_login_available": bool(getattr(settings, "enable_dev_login", False)),
            },
        )

    # ブラウザや過去キャッシュ由来で /styles.css /main.js が要求されることがあるため、
    # /static 側に寄せて 404 を避ける（実体は /static/base.css のみでも動作する）。
    @app.get("/styles.css", include_in_schema=False)
    async def legacy_styles_css():
        return RedirectResponse(url="/static/base.css", status_code=307)

    @app.get("/main.js", include_in_schema=False)
    async def legacy_main_js():
        # 現状フロント JS は必須ではないため、空で返す（ログの 404 ノイズを抑える）
        return Response(content="", media_type="application/javascript")

    # favicon / touch icon はブラウザが自動で取りに行く。未提供なら 204 で静かに処理する。
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_ico():
        return Response(status_code=204)

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    async def apple_touch_icon_png():
        return Response(status_code=204)

    @app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
    async def apple_touch_icon_precomposed_png():
        return Response(status_code=204)

    @app.get("/debug/reminders")
    async def debug_reminders():
        """開発用: 翌日のリマインドメッセージを確認するための簡易エンドポイント。"""
        msgs = build_reminder_messages()
        return {"messages": msgs}

    return app
app = create_app()


if __name__ == "__main__":
    # 開発用: 直接実行時に uvicorn でサーバー起動
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
