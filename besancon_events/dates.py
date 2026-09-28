"""Analyse de dates tolérante (ISO 8601, dates seules, formats français)."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

_FR_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2})[h:](\d{2})?)?$")


def parse_date(value) -> datetime | None:
    """Retourne un datetime avec fuseau (Europe/Paris par défaut) ou None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=PARIS)
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=PARIS)
    text = str(value).strip()
    m = _FR_DATE.match(text)
    if m:
        d, mo, y, h, mi = m.groups()
        return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), tzinfo=PARIS)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=PARIS)
