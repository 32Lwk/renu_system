# 運用マニュアル（簡易）

## 管理者向け

- 管理画面ログイン: `/admin/login`
- 名簿:
  - 一覧: `/admin/members`
  - 新規: `/admin/members/new`
  - 編集: `/admin/members/{member_id}/edit`
  - 無効化: `/admin/members/{member_id}/deactivate`
- 統合承認（merge_pending）:
  - 一覧: `/admin/merge-requests`

## メンバー向け

- Discord OAuth: `/auth/discord/start`
- メール入力: `/onboarding/email`
- コード確認: `/onboarding/verify`
- プロフィール: `/onboarding/profile`
- 繁忙期希望: `/my/busy/preferences`

## Discord Bot（概要）

- コマンド実行チャンネル: `#renu-bot-commands`（既定。環境変数 `BOT_COMMANDS_CHANNEL` で変更可）
- 主要コマンド:
  - `/sync-member-roles member_id`
  - `/create-event-channel event_id`
  - `/create-group-channel group_name`
  - `/faq question`
  - `/ai-propose command target`
  - `/ai-approve action_id`

