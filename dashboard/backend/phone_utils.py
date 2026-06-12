"""Phone-number normalization for participant matching.

Single source of truth for the canonical digits-only form used to match an
inbound SMS/voice number against stored participant phones. Previously this
logic was duplicated as three slightly-different inline `.replace()` chains in
main.py; divergence there risked a participant's "ERROR" reply not matching and
escalation continuing. Keep all matching normalization here.
"""


def normalize_phone(raw) -> str:
    """Return the canonical 10-digit form: digits only, US country code stripped.

    Examples:
      "(603) 555-1234"   -> "6035551234"
      "+1 603-555-1234"  -> "6035551234"
      "16035551234"      -> "6035551234"
      "603.555.1234"     -> "6035551234"
      None / ""          -> ""
    """
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def phones_match(a, b) -> bool:
    """True if two phone numbers refer to the same line after normalization.
    Both must be non-empty (an empty/unparseable number matches nothing)."""
    na, nb = normalize_phone(a), normalize_phone(b)
    return bool(na) and na == nb
