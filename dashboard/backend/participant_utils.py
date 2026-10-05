"""Pure helpers for reading a participant's study-start date.

A participant can have a document in BOTH `participants` and
`valid_participants`, holding different fields. Researcher edits
(studyStartDate, manualActiveStatus) are written to whichever collection the
write path finds first — and it checks `valid_participants` first — so every
read must give `valid_participants` the same precedence, or the edit silently
disappears.

That is exactly what went wrong in calculate_participant_compliance: it looped
valid_participants THEN participants, letting `participants.createdAt`
overwrite the researcher-set `valid_participants.studyStartDate`. The 3-day
cap masked it on most days, but on a participant's first study day it doubled
their expected check-ins and reported the day before enrollment as missed.

No FastAPI or Firestore imports here, so the precedence rules are unit tested.
`fetch_merged_participant` takes the db handle as a parameter.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, Optional


def merge_participant_docs(base: Optional[dict], overlay: Optional[dict]) -> dict:
    """Overlay wins for every key whose overlay value is not None."""
    merged = dict(base or {})
    for key, value in (overlay or {}).items():
        if value is not None:
            merged[key] = value
    return merged


def resolve_study_start(participant_data: Optional[dict], fallback: Any = None) -> Optional[datetime]:
    """Resolve a participant's study start date.

    A researcher-set `studyStartDate` always wins over the enrollment
    timestamp. Every read path must go through this helper: the dashboard
    cache used to derive the date from `enrolledAt` alone, so a manually
    edited date silently reverted on the next hourly cache rebuild.

    Uses datetime.fromtimestamp (server-local) to match the deployed dashboard
    exactly; Cloud Run runs in UTC, so it is UTC in production.
    """
    data = participant_data or {}
    for value in (data.get("studyStartDate"),
                  data.get("enrolledAt"),
                  data.get("lastEnrolledAt"),
                  fallback,
                  data.get("createdAt"),
                  data.get("created_at")):
        if not value:
            continue
        if hasattr(value, "timestamp"):
            return datetime.fromtimestamp(value.timestamp())
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                continue
    return None


def fetch_merged_participant(db, participant_id: str, collections: Iterable[str]) -> Optional[dict]:
    """Read the participant from each collection and merge them.

    `collections` is in LOW-to-HIGH precedence order: the LAST collection that
    has a document wins on every non-None field. Callers pass
    (participants, valid_participants) so researcher edits win.
    """
    merged: Optional[dict] = None
    for name in collections:
        doc = db.collection(name).document(participant_id).get()
        if doc.exists:
            merged = merge_participant_docs(merged, doc.to_dict() or {})
    return merged
