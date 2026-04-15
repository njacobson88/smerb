# Risk Assessment Summary Module
# Compiles EMA + C-SSRS + Safety Plan data into a live risk assessment,
# generates PDF, and emails to Slack.

import os
import json
import base64
from datetime import datetime, timedelta

from fastapi import HTTPException, Query, Request, Response, Depends
from firebase_admin import firestore

from cssrs_sync import CSSRS_CRISIS_TRIGGER_FIELDS, CSSRS_SCREEN_LABELS

# ---------------------------------------------------------------------------
# EMA constants
# ---------------------------------------------------------------------------

EMA_QUESTION_LABELS = {
    "social_media_use": {"label": "In the last 4 hours, have you used social media?", "anchors": "Yes / No"},
    "social_media_feeling": {"label": "How did you feel after using social media?", "anchors": "1 (Much worse) to 5 (Much better)"},
    "sad_depressed": {"label": "Right now, how sad or depressed are you feeling?", "anchors": "0 (Not at all) to 100 (Extremely)"},
    "anxious_worried": {"label": "Right now, how anxious or worried are you feeling?", "anchors": "0 (Not at all) to 100 (Extremely)"},
    "hopeless": {"label": "Right now, how hopeless are you feeling?", "anchors": "0 (Not at all) to 100 (Extremely)"},
    "desire_intensity": {"label": "How intense is your desire to kill yourself right now?", "anchors": "0 (Not at all) to 100 (Extremely)"},
    "intention_strength": {"label": "How strong is your intention to kill yourself right now?", "anchors": "0 (Not at all) to 100 (Extremely)"},
    "ability_safe": {"label": "How able are you to keep yourself safe right now?", "anchors": "0 (Not at all) to 100 (Completely)"},
    "thoughts_past_4hrs": {"label": "At any point in the last 4 hours, did you have any thoughts of killing yourself?", "anchors": "Yes / No"},
    "thoughts_duration": {"label": "How long did these thoughts last?", "anchors": "<1 min, 1-5 min, 6-10 min, 11-30 min, 31-60 min, >60 min"},
    "thoughts_intent": {"label": "How strong was your intent to act on these thoughts?", "anchors": "0 (Not at all) to 100 (Extremely)"},
}

EMA_SAFETY_TRIGGER_FIELDS = [
    "desire_intensity", "intention_strength", "ability_safe", "thoughts_intent",
]
EMA_THRESHOLD = 30


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def compute_ema_risk_score(responses: dict) -> int:
    """Composite EMA risk score from safety trigger fields (0-100)."""
    scores = []
    for field in EMA_SAFETY_TRIGGER_FIELDS:
        val = responses.get(field)
        if val is not None:
            try:
                score = float(val)
                if field == "ability_safe":
                    score = 100 - score  # inverted: lower = more dangerous
                scores.append(score)
            except (ValueError, TypeError):
                pass
    return int(max(scores)) if scores else 0


def determine_risk_level(ema_score: int, cssrs_severity: int, imminent: bool) -> str:
    """Overall risk level from EMA and C-SSRS data."""
    if imminent:
        return "IMMINENT"
    if cssrs_severity >= 4 or ema_score >= 70:
        return "HIGH"
    if cssrs_severity >= 2 or ema_score >= 30:
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# Data fetchers (from Firestore)
# ---------------------------------------------------------------------------

def _fetch_latest_ema(p_ref):
    """Fetch the most recent EMA check-in for a participant."""
    docs = list(
        p_ref.collection("ema_responses")
        .order_by("completedAt", direction=firestore.Query.DESCENDING)
        .limit(1).stream()
    )
    if not docs:
        return None, 0, False

    data = docs[0].to_dict()
    responses = data.get("responses", {})
    if isinstance(responses, str):
        try:
            responses = json.loads(responses)
        except Exception:
            responses = {}

    ema_score = compute_ema_risk_score(responses)
    imminent = responses.get("safety_confirmed_danger") is True

    questions = {}
    for field, q_info in EMA_QUESTION_LABELS.items():
        val = responses.get(field)
        is_trigger = field in EMA_SAFETY_TRIGGER_FIELDS
        exceeds = False

        # Round numeric slider values to whole numbers
        display_val = val
        if val is not None:
            try:
                fval = float(val)
                display_val = round(fval)
                if is_trigger:
                    exceeds = (fval <= EMA_THRESHOLD) if field == "ability_safe" else (fval >= EMA_THRESHOLD)
            except (ValueError, TypeError):
                pass

        questions[field] = {
            "label": q_info["label"],
            "anchors": q_info["anchors"],
            "value": display_val,
            "isTrigger": is_trigger,
            "exceedsThreshold": exceeds,
        }

    ema = {
        "id": docs[0].id,
        "completedAt": data.get("completedAt"),
        "responses": responses,
        "riskScore": ema_score,
        "triggeredAlert": ema_score >= EMA_THRESHOLD,
        "questions": questions,
    }
    return ema, ema_score, imminent


