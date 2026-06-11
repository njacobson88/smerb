# C-SSRS REDCap Sync Module
# Handles fetching, transforming, and storing C-SSRS data from REDCap,
# and triggering crisis alerts when intent/planning/behavior items are endorsed.
#
# NOTE (2026-06-11): instrument + field names were corrected against the live
# REDCap data dictionary (project 1884). The previous values
# ("columbia_suicide_severity_rating_scale_cssrs_scree/pedia", "cssrs_scr_6",
# "cssrs_scr_total") did not exist, so the C-SSRS crisis pathway never fired.
# Crisis trigger rule = standard C-SSRS high-risk criterion (active ideation
# with intent OR plan, OR any suicidal behavior). The clinical team should
# confirm these trigger rules and run a live REDCap test save.

from datetime import datetime
import requests as http_requests

# REDCap instrument (form) names — must match what the DET sends.
CSSRS_SCREEN_INSTRUMENT = "cssrs_screener"
CSSRS_WEEKLY_INSTRUMENT = "cssrs_weekly"
CSSRS_PEDIATRIC_INSTRUMENT = "cssrs_pediatrics"
CSSRS_INSTRUMENTS = (CSSRS_SCREEN_INSTRUMENT, CSSRS_WEEKLY_INSTRUMENT, CSSRS_PEDIATRIC_INSTRUMENT)

# Per-form field maps: item key -> REDCap field name. Reading a missing field
# yields None (safe); we fetch the whole form so an unknown field never 400s.
SCREEN_FIELDS = {
    "ideation": ["cssrs_scr_1", "cssrs_scr_2", "cssrs_scr_3", "cssrs_scr_4", "cssrs_scr_5"],
    "behavior": ["cssrs_scr_6a", "cssrs_scr_6b"],
    "score": "cssrs_scr_risk_score",
    "risk_level": "cssrs_scr_risk_level",
}
WEEKLY_FIELDS = {
    "ideation": ["cssrs_scr_1cssrs_wkly", "cssrs_scr_2cssrs_wkly", "cssrs_scr_3cssrs_wkly",
                 "cssrs_scr_4cssrs_wkly", "cssrs_scr_5cssrs_wkly"],
    "behavior": ["cssrs_scr_6cssrs_wkly", "cssrs_scr_6_last3mcssrs_wkly"],
    "score": "cssrs_weekly_score",
    "risk_level": "cssrs_wkly_risk_level",
}
PEDIATRIC_FIELDS = {
    "ideation": ["cssrs_ped_1", "cssrs_ped_2", "cssrs_ped_3", "cssrs_ped_4", "cssrs_ped_5"],
    "behavior": ["cssrs_ped_6a", "cssrs_ped_6b", "cssrs_ped_6c", "cssrs_ped_6d"],
    "score": "cssrs_ped_risk_score",
    "risk_level": "cssrs_ped_risk_level",
}

CSSRS_ITEM_LABELS = {
    1: "1. Wish to be Dead",
    2: "2. Non-Specific Active Suicidal Thoughts",
    3: "3. Active Suicidal Ideation with Any Methods (Not Plan)",
    4: "4. Active Suicidal Ideation with Some Intent to Act",
    5: "5. Active Suicidal Ideation with Specific Plan and Intent",
}


def _form_for(instrument):
    if instrument == CSSRS_WEEKLY_INSTRUMENT:
        return WEEKLY_FIELDS
    if instrument == CSSRS_PEDIATRIC_INSTRUMENT:
        return PEDIATRIC_FIELDS
    return SCREEN_FIELDS


def _yn(val):
    """REDCap yesno (1/0) -> bool. Anything else (incl. '') -> None."""
    if val == "1":
        return True
    if val == "0":
        return False
    return None


def _nonempty(val):
    return val.strip() if val and str(val).strip() else None


def fetch_redcap_cssrs(record_id, instrument, event_name, config):
    """Fetch the C-SSRS form from REDCap. Requests the whole FORM (not a field
    list) so an unexpected/renamed field can never cause a 400 — robustness the
    previous field-enumeration approach lacked."""
    data = {
        "token": config.REDCAP_API_TOKEN,
        "content": "record",
        "format": "json",
        "records[0]": record_id,
        "forms[0]": instrument,
        "returnFormat": "json",
    }
    if event_name or config.REDCAP_TRIGGER_EVENT:
        data["events[0]"] = event_name or config.REDCAP_TRIGGER_EVENT

    resp = http_requests.post(config.REDCAP_API_URL, data=data, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"REDCap API error: {resp.status_code} {resp.text}")

    records = resp.json()
    if not records:
        raise Exception(f"No record found for record_id={record_id}")

    # Prefer the record row that actually has C-SSRS data populated.
    for r in records:
        if any(str(r.get(f, "")).strip() for f in
               (_form_for(instrument)["ideation"] + _form_for(instrument)["behavior"])):
            return r
    return records[0]


