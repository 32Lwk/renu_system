-# ReNU 勤怠・シフト管理 Webアプリ
-
-Python + FastAPI 製の ReNU 勤怠・シフト管理システムです。
-
-本番では Google スプレッドシートのみをデータストアとして利用し、開発用に SQLite のモックDBを用意します。
-
-## セットアップ（ローカル開発）
-
-1. Python 3.11 以降をインストールする
-2. 仮想環境を作成・有効化する
-
-```bash
-python -m venv .venv
-(Windows) .\.venv\Scripts\activate
-(Unix)    source .venv/bin/activate
-```
-
-3. 依存パッケージをインストールする
-
-```bash
-pip install -r requirements.txt
-```
-
-4. `.env` を作成する（`.env.example` をコピーして編集）
-
-```bash
-cp .env.example .env  # PowerShell の場合は Copy-Item .env.example .env
-```
-
-主要な項目:
-
-- `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` : 開発用サービスアカウント JSON のパス
-- `SPREADSHEET_ID` : ReNU 本番 / 開発用スプレッドシートの ID
-- `DATA_SOURCE` : `"sheets"` または `"mockdb"`
-- `ADMIN_PASSWORD_HASH` : 管理画面ログイン用パスワード（簡易実装）
-- `SECRET_KEY` : FastAPI セッション用シークレット
-
-5. 開発サーバーを起動する
-
-```bash
-uvicorn app.main:app --reload
-```
-
-## ディレクトリ構成
-
-`app/main.py` : FastAPI アプリのエントリポイント  
-`app/templates/` : Jinja2 テンプレート  
-`app/static/` : CSS などの静的ファイル  
-`app/routers/` : 画面ごとのルーター (`admin`, `member`, `busy` など)  
-`app/services/` : DB・Sheets・割当アルゴリズムなどのサービス層  
-`app/schemas/` : Pydantic スキーマ  
-`app/core/` : 設定・認証などのコア機能  
-
-## Google Sheets スキーマ
-
-本番の「正」となるシート群は `app/services/sheet_schemas.py` に集約されています。
-
-### members シート
-
-論理名 / 物理カラムは以下のとおりです。
-
-- `member_id` : 内部 UUID
-- `full_name` : 氏名
-- `student_id` : 学籍番号（学部学科2桁 + 入学年度2桁 + 任意5桁）
-- `email` : メールアドレス
-- `faculty_code` : 学部コード（01〜09,17 など）
-- `entrance_year` : 入学年度（例: 24,25）
-- `grade` : 学年（B1/B2/B3）
-- `discord_user_id` : Discord ユーザー ID
-- `discord_username` : Discord の表示名
-- `teams` : 所属班（カンマ区切り: すまい,PC,提案,キャリア）
-- `roles` : 役職（Leader/SubLeader/Chief/Member など）
-- `status` : メンバー状態（`pending` / `email_verified` / `merge_pending` / `active` / `inactive`）
-- `email_verified` : メール認証済みフラグ
-- `email_verified_at` : メール認証日時
-- `merge_target_member_id` : マージ先メンバー ID
-- `approved_by` : 承認者
-- `approved_at` : 承認日時
-- `created_at` : 作成日時
-- `last_login_at` : 最終ログイン日時
-- `updated_at` : 更新日時
-
-### email_verifications シート
-
-- `verification_id` : UUID
-- `member_id` : members.member_id への参照
-- `email` : 対象メールアドレス
-- `code_hash` : 6桁コードのハッシュ値
-- `expires_at` : 有効期限
-- `attempt_count` : 試行回数
-- `verified_at` : 検証完了日時
-- `created_at` : 作成日時
-
-### events / attendances / attendance_changes / busy_preferences
-
-詳細は `app/services/sheet_schemas.py` を参照してください。  
-計画書に記載された以下の情報を保持します。
-
-- `events` : イベント ID / 日付 / 時間 / 名前 / 必要人数 / 対象班 / 繁忙期フラグ / 確定フラグ など
-- `attendances` : イベント ID / メンバー ID / 役割 / 状態（planned/absent/late/leave_early）/ 備考 / 更新日時
-- `attendance_changes` : 出勤 ID / 変更日時 / 変更種別 / 理由 / 申請元（web-admin/web-member/email 等）
-- `busy_preferences` : 繁忙期の希望シフト情報（メンバーごとの希望・優先度・上限数など）
-
-`sheet_schemas.get_headers(SheetName.XXX)` を利用すると、各シートのヘッダー行を Python から取得できます。
-
-## GCP インフラ構成（Cloud Run / GCE / GAS）
-
-本プロジェクトでは、次のような GCP 構成を想定しています。
-
-- **Cloud Run** : FastAPI 本体（このリポジトリ）をコンテナ化してデプロイ
-- **GCE (e2-micro)** : Discord Bot を常時稼働させるための VM
-- **Apps Script (GAS)** : 共通 Gmail アカウント経由でのメール送信と、Sheets 連携
-
-### 1. GCP プロジェクト作成
-
-1. GCP コンソールでプロジェクトを作成する（既存プロジェクトを利用しても可）
-2. 課金を有効化する
-3. `Cloud Run`, `Cloud Build`, `Artifact Registry`, `Compute Engine`, `Apps Script` を有効化する
-
-### 2. サービスアカウントと権限
-
-#### 共通サービスアカウント（Sheets / Drive 用）
-
-- 名前例: `renu-sheets-sa`
-- 付与ロール:
-  - `roles/drive.file`
-  - `roles/spreadsheets`
-- このサービスアカウントの JSON キーを作成し、ローカル開発用に `.env` の
-  `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` として参照します。
-- 本番では Secret Manager または Cloud Run の環境変数に JSON を格納し、コード側では
-  ファイルではなく環境変数から読み込むように差し替えることを想定しています（後続タスク）。
-
-#### Cloud Run 用サービスアカウント
-
-- 名前例: `renu-cloudrun-sa`
-- 付与ロール:
-  - `roles/run.invoker`（必要に応じて）
-  - Sheets への読み書きが必要な場合は、上記 Sheets 用ロールを追加
-- Cloud Run サービス作成時に、このサービスアカウントを実行サービスアカウントとして指定します。
-
-#### GCE (Discord Bot 用) サービスアカウント
-
-- 名前例: `renu-bot-sa`
-- 付与ロール:
-  - 必要に応じて Logs, Monitoring, Secret Manager など
-- VM の作成時に、このサービスアカウントを割り当てます。
-
-### 3. Cloud Run デプロイ（FastAPI）
-
-1. Docker イメージをビルドし、Artifact Registry に push する
-
-```bash
-gcloud builds submit --tag "REGION-docker.pkg.dev/PROJECT_ID/renu/fastapi"
-```
-
-2. Cloud Run サービスを作成する
-
-```bash
-gcloud run deploy renu-fastapi `
-  --image="REGION-docker.pkg.dev/PROJECT_ID/renu/fastapi" `
-  --platform=managed `
-  --region=REGION `
-  --service-account=renu-cloudrun-sa `
-  --allow-unauthenticated
-```
-
-3. Cloud Run の環境変数として以下を設定する
-
-- `DATA_SOURCE=sheets`
-- `SPREADSHEET_ID=<本番シートのID>`
-- `ADMIN_PASSWORD_HASH=<運用用パスワード>`
-- `SECRET_KEY=<十分に長いランダム文字列>`
-- Discord OAuth / OpenAI キーなどは A-3 で整理する値を設定
-
-### 4. GCE（Discord Bot 用 VM）
-
-1. e2-micro などの小さめインスタンスを作成
-2. SSH でログインし、Python 環境と Git をインストール
-3. Bot 用のコードリポジトリを clone し、`.env` を配置
-4. `systemd` などで常駐起動設定を行う（例: `renu-bot.service`）
-
-### 5. GAS（Gmail 送信用 Apps Script）
-
-1. 共通 Gmail アカウントにログインし、Apps Script プロジェクトを作成
-2. members / email_verifications / events などのスプレッドシートと連携する
-3. HTTP 経由で FastAPI 側からトリガーできるよう、`doPost` エンドポイントを実装する
-4. 認証メール / リマインドメールのテンプレート文面は、後続タスク F-3 で整備する
-
-## 運用モード
-
-- `DATA_SOURCE=mockdb` : ローカル SQLite を用いたモックDB モード（`app/services/db.py`）
-- `DATA_SOURCE=sheets` : Google Sheets を正とする本番運用モード（`app/services/sheet_client.py`）
-
-管理画面やメンバー画面は、設定値に応じてモックDB / Sheets のいずれかを参照するよう実装されています。
+
+-## Discord Bot（同梱サンプル）
+
+-このリポジトリには最小構成の Bot 実装を `bot/` に同梱しています。
+
+-### セットアップ
+
+-```bash
+-cd bot
+-python -m venv .venv
+-(Windows) .\.venv\Scripts\activate
+-pip install -r requirements.txt
+-```
+
+-### 環境変数（例）
+
+--- `DISCORD_BOT_TOKEN`
+--- `API_BASE_URL`（FastAPI の URL）
+--- `BOT_API_SECRET`（FastAPI 側と共有。簡易実装では `GAS_WEBHOOK_SECRET` を流用）
+--- `BOT_COMMANDS_CHANNEL`（既定 `renu-bot-commands`）
+--- `OPENAI_API_KEY`（FAQ 用）
+
+-### 起動
+
+-```bash
+-python main.py
+-```
+
+-## ドキュメント
+
+--- 運用マニュアル（簡易）: `docs/operations.md`
+--- メールテンプレ（草案）: `docs/templates/emails.md`

