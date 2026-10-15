"""Resolve a REDCap record_id to an app participant id — safely.

Why this exists (incident 2026-10-14): a staff test record was auto-numbered
389, qualified (mapping 389 -> app id written), then RENAMED to a custom name.
REDCap auto-numbering is max+1, so the next real survey respondent became
record 389. Her screener DET hit the stale `redcap_mappings/389` on an
unverified fast path, was filed under the staff member's participant, and the
crisis SMS went to the staff member's phone.

Rule: a stored mapping is a cache, not the truth. The truth is the
`socialscope_app_id` field written INTO the REDCap record at qualification —
it survives renames and is empty on a fresh record. Every resolution checks it:

  record app-id == mapping        -> use it
  record app-id empty / different -> mapping is STALE: mark superseded, never use
  no mapping, record has app-id   -> adopt it (rename repair) if participant exists
  no mapping, no app-id           -> unresolved (pre-qualify record)

If REDCap cannot be reached the mapping is NOT trusted either: a wrong
participant is worse than a dropped sync (the sync is retried by the
post-qualify backfill; a misrouted crisis alert is not undone).
"""
from datetime import datetime
from typing import Callable, Optional

MAPPING_SUPERSEDED_FIELD = "superseded_at"


def decide(mapping_pid: Optional[str], record_app_id: Optional[str],
           lookup_ok: bool) -> tuple:
    """Pure decision table. Returns (participant_id_or_None, action) where action is
    one of: 'mapping_verified', 'adopted_from_record', 'stale_mapping',
    'unresolved', 'lookup_failed'."""
    mapping_pid = (mapping_pid or "").strip() or None
    record_app_id = (record_app_id or "").strip() or None
    if not lookup_ok:
        return None, "lookup_failed"
    if record_app_id:
        if mapping_pid == record_app_id:
            return record_app_id, "mapping_verified"
        return record_app_id, "adopted_from_record" if not mapping_pid else "stale_mapping"
    if mapping_pid:
        return None, "stale_mapping"
    return None, "unresolved"


def resolve_participant_for_record(
    record_id: str,
    *,
    db,
    mappings_collection: str,
    participants_collection: str,
    fetch_record_app_id: Callable[[str], Optional[str]],
    logger,
    now: Optional[datetime] = None,
    event_name: Optional[str] = None,
) -> Optional[str]:
    """Resolve `record_id` to a participant id, or None.

    `fetch_record_app_id(record_id)` returns the record's app-id field ('' if
    empty) or raises on transport failure.
    """
    now = now or datetime.utcnow()
    mapping_ref = db.collection(mappings_collection).document(record_id)
    mapping = mapping_ref.get()
    mapping_data = (mapping.to_dict() or {}) if mapping.exists else {}
    mapping_pid = mapping_data.get("app_participant_id")
    already_superseded = mapping_data.get(MAPPING_SUPERSEDED_FIELD) is not None

    try:
        record_app_id = fetch_record_app_id(record_id)
        lookup_ok = True
    except Exception as e:  # transport / API failure
        record_app_id, lookup_ok = None, False
        logger.error(f"[REDCap DET] app-id lookup failed for record {record_id!r}: {e}")

    pid, action = decide(None if already_superseded else mapping_pid, record_app_id, lookup_ok)

    if action == "lookup_failed":
        logger.error(
            f"[REDCap DET] record {record_id!r}: cannot verify mapping "
            f"({'-> ' + str(mapping_pid) if mapping_pid else 'none'}) — NOT trusting it; save dropped")
        return None

    if action == "stale_mapping":
        # The record no longer carries the app id this mapping claims — it was
        # renamed and its number reused, or re-pointed. Keep the doc as history,
        # but it must never answer again.
        logger.error(
            f"[REDCap DET] STALE MAPPING record {record_id!r} -> {mapping_pid}: "
            f"record's app id is {record_app_id!r}. Marking superseded.")
        try:
            mapping_ref.set({MAPPING_SUPERSEDED_FIELD: now,
                             "superseded_reason": f"record app id is {record_app_id!r}",
                             "superseded_app_participant_id": mapping_pid}, merge=True)
        except Exception as e:
            logger.error(f"[REDCap DET] could not mark mapping {record_id!r} superseded: {e}")
        if not pid:
            return None
        # fall through: the record names a different, real participant

    if action == "unresolved":
        return None

    # 'mapping_verified' or 'adopted_from_record' (or stale + record names another pid)
    p_ref = db.collection(participants_collection).document(pid)
    if not p_ref.get().exists:
        logger.warning(f"[REDCap DET] record {record_id!r} names app id {pid}, but no participant doc")
        return None

    if action != "mapping_verified":
        try:
            mapping_ref.set({
                "app_participant_id": pid,
                "redcap_event": event_name,
                "created_at": now,
                "repaired_from_app_id_lookup": True,
                MAPPING_SUPERSEDED_FIELD: None,
                "superseded_reason": None,
            }, merge=True)
            p_ref.set({"redcapRecordId": record_id}, merge=True)
            logger.info(f"[REDCap DET] Adopted mapping: record {record_id!r} -> participant {pid}")
        except Exception as e:
            logger.error(f"[REDCap DET] mapping repair failed for {record_id!r}: {e}")
    return pid


def mapping_reusable_at_qualify(mapping_data: Optional[dict], this_record_id: str,
                                live_record_for_pid: Optional[str]) -> Optional[str]:
    """At qualification the DET calls us only when the record's app-id field is
    EMPTY. A cached mapping may then be reused ("self-heal" after a failed
    write-back) — but only if nothing says it belongs to another record.

    Returns the app id to reuse, or None (generate a fresh id).
      - no mapping / superseded mapping          -> None
      - the mapped participant's app id is found on a DIFFERENT REDCap record
        (the record was renamed; this number was reused)   -> None
      - otherwise (no live record found, or it is this one) -> reuse
    """
    if not mapping_data or mapping_data.get(MAPPING_SUPERSEDED_FIELD) is not None:
        return None
    pid = (mapping_data.get("app_participant_id") or "").strip()
    if not pid:
        return None
    if live_record_for_pid and str(live_record_for_pid) != str(this_record_id):
        return None
    return pid
