"""Study-personnel notes on a participant, plus the REDCap reminder switchboard.

Notes live in `participants/{id}/staff_notes/{noteId}` — a subcollection with no
Firestore rule, so it is Admin-SDK-only and the app can never read or write it.

Nothing here deletes. Editing a note appends the previous text to `revisions`
rather than overwriting it, so the record of what a coordinator knew and when is
preserved. Retiring a note archives it (it stays queryable, just hidden by
default in the UI).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from redcap_weekly import fetch_reminders, summarize_reminders

logger = logging.getLogger(__name__)

MAX_NOTE_LENGTH = 20000
MAX_REVISIONS = 50
NOTES_SUBCOLLECTION = "staff_notes"

# Free text is the point, but a category makes a long note list scannable.
NOTE_CATEGORIES = ("general", "contact", "clinical", "technical", "scheduling")
DEFAULT_CATEGORY = "general"


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_NOTE_LENGTH)
    category: Optional[str] = None
    pinned: Optional[bool] = None


class NoteUpdateRequest(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=MAX_NOTE_LENGTH)
    category: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


def _iso(value: Any) -> Optional[str]:
    """Firestore timestamps, datetimes and ISO strings all end up as UTC ISO strings.

    Firestore hands back a tz-aware `DatetimeWithNanoseconds` (a datetime
    subclass), while a value that never round-tripped is the naive UTC datetime
    we wrote. Check `isinstance` before `.timestamp()`, or the naive one gets
    shifted by the server's local offset.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat() + "Z"
    if hasattr(value, "timestamp"):
        try:
            return datetime.utcfromtimestamp(value.timestamp()).isoformat() + "Z"
        except Exception:
            return None
    return str(value)


def _normalize_category(value: Optional[str]) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in NOTE_CATEGORIES else DEFAULT_CATEGORY


def _author(user: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "email": user.get("email"),
        "name": user.get("name") or user.get("displayName") or user.get("email"),
    }


def serialize_note(doc) -> Dict[str, Any]:
    data = doc.to_dict() or {}
    revisions = data.get("revisions") or []
    return {
        "id": doc.id,
        "text": data.get("text", ""),
        "category": data.get("category", DEFAULT_CATEGORY),
        "pinned": bool(data.get("pinned")),
        "archived": bool(data.get("archived")),
        "createdAt": _iso(data.get("createdAt")),
        "createdBy": data.get("createdBy"),
        "createdByName": data.get("createdByName"),
        "updatedAt": _iso(data.get("updatedAt")),
        "updatedBy": data.get("updatedBy"),
        "updatedByName": data.get("updatedByName"),
        "revisionCount": len(revisions),
        "revisions": [
            {
                "text": r.get("text", ""),
                "editedAt": _iso(r.get("editedAt")),
                "editedBy": r.get("editedBy"),
            }
            for r in revisions
        ],
    }


