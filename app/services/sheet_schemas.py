from enum import Enum
from dataclasses import dataclass
from typing import Final, List


class SheetName(str, Enum):
    MEMBERS = "members"
    EMAIL_VERIFICATIONS = "email_verifications"
    EVENTS = "events"
    ATTENDANCES = "attendances"
    ATTENDANCE_CHANGES = "attendance_changes"
    BUSY_PREFERENCES = "busy_preferences"
    BOT_COMMAND_LOGS = "bot_command_logs"
    AI_ACTION_LOGS = "ai_action_logs"
    NOTIFICATIONS_LOG = "notifications_log"


@dataclass(frozen=True)
class NotificationsLogColumns:
    LOG_ID: str = "log_id"
    TYPE: str = "type"
    TARGET_IDS: str = "target_ids"
    TRIGGERED_BY: str = "triggered_by"
    SUBJECT: str = "subject"
    STATUS: str = "status"
    DETAIL: str = "detail"
    CREATED_AT: str = "created_at"


@dataclass(frozen=True)
class MembersColumns:
    # 物理キー系
    MEMBER_ID: str = "member_id"
    FULL_NAME: str = "full_name"
    STUDENT_ID: str = "student_id"
    EMAIL: str = "email"
    FACULTY_CODE: str = "faculty_code"
    ENTRANCE_YEAR: str = "entrance_year"
    GRADE: str = "grade"
    DISCORD_USER_ID: str = "discord_user_id"
    DISCORD_USERNAME: str = "discord_username"
    TEAMS: str = "teams"
    ROLES: str = "roles"
    STATUS: str = "status"
    EMAIL_VERIFIED: str = "email_verified"
    EMAIL_VERIFIED_AT: str = "email_verified_at"
    MERGE_TARGET_MEMBER_ID: str = "merge_target_member_id"
    APPROVED_BY: str = "approved_by"
    APPROVED_AT: str = "approved_at"
    CREATED_AT: str = "created_at"
    LAST_LOGIN_AT: str = "last_login_at"
    UPDATED_AT: str = "updated_at"
    NOTIFY_OPTOUT: str = "notify_optout"


@dataclass(frozen=True)
class EmailVerificationsColumns:
    VERIFICATION_ID: str = "verification_id"
    MEMBER_ID: str = "member_id"
    EMAIL: str = "email"
    CODE_HASH: str = "code_hash"
    EXPIRES_AT: str = "expires_at"
    ATTEMPT_COUNT: str = "attempt_count"
    VERIFIED_AT: str = "verified_at"
    CREATED_AT: str = "created_at"


@dataclass(frozen=True)
class EventsColumns:
    EVENT_ID: str = "event_id"
    DATE: str = "date"
    START_TIME: str = "start_time"
    END_TIME: str = "end_time"
    NAME: str = "name"
    REQUIRED_MEMBERS: str = "required_members"
    TARGET_TEAMS: str = "target_teams"
    IS_BUSY_SEASON: str = "is_busy_season"
    CONFIRMED: str = "confirmed"
    UPDATED_AT: str = "updated_at"


@dataclass(frozen=True)
class AttendancesColumns:
    ATTENDANCE_ID: str = "attendance_id"
    EVENT_ID: str = "event_id"
    MEMBER_ID: str = "member_id"
    ROLE: str = "role"
    STATUS: str = "status"
    NOTE: str = "note"
    UPDATED_AT: str = "updated_at"


@dataclass(frozen=True)
class AttendanceChangesColumns:
    CHANGE_ID: str = "change_id"
    CHANGED_AT: str = "changed_at"
    EVENT_ID: str = "event_id"
    MEMBER_ID: str = "member_id"
    ATTENDANCE_ID: str = "attendance_id"
    CHANGE_TYPE: str = "change_type"
    REASON: str = "reason"
    SOURCE: str = "source"


@dataclass(frozen=True)
class BusyPreferencesColumns:
    MEMBER_ID: str = "member_id"
    MEMBER_NAME: str = "member_name"
    EVENT_ID: str = "event_id"
    PREFERRED_ROLE: str = "preferred_role"
    PRIORITY: str = "priority"
    MAX_SHIFTS: str = "max_shifts"
    NOTE: str = "note"
    CREATED_AT: str = "created_at"
    UPDATED_AT: str = "updated_at"


@dataclass(frozen=True)
class BotCommandLogsColumns:
    LOG_ID: str = "log_id"
    EXECUTED_AT: str = "executed_at"
    ACTOR_DISCORD_USER_ID: str = "actor_discord_user_id"
    COMMAND: str = "command"
    PAYLOAD_JSON: str = "payload_json"
    RESULT: str = "result"


@dataclass(frozen=True)
class AiActionLogsColumns:
    ACTION_ID: str = "action_id"
    REQUESTED_BY: str = "requested_by"
    PROPOSED_BY: str = "proposed_by"
    APPROVED_BY: str = "approved_by"
    EXECUTED_AT: str = "executed_at"
    COMMAND: str = "command"
    TARGET: str = "target"
    STATUS: str = "status"  # proposed/approved/rejected/executed
    CREATED_AT: str = "created_at"


def get_headers(sheet: SheetName) -> List[str]:
    """各シートのヘッダー行を返すヘルパー。シート作成スクリプトなどから利用する。"""
    if sheet == SheetName.MEMBERS:
        return list(MembersColumns().__dict__.values())
    if sheet == SheetName.EMAIL_VERIFICATIONS:
        return list(EmailVerificationsColumns().__dict__.values())
    if sheet == SheetName.EVENTS:
        return list(EventsColumns().__dict__.values())
    if sheet == SheetName.ATTENDANCES:
        return list(AttendancesColumns().__dict__.values())
    if sheet == SheetName.ATTENDANCE_CHANGES:
        return list(AttendanceChangesColumns().__dict__.values())
    if sheet == SheetName.BUSY_PREFERENCES:
        return list(BusyPreferencesColumns().__dict__.values())
    if sheet == SheetName.BOT_COMMAND_LOGS:
        return list(BotCommandLogsColumns().__dict__.values())
    if sheet == SheetName.AI_ACTION_LOGS:
        return list(AiActionLogsColumns().__dict__.values())
    if sheet == SheetName.NOTIFICATIONS_LOG:
        return list(NotificationsLogColumns().__dict__.values())
    raise ValueError(f"Unsupported sheet: {sheet}")


ALL_SHEETS: Final[list[SheetName]] = [
    SheetName.MEMBERS,
    SheetName.EMAIL_VERIFICATIONS,
    SheetName.EVENTS,
    SheetName.ATTENDANCES,
    SheetName.ATTENDANCE_CHANGES,
    SheetName.BUSY_PREFERENCES,
    SheetName.BOT_COMMAND_LOGS,
    SheetName.AI_ACTION_LOGS,
    SheetName.NOTIFICATIONS_LOG,
]


