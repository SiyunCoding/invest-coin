"""시간 표시 유틸 (알림/대시보드 공용)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def kst_str(value: datetime | str | None = None, fmt: str = "%Y-%m-%d %H:%M KST") -> str:
    """UTC datetime 또는 ISO 문자열 → KST 문자열. None 이면 현재 시각, 빈 문자열이면 '—'."""
    if value == "":
        return "—"
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime(fmt)
