"""Send transactional email via Microsoft Graph (Mail.Send) as the study mailbox.

Replaces SendGrid (whose free trial ended and which required dartmouth.edu DNS
changes). Uses the Azure AD app registration "R01-SocialScope-Email-Alerts" with
the application Mail.Send permission (admin-consented, scoped to the
Social.Media.Wellness mailbox via an application access policy). Auth is the
OAuth2 client-credentials flow; we POST to /users/{mailbox}/sendMail.

Config (env): MSGRAPH_TENANT_ID, MSGRAPH_CLIENT_ID, MSGRAPH_CLIENT_SECRET
(mounted from Secret Manager), MSGRAPH_SENDER (defaults to the study mailbox).
If any are missing, graph_email_configured() is False and callers skip email.
"""
import json
import os
import time
import urllib.parse
import urllib.request

GRAPH_SENDER = os.getenv("MSGRAPH_SENDER", "Social.Media.Wellness@dartmouth.edu")

_token_cache = {"value": None, "exp": 0.0}


def graph_email_configured() -> bool:
    return bool(os.getenv("MSGRAPH_TENANT_ID") and os.getenv("MSGRAPH_CLIENT_ID")
               and (os.getenv("MSGRAPH_CLIENT_SECRET") or "").strip())


def _get_token(now=None) -> str:
    """Client-credentials access token, cached until ~60s before expiry."""
    now = now if now is not None else time.time()
    if _token_cache["value"] and _token_cache["exp"] - 60 > now:
        return _token_cache["value"]
    tenant = os.getenv("MSGRAPH_TENANT_ID")
    body = urllib.parse.urlencode({
        "client_id": os.getenv("MSGRAPH_CLIENT_ID"),
        "client_secret": (os.getenv("MSGRAPH_CLIENT_SECRET") or "").strip(),
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=body)
    resp = json.load(urllib.request.urlopen(req, timeout=20))
    _token_cache["value"] = resp["access_token"]
    _token_cache["exp"] = now + float(resp.get("expires_in", 3600))
    return _token_cache["value"]


def build_graph_message(to, subject, *, html=None, text=None, sender=None):
    """Build the Graph sendMail request body (pure — unit-tested)."""
    content_type = "HTML" if html else "Text"
    content = html if html else (text or "")
    return {
        "message": {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        # Don't clutter the shared mailbox's Sent Items with automated mail.
        "saveToSentItems": False,
    }


def send_graph_email(to, subject, *, html=None, text=None, sender=None) -> bool:
    """Send one email. Raises on failure (caller logs / falls back)."""
    if not graph_email_configured():
        raise RuntimeError("Microsoft Graph email not configured")
    sender = sender or GRAPH_SENDER
    token = _get_token()
    payload = json.dumps(build_graph_message(to, subject, html=html, text=text)).encode()
    req = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    urllib.request.urlopen(req, timeout=20)  # 202 Accepted, empty body
    return True
