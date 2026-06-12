"""Pure helpers for the data-export endpoints.

Kept import-free (no FastAPI/Firebase) so the security-relevant validation can be
unit-tested standalone, matching the phone_utils / content_events pattern.
"""
import re

# Every export/job id in this codebase is uuid4().hex — exactly 32 hex chars.
# The id arrives as a URL path param and is interpolated into a filesystem path
# (EXPORT_DIR / f"{export_id}.zip"), so it MUST be validated before use or a
# value like "..%2f..%2fsecret" becomes a path-traversal read.
_EXPORT_ID_RE = re.compile(r"\A[0-9a-fA-F]{32}\Z")


def is_valid_export_id(export_id) -> bool:
    """True only for a canonical 32-char hex export/job id. Rejects anything with
    path separators, dots, or unexpected length — i.e. anything traversal-shaped."""
    return isinstance(export_id, str) and bool(_EXPORT_ID_RE.match(export_id))
