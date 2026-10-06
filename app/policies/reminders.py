from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")


def next_morning(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Reminder clock must be timezone-aware")
    local = now.astimezone(TEHRAN)
    candidate = datetime.combine(local.date(), time(10), TEHRAN)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def reminder_due(scheduled: datetime, now: datetime) -> bool:
    local = now.astimezone(TEHRAN)
    return scheduled.astimezone(TEHRAN).date() == local.date() and local >= scheduled