def _sort_key(iso_value: Optional[str]) -> float:
    if not iso_value:
        return 0.0
    try:
        return datetime.strptime(iso_value[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except ValueError:
        return 0.0


def sort_notes(notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pinned first, then newest first. Notes missing a timestamp sort last."""
    return sorted(
        notes,
        key=lambda n: (0 if n.get("pinned") else 1, -_sort_key(n.get("createdAt"))),
    )


def register_staff_notes_routes(app, db, limiter, verify_firebase_token, config,
                                logger, redcap_record_id_for_participant):
    """Register the participant notes API routes on the FastAPI app."""

    def _notes_ref(participant_id: str):
        return (db.collection(config.col("participants"))
                  .document(participant_id)
                  .collection(NOTES_SUBCOLLECTION))

    def _redcap_reminders(participant_id: str) -> Dict[str, Any]:
        """Reminder switchboard from REDCap; degrades instead of failing the page."""
        record_id = redcap_record_id_for_participant(participant_id)
        if not record_id:
            payload = summarize_reminders(None)
            payload.update(available=False,
                           reason="No REDCap record mapped to this participant")
            return payload
        try:
            payload = fetch_reminders(record_id)
            payload.update(available=True, redcapRecordId=record_id)
            return payload
        except Exception as e:
            logger.warning(f"[Notes] REDCap reminders lookup failed for {participant_id}: {e}")
            payload = summarize_reminders(None)
            payload.update(available=False, reason=str(e), redcapRecordId=record_id)
            return payload

    @app.get("/api/participant/{participant_id}/notes")
    @limiter.limit("60/minute")
    def list_participant_notes(
        request: Request,
        participant_id: str,
        include_archived: bool = Query(False),
        user: dict = Depends(verify_firebase_token),
    ):
        """Staff notes for a participant, alongside their REDCap reminder status."""
        try:
            notes = [serialize_note(doc) for doc in _notes_ref(participant_id).stream()]
            if not include_archived:
                notes = [n for n in notes if not n["archived"]]
            return {
                "participantId": participant_id,
                "notes": sort_notes(notes),
                "categories": list(NOTE_CATEGORIES),
                "reminders": _redcap_reminders(participant_id),
            }
        except Exception as e:
            logger.error(f"[Notes] Failed to list notes for {participant_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/participant/{participant_id}/notes")
    @limiter.limit("30/minute")
    def create_participant_note(
        request: Request,
        participant_id: str,
        body: NoteRequest,
        user: dict = Depends(verify_firebase_token),
    ):
        """Add a note. Authorship is taken from the signed-in dashboard user."""
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Note text is required")

        author = _author(user)
        now = datetime.utcnow()
        try:
            doc_ref = _notes_ref(participant_id).document()
            doc_ref.set({
                "text": text,
                "category": _normalize_category(body.category),
                "pinned": bool(body.pinned),
                "archived": False,
                "createdAt": now,
                "createdBy": author["email"],
                "createdByName": author["name"],
                "updatedAt": now,
                "updatedBy": author["email"],
                "updatedByName": author["name"],
                "revisions": [],
            })
            logger.info(f"[Notes] {author['email']} added a note to {participant_id}")
            return {"success": True, "note": serialize_note(doc_ref.get())}
        except Exception as e:
            logger.error(f"[Notes] Failed to create note for {participant_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.put("/api/participant/{participant_id}/notes/{note_id}")
    @limiter.limit("30/minute")
    def update_participant_note(
        request: Request,
        participant_id: str,
        note_id: str,
        body: NoteUpdateRequest,
        user: dict = Depends(verify_firebase_token),
    ):
        """Edit a note. The previous text is kept as a revision, never discarded."""
        author = _author(user)
        try:
            doc_ref = _notes_ref(participant_id).document(note_id)
            snapshot = doc_ref.get()
            if not snapshot.exists:
                raise HTTPException(status_code=404, detail="Note not found")

            existing = snapshot.to_dict() or {}
            updates: Dict[str, Any] = {}

            if body.text is not None:
                text = body.text.strip()
                if not text:
                    raise HTTPException(status_code=400, detail="Note text cannot be empty")
                if text != existing.get("text"):
                    revisions = list(existing.get("revisions") or [])
                    revisions.append({
                        "text": existing.get("text", ""),
                        "editedAt": datetime.utcnow(),
                        "editedBy": author["email"],
                    })
                    # Keep the most recent revisions; nothing is ever deleted
                    # outright, but an unbounded array would eventually blow the
                    # 1 MiB document limit and make the note unwritable.
                    updates["revisions"] = revisions[-MAX_REVISIONS:]
                    updates["text"] = text

            if body.category is not None:
                updates["category"] = _normalize_category(body.category)
            if body.pinned is not None:
                updates["pinned"] = bool(body.pinned)
            if body.archived is not None:
                updates["archived"] = bool(body.archived)

            if not updates:
                return {"success": True, "note": serialize_note(snapshot), "unchanged": True}

            updates["updatedAt"] = datetime.utcnow()
            updates["updatedBy"] = author["email"]
            updates["updatedByName"] = author["name"]
            doc_ref.update(updates)

            logger.info(f"[Notes] {author['email']} edited note {note_id} on {participant_id}")
            return {"success": True, "note": serialize_note(doc_ref.get())}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Notes] Failed to update note {note_id} for {participant_id}: {e}",
                         exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
