from __future__ import annotations

import os
from dataclasses import dataclass

import discord
from discord import app_commands
from dotenv import load_dotenv
import httpx


load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    api_base_url: str
    bot_api_secret: str


def get_settings() -> Settings:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    base = os.getenv("API_BASE_URL", "").strip().rstrip("/")
    secret = os.getenv("BOT_API_SECRET", "").strip()
    if not token or not base or not secret:
        raise RuntimeError("DISCORD_BOT_TOKEN / API_BASE_URL / BOT_API_SECRET must be set")
    return Settings(discord_bot_token=token, api_base_url=base, bot_api_secret=secret)


ROLE_NAMES = {
    "AppAdmin": "AppAdmin",
    "OpsLeader": "OpsLeader",
    "Team_Sumai": "Team_Sumai",
    "Team_PC": "Team_PC",
    "Team_Teian": "Team_Teian",
    "Team_Career": "Team_Career",
    "Role_Leader": "Role_Leader",
    "Role_SubLeader": "Role_SubLeader",
    "Role_Chief": "Role_Chief",
    "Role_Member": "Role_Member",
}

COMMANDS_CHANNEL_NAME = os.getenv("BOT_COMMANDS_CHANNEL", "renu-bot-commands")


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


async def api_post(path: str, payload: dict) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(
            f"{s.api_base_url}{path}",
            json=payload,
            headers={"X-Bot-Secret": s.bot_api_secret},
        )
        r.raise_for_status()
        return r.json()


def _is_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    names = {r.name for r in interaction.user.roles}
    return ("AppAdmin" in names) or ("OpsLeader" in names)


def _in_commands_channel(interaction: discord.Interaction) -> bool:
    ch = interaction.channel
    return hasattr(ch, "name") and getattr(ch, "name") == COMMANDS_CHANNEL_NAME


@tree.command(name="sync-member-roles", description="Sheetsの名簿に基づいてロールを同期します。")
@app_commands.describe(member_id="members.member_id")
async def sync_member_roles(interaction: discord.Interaction, member_id: str):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。", ephemeral=True)
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return
    data = await api_post(
        "/bot/sync-member-roles",
        {"member_id": member_id, "actor_discord_user_id": str(interaction.user.id)},
    )
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("guild が取得できません。", ephemeral=True)
        return

    discord_user_id = data.get("discord_user_id")
    if not discord_user_id:
        await interaction.followup.send("対象メンバーに discord_user_id がありません。", ephemeral=True)
        return

    member = guild.get_member(int(discord_user_id))
    if member is None:
        await interaction.followup.send("Discordサーバー上に対象ユーザーが見つかりません。", ephemeral=True)
        return

    # 付与すべきロール名一覧（例: Team_Sumai など）
    role_names = set(data.get("role_names", []))
    # サーバー側の Role オブジェクトへ
    roles_by_name = {r.name: r for r in guild.roles}

    to_add = [roles_by_name[n] for n in role_names if n in roles_by_name]
    # 過剰に外すのは怖いので、いったん add のみ
    if to_add:
        await member.add_roles(*to_add, reason="ReNU role sync")

    await interaction.followup.send("同期しました。", ephemeral=True)


@tree.command(name="create-event-channel", description="イベント用チャンネルを作成します（管理者向け）。")
@app_commands.describe(event_id="events.event_id")
async def create_event_channel(interaction: discord.Interaction, event_id: str):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。", ephemeral=True)
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return
    data = await api_post(
        "/bot/create-event-channel",
        {"event_id": event_id, "actor_discord_user_id": str(interaction.user.id)},
    )
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("guild が取得できません。", ephemeral=True)
        return

    channel_name = data.get("channel_name")
    if not channel_name:
        await interaction.followup.send("channel_name が取得できません。", ephemeral=True)
        return

    ch = await guild.create_text_channel(channel_name, reason="ReNU event channel")
    await interaction.followup.send(f"作成しました: {ch.mention}", ephemeral=True)


@tree.command(name="create-group-channel", description="任意グループチャンネルを作成します（管理者向け）。")
@app_commands.describe(group_name="チャンネル名に使うグループ名")
async def create_group_channel(interaction: discord.Interaction, group_name: str):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。", ephemeral=True)
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return

    data = await api_post(
        "/bot/create-group-channel",
        {"group_name": group_name, "actor_discord_user_id": str(interaction.user.id)},
    )
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("guild が取得できません。", ephemeral=True)
        return
    channel_name = data.get("channel_name")
    if not channel_name:
        await interaction.followup.send("channel_name が取得できません。", ephemeral=True)
        return
    ch = await guild.create_text_channel(channel_name, reason="ReNU group channel")
    await interaction.followup.send(f"作成しました: {ch.mention}", ephemeral=True)


@tree.command(name="faq", description="ReNUのFAQをAIで回答します。")
@app_commands.describe(question="質問内容")
async def faq(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=True)
    # Bot 側は knowledge base を外部（Notion/Docs等）に置く想定。
    # ここでは最小実装として OpenAI API へ投げ、回答のみ返す。
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        await interaction.followup.send("OPENAI_API_KEY が設定されていません。", ephemeral=True)
        return

    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "あなたはReNUの勤怠・シフト運用を補助するFAQボットです。簡潔に日本語で答えてください。"},
                        {"role": "user", "content": question},
                    ],
                },
            )
            r.raise_for_status()
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        await interaction.followup.send(f"FAQ の生成に失敗しました: {e}", ephemeral=True)
        return

    await interaction.followup.send(answer, ephemeral=True)


@tree.command(name="ai-propose", description="AIに命令案を作らせ、承認待ちとして記録します（管理者向け）。")
@app_commands.describe(command="提案するコマンド", target="対象（任意）")
async def ai_propose(interaction: discord.Interaction, command: str, target: str = ""):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。", ephemeral=True)
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return
    data = await api_post(
        "/bot/ai/propose",
        {"requested_by": str(interaction.user.id), "command": command, "target": target},
    )
    await interaction.followup.send(f"提案を記録しました。action_id={data.get('action_id')}", ephemeral=True)


@tree.command(name="ai-approve", description="AI提案(action_id)を承認として記録します（管理者向け）。")
@app_commands.describe(action_id="ai_action_logs.action_id")
async def ai_approve(interaction: discord.Interaction, action_id: str):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。", ephemeral=True)
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return
    await api_post(
        "/bot/ai/approve",
        {"action_id": action_id, "approved_by": str(interaction.user.id)},
    )
    await interaction.followup.send("承認を記録しました。", ephemeral=True)


@tree.command(name="broadcast", description="指定テキストチャンネルに一斉連絡を投稿します。")
@app_commands.describe(channel="投稿先チャンネル", message="本文（2000文字まで）")
async def broadcast(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str,
):
    await interaction.response.defer(ephemeral=True)
    if not _in_commands_channel(interaction):
        await interaction.followup.send(
            f"このコマンドは `#{COMMANDS_CHANNEL_NAME}` で実行してください。",
            ephemeral=True,
        )
        return
    if not _is_admin(interaction):
        await interaction.followup.send("権限がありません。", ephemeral=True)
        return
    text = (message or "").strip()[:2000]
    if not text:
        await interaction.followup.send("本文が空です。", ephemeral=True)
        return
    await channel.send(text)
    await interaction.followup.send(f"{channel.mention} に投稿しました。", ephemeral=True)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")


def main():
    s = get_settings()
    client.run(s.discord_bot_token)


if __name__ == "__main__":
    main()

