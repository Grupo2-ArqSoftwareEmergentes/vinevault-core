"""Connection freshness is independent of RSSI and device-local Wi-Fi labels."""
from datetime import datetime, timedelta, timezone

ONLINE_WINDOW = timedelta(minutes=5)
POWER_STATE_KEY = "control.power_state"
POWER_CHANGED_AT_KEY = "control.power_changed_at"


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def activity_time(value: datetime | None, now: datetime | None = None) -> datetime:
    # A bad device clock must not keep a sensor online indefinitely.
    current = utc(now) or datetime.now(timezone.utc)
    return min(utc(value) or current, current)
