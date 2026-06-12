"""Pure logic for the offloaded analytics-event store (content_visible /
content_exposure).

The Flutter app offloads these high-frequency event types to gzipped JSONL
objects in Cloud Storage instead of one Firestore doc each (see
upload_service.syncContentEvents). On export we read those objects back and
merge them into events.json so the researcher view is complete.

This module is the *pure* part — gzip/JSON decoding, time-window filtering, and
id-deduped merging — kept free of any Firebase/GCS/FastAPI imports so it can be
unit-tested standalone (main.py needs the full venv to import). main.py owns the
GCS I/O (list_blobs / download_as_bytes(raw_download=True)) and delegates the
parsing here.
"""
import gzip
import json
from datetime import datetime


def parse_jsonl_gz(raw_bytes):
    """Decode one gzipped-JSONL content-event object into a list of event dicts.

    `raw_bytes` MUST be the stored gzip bytes. When reading from GCS, use
    download_as_bytes(raw_download=True) — a plain download would decompressively
    transcode objects that carry Content-Encoding: gzip and break this decode.

    Tolerant by design: a malformed object/line is skipped rather than aborting
    an export. Returns [] if the whole object can't be decompressed.
    """
    try:
        text = gzip.decompress(raw_bytes).decode("utf-8")
    except Exception:
        return []

    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def _parse_event_ts(ev):
    """Return the event's timestamp as a naive (tz-stripped, UTC) datetime, or
    None if absent/unparseable. The app writes UTC ISO-8601."""
    ts_raw = ev.get("timestamp")
    if not isinstance(ts_raw, str):
        return None
    try:
        dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def event_in_window(ev, start_dt=None, end_dt=None):
    """True if event falls in [start_dt, end_dt). Matches the Firestore events
    query bounds (>= start, < end). An event with no/unparseable timestamp is
    INCLUDED when a window is set (better to over-include research data than to
    silently drop it)."""
    if not start_dt and not end_dt:
        return True
    dt = _parse_event_ts(ev)
    if dt is None:
        return True
    if start_dt and dt < start_dt:
        return False
    if end_dt and dt >= end_dt:
        return False
    return True


def merge_content_events(events_data, content_events):
    """Append content_events to events_data, de-duplicating by id against what's
    already present (legacy Firestore copies during the migration window).
    Mutates and returns events_data."""
    existing_ids = {e.get("id") for e in events_data}
    for ev in content_events:
        eid = ev.get("id")
        if eid in existing_ids:
            continue
        events_data.append(ev)
        existing_ids.add(eid)
    return events_data
