# C-SSRS REDCap Sync Module
# Handles fetching, transforming, and storing C-SSRS data from REDCap,
# and triggering crisis alerts when intent/planning/preparation questions are endorsed.

from datetime import datetime
import requests as http_requests

# REDCap instrument names
CSSRS_SCREEN_INSTRUMENT = "columbia_suicide_severity_rating_scale_cssrs_scree"
CSSRS_PEDIATRIC_INSTRUMENT = "columbia_suicide_severity_rating_scale_cssrs_pedia"

# C-SSRS Screen (Weekly) fields
CSSRS_SCREEN_FIELDS = [
    "cssrs_scr_1", "cssrs_scr_2", "cssrs_scr_3",
    "cssrs_scr_4", "cssrs_scr_5", "cssrs_scr_6",
    "cssrs_scr_6_last3m", "cssrs_scr_total",
]

# C-SSRS Pediatric (Interview) fields
CSSRS_PEDIATRIC_FIELDS = [
    "cssrs_ped_1", "cssrs_ped_1_describe",
    "cssrs_ped_2", "cssrs_ped_2_describe",
    "cssrs_ped_3", "cssrs_ped_3_describe",
    "cssrs_ped_4", "cssrs_ped_4_describe",
    "cssrs_ped_5", "cssrs_5_plan", "cssrs_ped_5_describe",
    "cssrs_ped_intensity", "cssrs_ped_intense_descrip", "cssrs_frequency",
    "cssrs_ped_6a", "cssrs_ped_6a_what", "cssrs_ped_6a_why", "cssrs_ped_6a_desc",
    "cssrs_ped_6a_total_attempt",
    "cssrs_ped_ns_sh", "cssrs_ped_sh_intentunknown",
    "cssrs_ped_6b", "cssrs_ped_6b_desc", "cssrs_ped_6b_total_attempt",
    "cssrs_ped_6c", "cssrs_ped_6c_desc", "cssrs_ped_6c_total_attempt",
    "cssrs_ped_6d", "cssrs_ped_6d_desc", "cssrs_ped_6d_total_attempt",
    "cssrs_ped_suicide_complete",
    "cssrs_ped_most_lethal_date",
    "cssrs_ped_lethal_medical", "cssrs_ped_potential_lethal",
]

# C-SSRS Screen question labels (for display)
CSSRS_SCREEN_LABELS = {
    "cssrs_scr_1": "1. Wish to be Dead",
    "cssrs_scr_2": "2. Non-Specific Active Suicidal Thoughts",
    "cssrs_scr_3": "3. Active Suicidal Ideation with Any Methods (Not Plan)",
    "cssrs_scr_4": "4. Active Suicidal Ideation with Some Intent to Act",
    "cssrs_scr_5": "5. Active Suicidal Ideation with Specific Plan and Intent",
    "cssrs_scr_6": "6. Suicidal Behavior (Lifetime)",
    "cssrs_scr_6_last3m": "6a. Suicidal Behavior (Past 3 Months)",
}

# Weekly C-SSRS questions 4 (intent), 5 (planning), 6 (behavior) trigger crisis alerts
CSSRS_CRISIS_TRIGGER_FIELDS = ["cssrs_scr_4", "cssrs_scr_5", "cssrs_scr_6"]


def _yn(val):
    """Convert REDCap yes/no (1/0) to Python bool."""
    if val == "1":
        return True
    if val == "0":
        return False
    return None


def _nonempty(val):
    """Return stripped string or None."""
    return val.strip() if val and val.strip() else None