def _fetch_latest_cssrs(p_ref, doc_id):
    """Fetch latest C-SSRS assessment (screen or pediatric)."""
    doc = p_ref.collection("cssrs_assessments").document(doc_id).get()
    if doc.exists:
        data = doc.to_dict()
        return data, data.get("severity", 0)
    return None, 0


def _fetch_safety_plan(p_ref):
    """Fetch current safety plan."""
    doc = p_ref.collection("safety_plan").document("current").get()
    return doc.to_dict() if doc.exists else None


def _fetch_alert_history(p_ref, limit=20):
    """Fetch recent safety alerts."""
    docs = list(
        p_ref.collection("safety_alerts")
        .order_by("triggeredAt", direction=firestore.Query.DESCENDING)
        .limit(limit).stream()
    )
    return [
        {
            "id": d.id,
            "type": d.to_dict().get("alertType"),
            "triggeredAt": d.to_dict().get("triggeredAt"),
            "confirmedDanger": d.to_dict().get("confirmedDanger"),
            "handled": d.to_dict().get("handled"),
            "source": d.to_dict().get("source"),
        }
        for d in docs
    ]


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def build_risk_assessment_html(assessment, generated_by="system"):
    """Build HTML for the Risk Assessment Summary PDF."""
    risk_colors = {
        "LOW": "#22c55e", "MODERATE": "#f59e0b",
        "HIGH": "#ef4444", "IMMINENT": "#dc2626",
    }
    risk_color = risk_colors.get(assessment["riskLevel"], "#6b7280")
    pid = assessment["participantId"]
    parts = [f"""<html><head><style>
        body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11px; margin: 30px; }}
        h1 {{ font-size: 18px; color: #1f2937; border-bottom: 2px solid #3b82f6; padding-bottom: 8px; }}
        h2 {{ font-size: 14px; color: #374151; margin-top: 20px; border-bottom: 1px solid #d1d5db; padding-bottom: 4px; }}
        h3 {{ font-size: 12px; color: #4b5563; margin-top: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
        th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; font-size: 10px; }}
        th {{ background-color: #f3f4f6; font-weight: bold; }}
        .risk-badge {{ display: inline-block; padding: 4px 12px; border-radius: 4px;
                      color: white; font-weight: bold; font-size: 14px; background-color: {risk_color}; }}
        .trigger {{ background-color: #fef2f2; color: #dc2626; font-weight: bold; }}
        .meta {{ color: #6b7280; font-size: 10px; }}
    </style></head><body>
    <h1>Risk Assessment Summary</h1>
    <p><strong>Participant:</strong> {pid} &nbsp;
       <strong>Generated:</strong> {assessment['generatedAt'][:19]} UTC &nbsp;
       <strong>By:</strong> {generated_by}</p>
    <p><span class="risk-badge">{assessment['riskLevel']} RISK</span>
       &nbsp; EMA: {assessment['emaScore']} &nbsp; C-SSRS: {assessment['cssrsSeverity']}
       &nbsp; Imminent: {'YES' if assessment['imminentRisk'] else 'No'}</p>"""]

    # EMA
    ema = assessment.get("latestEma")
    if ema:
        completed = ema.get("completedAt")
        if hasattr(completed, "isoformat"):
            completed = completed.isoformat()[:19]
        parts.append(f'<h2>EMA Check-in</h2><p class="meta">Completed: {completed or "Unknown"}</p>')
        parts.append("<table><tr><th>Question</th><th>Response</th><th></th></tr>")
        for q in ema.get("questions", {}).values():
            val = q.get("value")
            val_str = "Yes" if val is True else ("No" if val is False else (str(val) if val is not None else "—"))
            cls = ' class="trigger"' if q.get("exceedsThreshold") else ""
            mark = "!!" if q.get("exceedsThreshold") else ""
            parts.append(f'<tr{cls}><td>{q["label"]}</td><td>{val_str}</td><td>{mark}</td></tr>')
        parts.append("</table>")

    # C-SSRS Screen
    cs = assessment.get("cssrsScreen")
    if cs:
        synced = cs.get("syncedAt")
        if hasattr(synced, "isoformat"):
            synced = synced.isoformat()[:19]
        parts.append(f'<h2>C-SSRS Screen (Weekly)</h2><p class="meta">Synced: {synced or "Unknown"} | Severity: {cs.get("severity", 0)}</p>')
        parts.append("<table><tr><th>Question</th><th>Response</th></tr>")
        for field, q in cs.get("questions", {}).items():
            v = q.get("value")
            vs = "Yes" if v is True else ("No" if v is False else "—")
            crisis = field in CSSRS_CRISIS_TRIGGER_FIELDS and v is True
            cls = ' class="trigger"' if crisis else ""
            parts.append(f'<tr{cls}><td>{q["label"]}</td><td>{vs}</td></tr>')
        parts.append("</table>")

    # C-SSRS Pediatric
    cp = assessment.get("cssrsPediatric")
    if cp:
        synced = cp.get("syncedAt")
        if hasattr(synced, "isoformat"):
            synced = synced.isoformat()[:19]
        parts.append(f'<h2>C-SSRS Interview (Pediatric)</h2><p class="meta">Synced: {synced or "Unknown"} | Severity: {cp.get("severity", 0)}</p>')
        parts.append("<table><tr><th>Item</th><th>Endorsed</th></tr>")
        ideation = cp.get("ideation", {})
        for key, label in [
            ("wish_to_be_dead", "1. Wish to be Dead"),
            ("nonspecific_thoughts", "2. Non-Specific Active Suicidal Thoughts"),
            ("ideation_with_methods", "3. Ideation with Methods"),
            ("ideation_with_intent", "4. Ideation with Intent"),
            ("ideation_with_plan", "5. Ideation with Plan and Intent"),
        ]:
            v = ideation.get(key)
            vs = "Yes" if v is True else ("No" if v is False else "—")
            crisis = key in ("ideation_with_intent", "ideation_with_plan") and v is True
            cls = ' class="trigger"' if crisis else ""
            parts.append(f'<tr{cls}><td>{label}</td><td>{vs}</td></tr>')
        behavior = cp.get("behavior", {})
        for key, label in [
            ("actual_attempt", "Actual Attempt"),
            ("interrupted_attempt", "Interrupted Attempt"),
            ("aborted_attempt", "Aborted Attempt"),
            ("preparatory_acts", "Preparatory Acts"),
        ]:
            v = behavior.get(key)
            vs = "Yes" if v is True else ("No" if v is False else "—")
            cls = ' class="trigger"' if v is True else ""
            parts.append(f'<tr{cls}><td>{label}</td><td>{vs}</td></tr>')
        parts.append("</table>")

    # Safety Plan
    sp = assessment.get("safetyPlan")
    if sp:
        parts.append("<h2>Safety Plan</h2>")
        for title, key in [
            ("Step 1: Warning Signs", "warningSigns"),
            ("Step 2: Coping Strategies", "copingStrategies"),
            ("Step 6: Environment Safety", "environmentSafety"),
        ]:
            items = sp.get(key, [])
            if items:
                parts.append(f"<h3>{title}</h3><ul>")
                for item in items:
                    parts.append(f"<li>{item}</li>")
                parts.append("</ul>")

        for contacts_key, title in [
            ("supportContacts", "Step 4: Support Network"),
            ("distractionContacts", "Step 3: Distraction Contacts"),
        ]:
            contacts = sp.get(contacts_key, [])
            if contacts:
                parts.append(f"<h3>{title}</h3><ul>")
                for c in contacts:
                    parts.append(f"<li>{c.get('name', '')} — {c.get('phone', '')}</li>")
                parts.append("</ul>")

        if sp.get("clinicianName"):
            parts.append(f"<h3>Clinician</h3><p>{sp['clinicianName']} — {sp.get('clinicianPhone', '')}</p>")
        if sp.get("localErName"):
            parts.append(f"<p>Local ER: {sp['localErName']} — {sp.get('localErPhone', '')} — {sp.get('localErAddress', '')}</p>")
        if sp.get("reasonsToLive"):
            parts.append(f"<h3>Step 7: Reasons for Living</h3><p>{sp['reasonsToLive']}</p>")

    # Alert History
    alerts = assessment.get("alertHistory", [])
    if alerts:
        parts.append("<h2>Recent Alerts (30 Days)</h2><table>")
        parts.append("<tr><th>Date</th><th>Type</th><th>Confirmed</th><th>Handled</th></tr>")
        for a in alerts[:10]:
            t = a.get("triggeredAt")
            if hasattr(t, "isoformat"):
                t = t.isoformat()[:19]
            parts.append(
                f'<tr><td>{t or "—"}</td><td>{a.get("type", "—")}</td>'
                f'<td>{"Yes" if a.get("confirmedDanger") else "No"}</td>'
                f'<td>{"Yes" if a.get("handled") else "No"}</td></tr>'
            )
        parts.append("</table>")

    parts.append("</body></html>")
    return "\n".join(parts)


