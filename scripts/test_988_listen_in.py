#!/usr/bin/env python3
"""
988 Test Call — Listen-In / Audit Mode
=======================================
Calls your cell phone FIRST, then bridges you into the 988 partner test line
so you can hear the full IVR routing and verify it works.

Hang up your cell to end both call legs.

Usage:
    python3 test_988_listen_in.py
    python3 test_988_listen_in.py --phone 3145551234       # override participant phone
    python3 test_988_listen_in.py --area-code 314           # override area code
"""

import argparse
import os
from google.cloud import secretmanager
from twilio.rest import Client

PROJECT_ID = "r01-redditx-suicide"
CELL_PHONE = os.getenv("TEST_PHONE", "")  # Your cell — gets called first (set TEST_PHONE env var)
BRIDGE_NUMBER = "+18009968362"       # 988 dedicated partner test line


def get_secret(name):
    sm = secretmanager.SecretManagerServiceClient()
    response = sm.access_secret_version(
        request={"name": f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"}
    )
    return response.payload.data.decode("UTF-8").strip()


def main():
    parser = argparse.ArgumentParser(description="988 listen-in test call")
    parser.add_argument("--phone", default=None, help="10-digit participant phone to enter (default: TEST_PHONE env var)")
    parser.add_argument("--area-code", default=None, help="3-digit area code (default: first 3 digits of phone)")
    args = parser.parse_args()

    raw_phone = args.phone or CELL_PHONE
    if not raw_phone or not CELL_PHONE:
        raise SystemExit("No phone number: pass --phone and/or set the TEST_PHONE env var")
    phone = raw_phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "").replace("+1", "")
    area_code = args.area_code or phone[:3]

    # Build DTMF sequence:
    #   2s init wait → phone digits → 10s wait → confirm (1) → 10s wait → area code → 10s wait → confirm (1)
    phone_spaced = "w".join(list(phone))
    area_spaced = "w".join(list(area_code))
    digits = f"wwww{phone_spaced}WWWWWWWWWW1WWWWWWWWWW{area_spaced}WWWWWWWWWW1"

    sid = get_secret("TWILIO_ACCOUNT_SID")
    token = get_secret("TWILIO_AUTH_TOKEN")
    from_num = get_secret("TWILIO_FROM_NUMBER")
    client = Client(sid, token)

    twiml = f'''<Response>
  <Say voice="Polly.Joanna">Listen-in test call to 988 partner line. The system will enter phone number {" ".join(list(phone))}, confirm it, enter area code {" ".join(list(area_code))}, and confirm. You will hear the full IVR routing. Hang up your cell to end both calls.</Say>
  <Pause length="1"/>
  <Say voice="Polly.Joanna">Connecting now.</Say>
  <Dial timeout="180">
    <Number sendDigits="{digits}">{BRIDGE_NUMBER}</Number>
  </Dial>
  <Say voice="Polly.Joanna">Call ended. Goodbye.</Say>
</Response>'''

    call = client.calls.create(twiml=twiml, from_=from_num, to=CELL_PHONE, timeout=60)
    print(f"Call initiated: {call.sid}")
    print(f"  Your cell: {CELL_PHONE}")
    print(f"  988 test line: {BRIDGE_NUMBER}")
    print(f"  Phone entered: {phone}")
    print(f"  Area code entered: {area_code}")
    print(f"  DTMF sequence: {digits}")
    print()
    print("Pick up your cell → hear intro → bridged to 988 → listen to IVR")
    print("Hang up cell to end both legs.")


if __name__ == "__main__":
    main()
