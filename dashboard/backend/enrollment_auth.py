"""Enrollment-secret primitives for per-participant Firebase auth.

The cross-participant read hole exists because participants have no identity the
Firestore rules can check — the only "credential" today is *knowing* the
participantId, which is also what an attacker would use to read the data. To get
real per-participant isolation we need a secret that proves "I am participant X",
delivered out-of-band (in the REDCap/distribution invite), exchanged once for a
Firebase custom token (uid == participantId).

This module is the pure crypto half (generate / hash / verify), kept import-free
so it can be unit-tested standalone. main.py owns the Firestore storage of the
hash and the custom-token minting.

Design (see docs): at participant creation the backend generates a secret,
stores ONLY its hash on valid_participants, and includes the plaintext in the
invite. The app exchanges {participantId, secret} at an enrollment endpoint that
verifies the hash and returns a custom token. The plaintext secret is never
persisted server-side.
"""
import hashlib
import secrets


def generate_enrollment_secret() -> str:
    """A high-entropy (~190-bit) URL-safe one-time enrollment secret."""
    return secrets.token_urlsafe(24)


def hash_secret(secret) -> str:
    """SHA-256 hex of the secret. Unsalted is acceptable here ONLY because the
    secret is high-entropy and unguessable (no dictionary/rainbow risk); the
    point of hashing is so a leak of the stored value can't be replayed."""
    return hashlib.sha256(str(secret or "").encode("utf-8")).hexdigest()


def verify_secret(secret, stored_hash) -> bool:
    """Constant-time check of a presented secret against the stored hash.
    Both must be non-empty (an absent secret/hash matches nothing)."""
    if not secret or not stored_hash:
        return False
    return secrets.compare_digest(hash_secret(secret), str(stored_hash))


def build_enrollment_url(base_url, participant_id, secret) -> str:
    """Build the enrollment link. The secret goes in the URL FRAGMENT (#…),
    which browsers never transmit to the server — so the secret never reaches
    Firebase Hosting / our logs. The static landing page reads it client-side and
    hands off to the smerb:// app scheme."""
    base = str(base_url or "").rstrip("/")
    return f"{base}/enroll#pid={participant_id}&s={secret}"


def enrollment_sms_text(url) -> str:
    """SMS body delivering the enrollment link to the participant's study phone."""
    return (
        "SocialScope (Dartmouth) study: open this link on your study phone to "
        "sign in to the app.\n" + str(url) + "\n"
        "Keep this link private — it signs you in. Reply STOP to opt out of texts."
    )


def enrollment_email_subject() -> str:
    return "Your SocialScope study app sign-in link"


def enrollment_email_html(url) -> str:
    """HTML email body delivering the enrollment link."""
    safe_url = str(url)
    return (
        "<p>Hello,</p>"
        "<p>To sign in to the SocialScope study app, open this link "
        "<strong>on the phone where you installed the app</strong>:</p>"
        f'<p><a href="{safe_url}">Sign in to SocialScope</a></p>'
        "<p>If the button doesn't open the app, copy and paste this link into "
        f"your phone's browser:<br>{safe_url}</p>"
        "<p>Please keep this link private — it signs you in to your study "
        "account. You can reuse it if you reinstall or change phones.</p>"
        "<p>— SocialScope Study Team, Dartmouth College</p>"
    )