def fetch_redcap_cssrs(record_id, instrument, event_name, config):
    """Fetch C-SSRS fields from REDCap for a given record."""
    fields = CSSRS_SCREEN_FIELDS if "scree" in instrument else CSSRS_PEDIATRIC_FIELDS
    data = {
        "token": config.REDCAP_API_TOKEN,
        "content": "record",
        "format": "json",
        "records[0]": record_id,
        "events[0]": event_name or config.REDCAP_TRIGGER_EVENT,
        "returnFormat": "json",
    }
    for i, f in enumerate(fields):
        data[f"fields[{i}]"] = f

    resp = http_requests.post(config.REDCAP_API_URL, data=data)
    if resp.status_code != 200:
        raise Exception(f"REDCap API error: {resp.status_code} {resp.text}")

    records = resp.json()
    if not records:
        raise Exception(f"No record found for record_id={record_id}")

    # Return the first record with populated fields
    for r in records:
        filled = {k: v for k, v in r.items() if v and str(v).strip()}
        if filled:
            return r
    return records[0]


def transform_cssrs_screen(redcap_data):
    """Transform C-SSRS Screen (weekly) data for Firestore."""
    questions = {}
    for field, label in CSSRS_SCREEN_LABELS.items():
        val = redcap_data.get(field, "")
        questions[field] = {
            "label": label,
            "value": _yn(val),
            "raw": val,
        }

    total_raw = redcap_data.get("cssrs_scr_total", "")
    try:
        total = int(float(total_raw)) if total_raw else 0
    except (ValueError, TypeError):
        total = 0

    # Highest endorsed item = severity level
    severity = 0
    for i in range(6, 0, -1):
        if _yn(redcap_data.get(f"cssrs_scr_{i}", "")) is True:
            severity = i
            break

    crisis_triggered = any(
        _yn(redcap_data.get(f, "")) is True for f in CSSRS_CRISIS_TRIGGER_FIELDS
    )

    return {
        "type": "screen",
        "questions": questions,
        "total": total,
        "severity": severity,
        "crisisTriggered": crisis_triggered,
        "crisisTriggerFields": [
            f for f in CSSRS_CRISIS_TRIGGER_FIELDS
            if _yn(redcap_data.get(f, "")) is True
        ],
    }


def transform_cssrs_pediatric(redcap_data):
    """Transform C-SSRS Pediatric (interview) data for Firestore."""
    ideation = {
        "wish_to_be_dead": _yn(redcap_data.get("cssrs_ped_1", "")),
        "wish_to_be_dead_describe": _nonempty(redcap_data.get("cssrs_ped_1_describe", "")),
        "nonspecific_thoughts": _yn(redcap_data.get("cssrs_ped_2", "")),
        "nonspecific_thoughts_describe": _nonempty(redcap_data.get("cssrs_ped_2_describe", "")),
        "ideation_with_methods": _yn(redcap_data.get("cssrs_ped_3", "")),
        "ideation_with_methods_describe": _nonempty(redcap_data.get("cssrs_ped_3_describe", "")),
        "ideation_with_intent": _yn(redcap_data.get("cssrs_ped_4", "")),
        "ideation_with_intent_describe": _nonempty(redcap_data.get("cssrs_ped_4_describe", "")),
        "ideation_with_plan": _yn(redcap_data.get("cssrs_ped_5", "")),
        "plan_details": _nonempty(redcap_data.get("cssrs_5_plan", "")),
        "ideation_with_plan_describe": _nonempty(redcap_data.get("cssrs_ped_5_describe", "")),
    }

    behavior = {
        "actual_attempt": _yn(redcap_data.get("cssrs_ped_6a", "")),
        "actual_attempt_what": _nonempty(redcap_data.get("cssrs_ped_6a_what", "")),
        "actual_attempt_total": _nonempty(redcap_data.get("cssrs_ped_6a_total_attempt", "")),
        "interrupted_attempt": _yn(redcap_data.get("cssrs_ped_6b", "")),
        "interrupted_attempt_total": _nonempty(redcap_data.get("cssrs_ped_6b_total_attempt", "")),
        "aborted_attempt": _yn(redcap_data.get("cssrs_ped_6c", "")),
        "aborted_attempt_total": _nonempty(redcap_data.get("cssrs_ped_6c_total_attempt", "")),
        "preparatory_acts": _yn(redcap_data.get("cssrs_ped_6d", "")),
        "preparatory_acts_total": _nonempty(redcap_data.get("cssrs_ped_6d_total_attempt", "")),
        "non_suicidal_self_harm": _yn(redcap_data.get("cssrs_ped_ns_sh", "")),
    }

    # Highest endorsed ideation item = severity
    severity = 0
    for i in range(5, 0, -1):
        if _yn(redcap_data.get(f"cssrs_ped_{i}", "")) is True:
            severity = i
            break

    # Crisis: items 4 (intent), 5 (plan), or actual attempt/preparatory acts
    crisis_triggered = (
        ideation["ideation_with_intent"] is True or
        ideation["ideation_with_plan"] is True or
        behavior["actual_attempt"] is True or
        behavior["preparatory_acts"] is True
    )

    return {
        "type": "pediatric",
        "ideation": ideation,
        "intensity": _nonempty(redcap_data.get("cssrs_ped_intensity", "")),
        "frequency": _nonempty(redcap_data.get("cssrs_frequency", "")),
        "behavior": behavior,
        "severity": severity,
        "crisisTriggered": crisis_triggered,
    }


