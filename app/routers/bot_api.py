from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.core.config import get_settings
from app.services.sheet_client import get_sheet_client
import json
import secrets

from app.services.sheet_schemas import (
    SheetName,
    MembersColumns,
    EventsColumns,
    BotCommandLogsColumns,
    AiActionLogsColumns,
    get_headers,
)
from app.services.sheet_utils import dict_to_row


router = APIRouter(prefix="/bot", tags=["bot"])


def _require_bot_secret(x_bot_secret: str | None) -> None:
    settings = get_settings()
    if not settings.gas_webhook_secret:
        # 既存の設定を流用せず、bot 用 secret は別途追加してもよいが、ここでは簡易に共通 secret で扱う
        pass
    expected = (settings.gas_webhook_secret or "").strip()
    if not expected or not x_bot_secret or x_bot_secret.strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _log_command(actor_discord_user_id: str, command: str, payload: dict[str, Any], result: str) -> None:
    client = get_sheet_client()
    now = datetime.now(timezone.utc).isoformat()
    values = {
        BotCommandLogsColumns.LOG_ID: f"log_{secrets.token_hex(8)}",
        BotCommandLogsColumns.EXECUTED_AT: now,
        BotCommandLogsColumns.ACTOR_DISCORD_USER_ID: actor_discord_user_id,
        BotCommandLogsColumns.COMMAND: command,
        BotCommandLogsColumns.PAYLOAD_JSON: json.dumps(payload, ensure_ascii=False),
        BotCommandLogsColumns.RESULT: result,
    }
    client.append_row(SheetName.BOT_COMMAND_LOGS, dict_to_row(get_headers(SheetName.BOT_COMMAND_LOGS), values))


@router.post("/sync-member-roles")
async def sync_member_roles(payload: dict[str, Any], x_bot_secret: str | None = Header(default=None)):
    _require_bot_secret(x_bot_secret)
    member_id = str(payload.get("member_id", "")).strip()
    actor = str(payload.get("actor_discord_user_id", "")).strip()
    if not member_id:
        raise HTTPException(status_code=400, detail="member_id is required")

    client = get_sheet_client()
    records = client.get_all_records(SheetName.MEMBERS)
    for rec in records:
        if str(rec.get(MembersColumns.MEMBER_ID, "")).strip() != member_id:
            continue
        teams = str(rec.get(MembersColumns.TEAMS, "") or "")
        roles = str(rec.get(MembersColumns.ROLES, "") or "")
        role_names: list[str] = []
        for t in [x.strip() for x in teams.split(",") if x.strip()]:
            if t == "すまい":
                role_names.append("Team_Sumai")
            if t == "PC":
                role_names.append("Team_PC")
            if t == "提案":
                role_names.append("Team_Teian")
            if t == "キャリア":
                role_names.append("Team_Career")
        for r in [x.strip() for x in roles.split(",") if x.strip()]:
            if r.lower() == "leader":
                role_names.append("Role_Leader")
            if r.lower() == "subleader":
                role_names.append("Role_SubLeader")
            if r.lower() == "chief":
                role_names.append("Role_Chief")
            if r.lower() == "member":
                role_names.append("Role_Member")

        res = {
            "member_id": member_id,
            "discord_user_id": rec.get(MembersColumns.DISCORD_USER_ID, ""),
            "role_names": sorted(set(role_names)),
        }
        _log_command(actor, "sync-member-roles", payload, "ok")
        return res
    _log_command(actor, "sync-member-roles", payload, "not_found")
    raise HTTPException(status_code=404, detail="member not found")


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "event"


@router.post("/create-event-channel")
async def create_event_channel(payload: dict[str, Any], x_bot_secret: str | None = Header(default=None)):
    _require_bot_secret(x_bot_secret)
    event_id = str(payload.get("event_id", "")).strip()
    actor = str(payload.get("actor_discord_user_id", "")).strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="event_id is required")

    client = get_sheet_client()
    events = client.get_all_records(SheetName.EVENTS)
    for ev in events:
        if str(ev.get(EventsColumns.EVENT_ID, "")) != event_id:
            continue
        date = str(ev.get(EventsColumns.DATE, "")).replace("-", "")
        start = str(ev.get(EventsColumns.START_TIME, "")).replace(":", "")
        slug = _slugify(str(ev.get(EventsColumns.NAME, "")))
        res = {"channel_name": f"event-{date}-{start}-{slug}"}
        _log_command(actor, "create-event-channel", payload, "ok")
        return res
    _log_command(actor, "create-event-channel", payload, "not_found")
    raise HTTPException(status_code=404, detail="event not found")


@router.post("/create-group-channel")
async def create_group_channel(payload: dict[str, Any], x_bot_secret: str | None = Header(default=None)):
    _require_bot_secret(x_bot_secret)
    group_name = str(payload.get("group_name", "")).strip()
    actor = str(payload.get("actor_discord_user_id", "")).strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="group_name is required")
    slug = _slugify(group_name)
    res = {"channel_name": f"group-{slug}"}
    _log_command(actor, "create-group-channel", payload, "ok")
    return res


@router.post("/ai/propose")
async def ai_propose(payload: dict[str, Any], x_bot_secret: str | None = Header(default=None)):
    _require_bot_secret(x_bot_secret)
    requested_by = str(payload.get("requested_by", "")).strip()
    command = str(payload.get("command", "")).strip()
    target = str(payload.get("target", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    action_id = f"act_{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).isoformat()
    values = {
        AiActionLogsColumns.ACTION_ID: action_id,
        AiActionLogsColumns.REQUESTED_BY: requested_by,
        AiActionLogsColumns.PROPOSED_BY: "ai",
        AiActionLogsColumns.APPROVED_BY: "",
        AiActionLogsColumns.EXECUTED_AT: "",
        AiActionLogsColumns.COMMAND: command,
        AiActionLogsColumns.TARGET: target,
        AiActionLogsColumns.STATUS: "proposed",
        AiActionLogsColumns.CREATED_AT: now,
    }
    client = get_sheet_client()
    client.append_row(SheetName.AI_ACTION_LOGS, dict_to_row(get_headers(SheetName.AI_ACTION_LOGS), values))
    _log_command(requested_by, "ai-propose", payload, "ok")
    return {"action_id": action_id}


@router.post("/ai/approve")
async def ai_approve(payload: dict[str, Any], x_bot_secret: str | None = Header(default=None)):
    _require_bot_secret(x_bot_secret)
    action_id = str(payload.get("action_id", "")).strip()
    approved_by = str(payload.get("approved_by", "")).strip()
    if not action_id:
        raise HTTPException(status_code=400, detail="action_id is required")

    client = get_sheet_client()
    records = client.get_all_records(SheetName.AI_ACTION_LOGS)
    row_idx = None
    rec = None
    for idx, r in enumerate(records, start=2):
        if str(r.get(AiActionLogsColumns.ACTION_ID, "")) == action_id:
            row_idx = idx
            rec = r
            break
    if not row_idx or rec is None:
        raise HTTPException(status_code=404, detail="action not found")

    now = datetime.now(timezone.utc).isoformat()
    rec2 = dict(rec)
    rec2[AiActionLogsColumns.APPROVED_BY] = approved_by
    rec2[AiActionLogsColumns.STATUS] = "approved"
    client.update_row(SheetName.AI_ACTION_LOGS, row_idx, dict_to_row(get_headers(SheetName.AI_ACTION_LOGS), rec2))
    _log_command(approved_by, "ai-approve", payload, "ok")
    return {"ok": True}