def _transform_cssrs(redcap_data, instrument):
    """Unified transform for screener / weekly / pediatric forms."""
    fmap = _form_for(instrument)
    is_pediatric = instrument == CSSRS_PEDIATRIC_INSTRUMENT

    ideation = {}
    for i, field in enumerate(fmap["ideation"], start=1):
        ideation[f"item_{i}"] = {
            "field": field,
            "label": CSSRS_ITEM_LABELS.get(i, f"Item {i}"),
            "value": _yn(redcap_data.get(field, "")),
            "raw": redcap_data.get(field, ""),
        }
    behavior = {}
    for field in fmap["behavior"]:
        behavior[field] = {
            "value": _yn(redcap_data.get(field, "")),
            "raw": redcap_data.get(field, ""),
        }

    # Severity: highest endorsed ideation item (1-5); 6 if any behavior endorsed.
    severity = 0
    for i in range(5, 0, -1):
        if _yn(redcap_data.get(fmap["ideation"][i - 1], "")) is True:
            severity = i
            break
    behavior_endorsed = any(_yn(redcap_data.get(f, "")) is True for f in fmap["behavior"])
    if behavior_endorsed:
        severity = 6

    # Crisis = active ideation with intent (item 4) or plan (item 5),
    # OR any suicidal behavior. (Standard C-SSRS high-risk criterion.)
    intent = _yn(redcap_data.get(fmap["ideation"][3], "")) is True   # item 4
    plan = _yn(redcap_data.get(fmap["ideation"][4], "")) is True     # item 5
    crisis_triggered = intent or plan or behavior_endorsed

    trigger_fields = []
    if intent:
        trigger_fields.append(fmap["ideation"][3])
    if plan:
        trigger_fields.append(fmap["ideation"][4])
    trigger_fields += [f for f in fmap["behavior"] if _yn(redcap_data.get(f, "")) is True]

    score_raw = redcap_data.get(fmap["score"], "")
    try:
        score = int(float(score_raw)) if str(score_raw).strip() else None
    except (ValueError, TypeError):
        score = None

    return {
        "type": "pediatric" if is_pediatric else ("weekly" if instrument == CSSRS_WEEKLY_INSTRUMENT else "screen"),
        "ideation": ideation,
        "behavior": behavior,
        "severity": severity,
        "behaviorEndorsed": behavior_endorsed,
        "riskScore": score,
        "riskLevel": _nonempty(redcap_data.get(fmap["risk_level"], "")),
        "crisisTriggered": crisis_triggered,
        "crisisTriggerFields": trigger_fields,
    }


def sync_cssrs_from_redcap(record_id, instrument, event_name, participant_id, db, config, logger):
    """Fetch C-SSRS from REDCap, transform, write to Firestore, and trigger a
    crisis alert if intent/plan/behavior is endorsed."""
    redcap_data = fetch_redcap_cssrs(record_id, instrument, event_name, config)
    cssrs = _transform_cssrs(redcap_data, instrument)

    cssrs["syncedAt"] = datetime.utcnow()
    cssrs["syncedBy"] = "redcap_trigger"
    cssrs["redcapRecordId"] = record_id
    cssrs["redcapInstrument"] = instrument
    cssrs["redcapEvent"] = event_name

    participants_col = config.col("participants")
    p_ref = db.collection(participants_col).document(participant_id)

    # Historical record (timestamped audit trail)
    assess_id = f"{instrument}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    p_ref.collection("cssrs_assessments").document(assess_id).set(cssrs)
    # Latest per form, for quick access
    latest_key = {
        CSSRS_WEEKLY_INSTRUMENT: "latest_weekly",
        CSSRS_PEDIATRIC_INSTRUMENT: "latest_pediatric",
    }.get(instrument, "latest_screen")
    p_ref.collection("cssrs_assessments").document(latest_key).set(cssrs)

    logger.info(
        f"[C-SSRS] Synced {instrument} for participant {participant_id} "
        f"(severity={cssrs['severity']}, crisis={cssrs['crisisTriggered']})"
    )

    if cssrs["crisisTriggered"]:
        label = {
            CSSRS_WEEKLY_INSTRUMENT: "Weekly C-SSRS",
            CSSRS_PEDIATRIC_INSTRUMENT: "C-SSRS Interview (Pediatric)",
        }.get(instrument, "C-SSRS Screener")
        logger.warning(
            f"[C-SSRS CRISIS] Participant {participant_id} — crisis triggered by "
            f"{label}: {cssrs['crisisTriggerFields']}"
        )

        # Idempotent alert id: stable per record+event+instrument so re-saving the
        # SAME assessment overwrites (no duplicate alert / re-page), while a new
        # timepoint (different REDCap event) creates a new alert that re-fires
        # the onSafetyAlert trigger.
        ev = (event_name or "noevent").replace("/", "_").replace(" ", "_")
        alert_id = f"cssrs-{record_id}-{ev}-{instrument}"
        p_ref.collection("safety_alerts").document(alert_id).set({
            "participantId": participant_id,
            "alertType": "cssrs_crisis",
            "triggeredAt": datetime.utcnow(),
            "confirmedDanger": None,
            "handled": False,
            "source": label,
            "severity": cssrs["severity"],
            "crisisTriggerFields": cssrs["crisisTriggerFields"],
            "redcapRecordId": record_id,
            "redcapInstrument": instrument,
            "redcapEvent": event_name,
        })

        # Auto-send Risk Assessment PDF to Slack (best-effort)
        try:
            from risk_assessment import auto_send_risk_pdf_if_needed
            auto_send_risk_pdf_if_needed(participant_id, db, config, logger)
        except Exception as e:
            logger.error(f"[C-SSRS] Auto-PDF failed for {participant_id}: {e}")

    return {
        "status": "cssrs_synced",
        "participant_id": participant_id,
        "instrument": instrument,
        "severity": cssrs["severity"],
        "crisis_triggered": cssrs["crisisTriggered"],
    }
