"""UTC-safe serialization of Firestore timestamps for API responses.

Firestore returns a tz-aware `DatetimeWithNanoseconds`; the codebase's habit was
`datetime.fromtimestamp(value.timestamp()).isoformat()`, which does two harmful
things at once: `fromtimestamp` converts to the SERVER's local zone (UTC on
Cloud Run), and the result is NAIVE, so `.isoformat()` emits a string with no
offset. A browser parses an offset-less ISO string as LOCAL time, so a
notification actually sent at 1:45 PM EDT rendered as "5:45 PM" — and because
the misparsed instant sits in the future, `Math.floor((now - then)/day)` went
negative and the relative label read "-1d ago".

`iso_utc` always returns an explicit UTC instant, which every JS `Date` parser
reads correctly.
"""

from datetime import datetime, timezone
from typing import Any, Optional


def iso_utc(value: Any) -> Optional[str]:
    """Render a timestamp as an explicit-UTC ISO 8601 string, or None.

    Accepts Firestore timestamps, aware/naive datetimes (naive is assumed UTC,
    which is what `datetime.utcnow()` writes), epoch numbers, and passes strings
    through untouched.
    """
    if value is None:
        return None

    # A Firestore DatetimeWithNanoseconds IS a datetime subclass, so check
    # isinstance BEFORE .timestamp() or a naive value gets shifted by the
    # server's local offset.
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat() + "Z"

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value).isoformat() + "Z"

    if hasattr(value, "timestamp"):
        try:
            return datetime.utcfromtimestamp(value.timestamp()).isoformat() + "Z"
        except Exception:
            return None

    return str(value)