def build_risk_assessment_pdf(assessment, pdf_path, generated_by="system"):
    """Build a PDF of the Risk Assessment Summary using fpdf2."""
    from fpdf import FPDF

    class RiskPDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 14)
            self.cell(0, 8, "Risk Assessment Summary", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5,
                f"Participant: {assessment['participantId']}  |  "
                f"Generated: {assessment['generatedAt'][:19]} UTC  |  By: {generated_by}",
                new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)
            self.ln(2)

        def section_title(self, title):
            self.set_font("Helvetica", "B", 11)
            self.set_fill_color(240, 240, 240)
            self.cell(0, 7, _safe(title), new_x="LMARGIN", new_y="NEXT", fill=True)
            self.ln(1)

        def table_row(self, col1, col2, highlight=False):
            if highlight:
                self.set_fill_color(254, 226, 226)
                self.set_text_color(185, 28, 28)
            else:
                self.set_fill_color(255, 255, 255)
                self.set_text_color(0, 0, 0)
            self.set_font("Helvetica", "", 8)
            w1 = self.w - self.l_margin - self.r_margin - 35
            self.cell(w1, 5, _safe(col1)[:90], border="B", fill=highlight)
            self.cell(35, 5, _safe(col2)[:20], border="B", fill=highlight, new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)

    def _safe(text):
        """Replace Unicode chars not supported by Latin-1 fonts."""
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        return text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2026", "...").replace("\u2022", "-")

    pdf = RiskPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Risk Level Badge
    colors = {"LOW": (34, 197, 94), "MODERATE": (245, 158, 11), "HIGH": (239, 68, 68), "IMMINENT": (220, 38, 38)}
    r, g, b = colors.get(assessment["riskLevel"], (107, 114, 128))
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(50, 8, f"  {assessment['riskLevel']} RISK", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 8,
        f"   EMA: {assessment['emaScore']}  |  C-SSRS: {assessment['cssrsSeverity']}  |  "
        f"Imminent: {'YES' if assessment['imminentRisk'] else 'No'}",
        new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Contact Info
    ci = assessment.get("contactInfo", {})
    if ci:
        pdf.section_title("Contact Information")
        pdf.set_font("Helvetica", "", 8)
        for label, val in [
            ("Phone", ci.get("phone")),
            ("Email", ci.get("email")),
            ("Address", ci.get("address")),
            ("County", ci.get("county")),
            ("Emergency Services", ci.get("erServiceNumber")),
        ]:
            if val:
                pdf.cell(30, 5, f"{label}:", new_x="RIGHT")
                pdf.cell(0, 5, _safe(val), new_x="LMARGIN", new_y="NEXT")
        clin = ci.get("clinician", {})
        if clin and clin.get("name"):
            pdf.cell(30, 5, "Clinician:", new_x="RIGHT")
            pdf.cell(0, 5, _safe(f"{clin['name']} - {clin.get('phone', '')}"), new_x="LMARGIN", new_y="NEXT")
        er = ci.get("localER", {})
        if er and er.get("name"):
            pdf.cell(30, 5, "Local ER:", new_x="RIGHT")
            pdf.cell(0, 5, _safe(f"{er['name']} - {er.get('phone', '')} - {er.get('address', '')}"), new_x="LMARGIN", new_y="NEXT")
        for ec in ci.get("emergencyContacts", []):
            pdf.cell(30, 5, "Emergency:", new_x="RIGHT")
            pdf.cell(0, 5, _safe(f"{ec.get('name', '')} - {ec.get('phone', '')} ({ec.get('relationship', '')})"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # EMA
    ema = assessment.get("latestEma")
    if ema:
        completed = ema.get("completedAt")
        if hasattr(completed, "isoformat"):
            completed = completed.isoformat()[:19]
        pdf.section_title(f"EMA Check-in ({completed or 'Unknown'})")
        for q in ema.get("questions", {}).values():
            val = q.get("value")
            val_str = "Yes" if val is True else ("No" if val is False else (str(val) if val is not None else "-"))
            anchors = q.get("anchors", "")
            label = f"{q['label']}  [{anchors}]" if anchors else q["label"]
            pdf.table_row(label, val_str, highlight=q.get("exceedsThreshold", False))
        pdf.ln(2)

    # C-SSRS Screen
    cs = assessment.get("cssrsScreen")
    if cs:
        pdf.section_title(f"C-SSRS Screen (Weekly) — Severity: {cs.get('severity', 0)}")
        for field, q in cs.get("questions", {}).items():
            v = q.get("value")
            vs = "Yes" if v is True else ("No" if v is False else "-")
            crisis = field in ("cssrs_scr_4", "cssrs_scr_5", "cssrs_scr_6") and v is True
            pdf.table_row(q["label"], vs, highlight=crisis)
        pdf.ln(2)

    # C-SSRS Pediatric
    cp = assessment.get("cssrsPediatric")
    if cp:
        pdf.section_title(f"C-SSRS Interview (Pediatric) — Severity: {cp.get('severity', 0)}")
        ideation = cp.get("ideation", {})
        for key, label in [
            ("wish_to_be_dead", "1. Wish to be Dead"),
            ("nonspecific_thoughts", "2. Non-Specific Active Suicidal Thoughts"),
            ("ideation_with_methods", "3. Ideation with Methods"),
            ("ideation_with_intent", "4. Ideation with Intent"),
            ("ideation_with_plan", "5. Ideation with Plan and Intent"),
        ]:
            v = ideation.get(key)
            vs = "Yes" if v is True else ("No" if v is False else "-")
            crisis = key in ("ideation_with_intent", "ideation_with_plan") and v is True
            pdf.table_row(label, vs, highlight=crisis)
        behavior = cp.get("behavior", {})
        for key, label in [
            ("actual_attempt", "Actual Attempt"),
            ("preparatory_acts", "Preparatory Acts"),
            ("non_suicidal_self_harm", "Non-Suicidal Self-Harm"),
        ]:
            v = behavior.get(key)
            vs = "Yes" if v is True else ("No" if v is False else "-")
            pdf.table_row(label, vs, highlight=(v is True))
        pdf.ln(2)

    # Safety Plan Summary
    sp = assessment.get("safetyPlan")
    if sp:
        pdf.section_title("Safety Plan")
        pdf.set_font("Helvetica", "", 8)
        for title, key in [("Warning Signs", "warningSigns"), ("Coping Strategies", "copingStrategies"), ("Environment Safety", "environmentSafety")]:
            items = sp.get(key, [])
            if items:
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 8)
                for item in items:
                    pdf.cell(5, 4, "", new_x="RIGHT")
                    pdf.cell(0, 4, _safe(f"- {item}"), new_x="LMARGIN", new_y="NEXT")
        if sp.get("reasonsToLive"):
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(0, 5, "Reasons for Living", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.multi_cell(0, 4, _safe(sp["reasonsToLive"]))
        pdf.ln(2)

    # Alert History
    alerts = assessment.get("alertHistory", [])
    if alerts:
        pdf.section_title("Recent Alerts (30 Days)")
        for a in alerts[:10]:
            t = a.get("triggeredAt")
            if hasattr(t, "isoformat"):
                t = t.isoformat()[:19]
            pdf.table_row(
                f"{t or '-'}  |  {a.get('type', '-')}  |  Source: {a.get('source', '-')}",
                "Handled" if a.get("handled") else "Open",
                highlight=a.get("confirmedDanger", False),
            )

    pdf.output(pdf_path)


def email_pdf_to_slack(pdf_path, assessment, generated_by, logger):
    """Send the PDF to the Slack channel via SendGrid email."""
    try:
        import sendgrid
        from sendgrid.helpers.mail import (
            Mail, Attachment, FileContent, FileName, FileType, Disposition,
        )

        sg_key = os.getenv("SENDGRID_API_KEY")
        slack_email = os.getenv("SLACK_CHANNEL_EMAIL")
        sender = os.getenv("ALERT_SENDER_EMAIL", "Social.Media.Wellness@dartmouth.edu")

        if not sg_key or not slack_email:
            logger.warning("[RiskAssessment] SendGrid/Slack not configured")
            return False

        with open(pdf_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode()

        is_pdf = pdf_path.endswith(".pdf")
        pid = assessment["participantId"]

        message = Mail(
            from_email=sender,
            to_emails=slack_email,
            subject=f"[{assessment['riskLevel']} RISK] Risk Assessment — Participant {pid}",
            plain_text_content=(
                f"Risk Assessment Summary for participant {pid}\n"
                f"Risk Level: {assessment['riskLevel']}\n"
                f"EMA Score: {assessment['emaScore']} | C-SSRS Severity: {assessment['cssrsSeverity']}\n"
                f"Imminent Risk: {'YES' if assessment['imminentRisk'] else 'No'}\n"
                f"Generated by: {generated_by}\n"
                f"See attached for full summary."
            ),
        )
        message.attachment = Attachment(
            FileContent(file_data),
            FileName(f"risk_assessment_{pid}.{'pdf' if is_pdf else 'html'}"),
            FileType("application/pdf" if is_pdf else "text/html"),
            Disposition("attachment"),
        )

        sg = sendgrid.SendGridAPIClient(api_key=sg_key)
        sg.send(message)
        logger.info(f"[RiskAssessment] PDF emailed to Slack for {pid}")
        return True
    except Exception as e:
        logger.error(f"[RiskAssessment] Slack email failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Auto-send PDF on high risk (called from cssrs_sync or safety alert pipeline)
# ---------------------------------------------------------------------------

def auto_send_risk_pdf_if_needed(participant_id, db, config, logger):
    """
    Check risk level for a participant and auto-send PDF to Slack if HIGH or IMMINENT.
    Called after C-SSRS sync or EMA safety alert trigger.
    """
    try:
        p_ref = db.collection(config.col("participants")).document(participant_id)

        latest_ema, ema_score, ema_imminent = _fetch_latest_ema(p_ref)
        _, screen_sev = _fetch_latest_cssrs(p_ref, "latest_screen")
        _, ped_sev = _fetch_latest_cssrs(p_ref, "latest_pediatric")
        safety_plan = _fetch_safety_plan(p_ref)

        cssrs_severity = max(screen_sev, ped_sev)
        imminent = ema_imminent or screen_sev >= 4 or ped_sev >= 4
        risk_level = determine_risk_level(ema_score, cssrs_severity, imminent)

        if risk_level not in ("HIGH", "IMMINENT"):
            return

        logger.info(f"[RiskAssessment] Auto-generating PDF for {participant_id} — {risk_level} risk")

        # Build a minimal assessment dict for the PDF
        cssrs_screen, _ = _fetch_latest_cssrs(p_ref, "latest_screen")
        cssrs_pediatric, _ = _fetch_latest_cssrs(p_ref, "latest_pediatric")
        alerts = _fetch_alert_history(p_ref, limit=10)

        participant_data = {}
        try:
            p_doc = p_ref.get()
            if p_doc.exists:
                participant_data = p_doc.to_dict()
        except Exception:
            pass

        assessment = {
            "participantId": participant_id,
            "generatedAt": datetime.utcnow().isoformat(),
            "riskLevel": risk_level,
            "imminentRisk": imminent,
            "emaScore": ema_score,
            "cssrsSeverity": cssrs_severity,
            "latestEma": latest_ema,
            "cssrsScreen": cssrs_screen,
            "cssrsPediatric": cssrs_pediatric,
            "safetyPlan": safety_plan,
            "alertHistory": alerts,
        }

        html_content = build_risk_assessment_html(assessment, "auto_alert")
        pdf_path = f"/tmp/risk_assessment_{participant_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        with open(pdf_path, "w") as f:
            f.write(html_content)

        email_pdf_to_slack(pdf_path, assessment, "auto_alert", logger)

    except Exception as e:
        logger.error(f"[RiskAssessment] Auto-send PDF failed for {participant_id}: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Route registration (called from main.py)
# ---------------------------------------------------------------------------

def register_risk_assessment_routes(app, db, limiter, verify_firebase_token, config, logger):
    """Register risk assessment API routes on the FastAPI app."""

    @app.get("/api/participant/{participant_id}/risk-assessment")
    @limiter.limit("30/minute")
    def get_risk_assessment(
        request: Request,
        participant_id: str,
        user: dict = Depends(verify_firebase_token),
    ):
        """Compile a live Risk Assessment Summary for a participant."""
        try:
            p_ref = db.collection(config.col("participants")).document(participant_id)

            latest_ema, ema_score, ema_imminent = _fetch_latest_ema(p_ref)
            cssrs_screen, screen_sev = _fetch_latest_cssrs(p_ref, "latest_screen")
            cssrs_pediatric, ped_sev = _fetch_latest_cssrs(p_ref, "latest_pediatric")
            safety_plan = _fetch_safety_plan(p_ref)
            alerts = _fetch_alert_history(p_ref)

            cssrs_severity = max(screen_sev, ped_sev)
            cssrs_crisis = (
                (cssrs_screen and cssrs_screen.get("crisisTriggered")) or
                (cssrs_pediatric and cssrs_pediatric.get("crisisTriggered"))
            )
            imminent = ema_imminent or bool(cssrs_crisis)
            risk_level = determine_risk_level(ema_score, cssrs_severity, imminent)

            participant_data = {}
            try:
                p_doc = p_ref.get()
                if p_doc.exists:
                    participant_data = p_doc.to_dict()
            except Exception:
                pass

            # Build comprehensive contact info from participant doc + safety plan
            contact_info = {
                "phone": participant_data.get("phone") or participant_data.get("phoneNumber"),
                "email": participant_data.get("email"),
                "address": participant_data.get("address"),
                "county": participant_data.get("county") or (safety_plan or {}).get("county"),
                "erServiceNumber": participant_data.get("erServiceNumber") or (safety_plan or {}).get("erServiceNumber"),
                "emergencyContacts": participant_data.get("emergencyContacts", []),
            }

            # Clinician and local ER from safety plan
            if safety_plan:
                contact_info["clinician"] = {
                    "name": safety_plan.get("clinicianName"),
                    "phone": safety_plan.get("clinicianPhone"),
                    "erContact": safety_plan.get("clinicianErContact"),
                }
                contact_info["localER"] = {
                    "name": safety_plan.get("localErName"),
                    "phone": safety_plan.get("localErPhone"),
                    "address": safety_plan.get("localErAddress"),
                }

            return {
                "participantId": participant_id,
                "generatedAt": datetime.utcnow().isoformat(),
                "riskLevel": risk_level,
                "imminentRisk": imminent,
                "emaScore": ema_score,
                "cssrsSeverity": cssrs_severity,
                "latestEma": latest_ema,
                "cssrsScreen": cssrs_screen,
                "cssrsPediatric": cssrs_pediatric,
                "safetyPlan": safety_plan,
                "alertHistory": alerts,
                "contactInfo": contact_info,
                "participantInfo": {
                    "enrolledAt": participant_data.get("enrolledAt"),
                },
            }
        except Exception as e:
            logger.error(f"[RiskAssessment] Failed for {participant_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/participant/{participant_id}/risk-assessment/pdf")
    @limiter.limit("10/minute")
    def generate_risk_assessment_pdf(
        request: Request,
        participant_id: str,
        send_to_slack: bool = Query(default=True),
        user: dict = Depends(verify_firebase_token),
    ):
        """Generate a PDF of the Risk Assessment Summary and optionally email to Slack."""
        try:
            assessment = get_risk_assessment(request, participant_id, user)

            html_content = build_risk_assessment_html(assessment, user.get("email", "system"))

            pdf_path = f"/tmp/risk_assessment_{participant_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
            build_risk_assessment_pdf(assessment, pdf_path, user.get("email", "system"))

            slack_sent = False
            if send_to_slack:
                slack_sent = email_pdf_to_slack(pdf_path, assessment, user.get("email", "system"), logger)

            return {
                "status": "generated",
                "participant_id": participant_id,
                "risk_level": assessment["riskLevel"],
                "pdf_path": pdf_path,
                "sent_to_slack": slack_sent,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[RiskAssessment] PDF failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