def sync_cssrs_from_redcap(record_id, instrument, event_name, participant_id, db, config, logger):
    """
    Fetch C-SSRS from REDCap, transform, write to Firestore.
    Triggers a crisis alert (safety_alerts doc) if questions 4/5/6 are endorsed.
    """
    redcap_data = fetch_redcap_cssrs(record_id, instrument, event_name, config)

    if "scree" in instrument:
        cssrs = transform_cssrs_screen(redcap_data)
    else:
        cssrs = transform_cssrs_pediatric(redcap_data)

    cssrs["syncedAt"] = datetime.utcnow()
    cssrs["syncedBy"] = "redcap_trigger"
    cssrs["redcapRecordId"] = record_id
    cssrs["redcapInstrument"] = instrument
    cssrs["redcapEvent"] = event_name

    participants_col = config.col("participants")
    p_ref = db.collection(participants_col).document(participant_id)

    # Historical record
    assess_id = f"{instrument[:20]}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    p_ref.collection("cssrs_assessments").document(assess_id).set(cssrs)

    # Latest record for quick access
    latest_key = "latest_screen" if "scree" in instrument else "latest_pediatric"
    p_ref.collection("cssrs_assessments").document(latest_key).set(cssrs)

    logger.info(
        f"[C-SSRS] Synced {instrument[:30]} for participant {participant_id} "
        f"(severity={cssrs['severity']}, crisis={cssrs.get('crisisTriggered', False)})"
    )

    # Trigger crisis alert if intent/planning/preparation endorsed
    if cssrs.get("crisisTriggered"):
        trigger_fields = cssrs.get("crisisTriggerFields", [])
        instrument_label = "Weekly C-SSRS" if "scree" in instrument else "C-SSRS Interview"
        logger.warning(
            f"[C-SSRS CRISIS] Participant {participant_id} — "
            f"crisis triggered by {instrument_label}: {trigger_fields}"
        )

        alert_id = f"cssrs-{assess_id}"
        p_ref.collection("safety_alerts").document(alert_id).set({
            "participantId": participant_id,
            "alertType": "cssrs_crisis",
            "triggeredAt": datetime.utcnow(),
            "confirmedDanger": None,
            "handled": False,
            "source": instrument_label,
            "severity": cssrs["severity"],
            "crisisTriggerFields": trigger_fields if trigger_fields else ["ideation_with_intent_or_plan"],
            "redcapRecordId": record_id,
        })

        # Auto-send Risk Assessment PDF to Slack
        try:
            from risk_assessment import auto_send_risk_pdf_if_needed
            auto_send_risk_pdf_if_needed(participant_id, db, config, logger)
        except Exception as e:
            logger.error(f"[C-SSRS] Auto-PDF failed: {e}")

    return {
        "status": "cssrs_synced",
        "participant_id": participant_id,
        "instrument": instrument,
        "severity": cssrs["severity"],
        "crisis_triggered": cssrs.get("crisisTriggered", False),
    }
