#!/usr/bin/env python3
"""
988 Full Demo — Simulated Crisis Event
========================================
Simulates a real crisis event: calls your cell with the full IVR script
(as a participant would experience). Press 1 to be transferred to 988.

The system handles everything automatically:
  1. Calls your cell with the crisis check-in IVR
  2. You press 1 → placed on hold with reassuring messages
  3. System calls 988 test line in background
  4. Navigates 988's IVR (phone number, confirm, area code, confirm)
  5. 988 transfers to a counselor
  6. Both calls joined in a conference

Usage:
    python3 test_988_full_demo.py
    python3 test_988_full_demo.py --phone 3145551234    # override participant phone
"""

import argparse
import os
from google.cloud import secretmanager
from twilio.rest import Client

PROJECT_ID = "r01-redditx-suicide"
CELL_PHONE = os.getenv("TEST_PHONE", "")  # Set TEST_PHONE env var, e.g. +13145551234
BACKEND_URL = "https://socialscope-dashboard-api-436153481478.us-central1.run.app"


def get_secret(name):
    sm = secretmanager.SecretManagerServiceClient()
    response = sm.access_secret_version(
        request={"name": f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"}
    )
    return response.payload.data.decode("UTF-8").strip()


def main():
    parser = argparse.ArgumentParser(description="988 full demo — simulated crisis event")
    parser.add_argument("--phone", default=None, help="Override cell phone to call (default: TEST_PHONE env var)")
    parser.add_argument("--participant-id", default="demo-988", help="Participant ID for logging (default: demo-988)")
    args = parser.parse_args()

    cell = args.phone or CELL_PHONE
    if not cell:
        raise SystemExit("No phone number: pass --phone or set the TEST_PHONE env var")
    if not cell.startswith("+"):
        cell = f"+1{cell.replace('-', '').replace(' ', '')}"

    pid = args.participant_id
    action_url = f"{BACKEND_URL}/api/twilio/call-response?participantId={pid}&amp;alertId=demo-988-call"

    sid = get_secret("TWILIO_ACCOUNT_SID")
    token = get_secret("TWILIO_AUTH_TOKEN")
    from_num = get_secret("TWILIO_FROM_NUMBER")
    client = Client(sid, token)

    twiml = f'''<Response>
  <Pause length="2"/>
  <Say voice="Polly.Joanna">Hello. Thank you for picking up this call. This is an automated call from the SocialScope study.</Say>
  <Pause length="1"/>
  <Say voice="Polly.Joanna">We are calling because we recently received a response from you indicating that you may be experiencing a mental health crisis or may need additional immediate support. Your safety is very important to us. This call is intended to help you connect with support right away or let us know if the response was no longer accurate.</Say>
  <Pause length="1"/>
  <Say voice="Polly.Joanna">If you are in immediate danger or need emergency medical help, please hang up and call 911 now or go to the nearest emergency department.</Say>
  <Pause length="2"/>
  <Say voice="Polly.Joanna">You will now hear three options. Please listen carefully.</Say>
  <Pause length="1"/>
  <Gather numDigits="1" action="{action_url}" method="POST" timeout="20">
    <Say voice="Polly.Joanna">Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline, where trained crisis counselors are available to provide immediate support.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 2 if your response was an error and you are not currently in a crisis state.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support, such as from an emergency contact, 988, a therapist, a healthcare provider, or another trusted person.</Say>
  </Gather>
  <Say voice="Polly.Joanna">Again, please listen to the options.</Say>
  <Pause length="1"/>
  <Gather numDigits="1" action="{action_url}" method="POST" timeout="20">
    <Say voice="Polly.Joanna">Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 2 if your response was an error and you are not currently in a crisis state.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support.</Say>
  </Gather>
  <Say voice="Polly.Joanna">For a third and final time, here are the options.</Say>
  <Pause length="1"/>
  <Gather numDigits="1" action="{action_url}" method="POST" timeout="20">
    <Say voice="Polly.Joanna">Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 2 if your response was an error and you are not currently in a crisis state.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support.</Say>
  </Gather>
  <Say voice="Polly.Joanna">Please make your selection now.</Say>
  <Gather numDigits="1" action="{action_url}" method="POST" timeout="10"/>
  <Say voice="Polly.Joanna">We did not receive a valid response. Because your earlier response indicated that you may need immediate support, we encourage you to call or text 988 now, or call 911 if you are in immediate danger. Goodbye.</Say>
</Response>'''

    call = client.calls.create(twiml=twiml, from_=from_num, to=cell, timeout=60)
    print(f"Call initiated: {call.sid}")
    print(f"  Calling: {cell}")
    print(f"  Participant ID: {pid}")
    print()
    print("Full crisis check-in IVR will play.")
    print("  Press 1 → transfer to 988 (hold music → 988 IVR navigation → connected)")
    print("  Press 2 → recorded as error, call ends")
    print("  Press 3 → recorded as resolved with support, call ends")


if __name__ == "__main__":
    main()
