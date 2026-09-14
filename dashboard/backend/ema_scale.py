"""Scale handling for the EMA "ability to keep yourself safe" item.

Pure logic, deliberately free of FastAPI/Firestore imports so it can be unit
tested directly — this is the code that decides whether a suicide-risk answer
counts as dangerous, so it needs tests that actually run.

Background: "How able are you to keep yourself safe right now?" originally ran
0 = Not at all able to 100 = Completely able, so a LOW score meant HIGH risk —
the opposite of every other slider, which made it easy to answer backwards. The
anchors were reversed mid-study (0 = Completely, 100 = Not at all) so that higher
always means riskier.

Participants update at different times, so the scale is NEVER inferred from a
date. Each response records the scale it was collected on; anything without the
marker predates the change and is read on the ORIGINAL scale, permanently.
"""

ABILITY_SAFE_SCALE_KEY = "__ability_safe_scale"
ABILITY_SAFE_HIGH_IS_RISK = "high_is_risk"
ABILITY_SAFE_LOW_IS_RISK = "low_is_risk"

EMA_SAFETY_TRIGGER_FIELDS = [
    "desire_intensity", "intention_strength", "ability_safe", "thoughts_intent",
]
EMA_THRESHOLD = 30


def ability_safe_high_is_risk(responses) -> bool:
    """True when this response used the reversed (high = riskier) scale."""
    return (responses or {}).get(ABILITY_SAFE_SCALE_KEY) == ABILITY_SAFE_HIGH_IS_RISK


def ability_safe_risk_value(responses):
    """ability_safe in RISK units (higher = riskier) for this response's scale."""
    val = (responses or {}).get("ability_safe")
    if val is None:
        return None
    try:
        score = float(val)
    except (ValueError, TypeError):
        return None
    # Old scale: 100 = completely able = least risk, so invert into risk units.
    return score if ability_safe_high_is_risk(responses) else 100 - score


def ability_safe_exceeds(responses) -> bool:
    """Whether ability_safe crosses the safety threshold for this response."""
    risk = ability_safe_risk_value(responses)
    return risk is not None and risk >= EMA_THRESHOLD


def compute_ema_risk_score(responses) -> int:
    """Composite EMA risk score from the safety trigger fields (0-100)."""
    responses = responses or {}
    scores = []
    for field in EMA_SAFETY_TRIGGER_FIELDS:
        if field == "ability_safe":
            risk = ability_safe_risk_value(responses)
            if risk is not None:
                scores.append(risk)
            continue
        val = responses.get(field)
        if val is not None:
            try:
                scores.append(float(val))
            except (ValueError, TypeError):
                pass
    return int(max(scores)) if scores else 0


def build_ability_safe_note(checkins) -> str:
    """Provenance note for a participant's data download.

    States WHEN this participant's "ability to keep yourself safe" answers
    switched scale, and on which app version, so nobody analysing the export can
    silently mix the two directions. The stored values are never altered — the
    note explains how to read them.

    `checkins` is a list of exported EMA response dicts (each with `responses`
    and `completedAt`).
    """
    old, new = [], []
    for c in checkins or []:
        r = c.get("responses")
        if not isinstance(r, dict) or r.get("ability_safe") is None:
            continue
        when = str(c.get("completedAt") or "")[:19]
        entry = (when, r.get("__app_version") or "unknown")
        (new if ability_safe_high_is_risk(r) else old).append(entry)

    if not old and not new:
        return ""

    lines = [
        "SCALE CHANGE NOTE - EMA item: ability_safe",
        '  Question: "How able are you to keep yourself safe right now?"',
        "",
        "  This item's slider direction was REVERSED during the study so that a",
        "  higher number always means higher risk, consistent with every other",
        "  slider. Stored values were NOT modified. Read each response using the",
        "  scale recorded on it (responses.__ability_safe_scale).",
        "",
        "    low_is_risk  (original) : 0 = Not at all able ... 100 = Completely able",
        "                              -> LOWER values indicate GREATER risk",
        "    high_is_risk (current)  : 0 = Completely able ... 100 = Not at all able",
        "                              -> HIGHER values indicate GREATER risk",
        "",
        "  To pool across the change, convert original-scale values to risk units:",
        "      risk = 100 - ability_safe      (low_is_risk responses only)",
        "",
    ]
    if old:
        lines.append(f"  Responses on the ORIGINAL scale : {len(old)}")
        lines.append(f"      first {old[0][0]}   last {old[-1][0]}")
    if new:
        first_new, first_ver = sorted(new)[0]
        lines.append(f"  Responses on the REVERSED scale : {len(new)}")
        lines.append(f"      effective from {first_new} (app version {first_ver})")
    if old and not new:
        lines.append("  This participant has no responses on the reversed scale yet.")
    lines.append("")
    return "\n".join(lines)
