const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { onSchedule } = require("firebase-functions/v2/scheduler");
const { defineSecret } = require("firebase-functions/params");
const admin = require("firebase-admin");
const sgMail = require("@sendgrid/mail");

admin.initializeApp();

// ============================================================================
// Environment Configuration (dev/prod)
// Set ENVIRONMENT=dev when deploying to use dev_ prefixed collections
// Default is "prod" (no prefix)
// ============================================================================
const ENVIRONMENT = process.env.ENVIRONMENT || "prod";
const PREFIX = ENVIRONMENT === "dev" ? "dev_" : "";
function col(name) { return `${PREFIX}${name}`; }

// URLs parameterized for dev/prod
const BACKEND_URL = process.env.BACKEND_URL || "https://socialscope-dashboard-api-436153481478.us-central1.run.app";
const DASHBOARD_URL = process.env.DASHBOARD_URL || "https://socialscope-dashboard.web.app";

console.log(`[Config] Environment: ${ENVIRONMENT}, prefix: '${PREFIX}'`);

// Twilio credentials stored as Firebase secrets
const twilioAccountSid = defineSecret("TWILIO_ACCOUNT_SID");
const twilioAuthToken = defineSecret("TWILIO_AUTH_TOKEN");
const twilioFromNumber = defineSecret("TWILIO_FROM_NUMBER");

// SendGrid + Slack email config
const sendgridApiKey = defineSecret("SENDGRID_API_KEY");
const slackChannelEmail = defineSecret("SLACK_CHANNEL_EMAIL");
const alertSenderEmail = defineSecret("ALERT_SENDER_EMAIL"); // e.g., Social.Media.Wellness@dartmouth.edu

// ============================================================================
// Helper: Send email via SendGrid (for Slack channel and participant notifications)
// ============================================================================
async function sendEmail({ senderEmail, to, subject, body }) {
  sgMail.setApiKey(sendgridApiKey.value().trim());

  await sgMail.send({
    to,
    from: { email: senderEmail, name: "SocialScope Study Team" },
    subject,
    text: body,
  });
}

// ============================================================================
// Helper: Get Twilio client
// ============================================================================
function getTwilioClient() {
  return require("twilio")(
    twilioAccountSid.value(),
    twilioAuthToken.value()
  );
}

// ============================================================================
// Helper: Retry a Twilio API call with exponential backoff (1s, 2s).
// Used on safety-critical sends so a transient API failure doesn't silently
// drop an alert, escalation page, or emergency contact notification.
// ============================================================================
async function twilioWithRetry(label, fn, maxAttempts = 3) {
  let lastErr;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      console.error(`[TwilioRetry] ${label} failed (attempt ${attempt}/${maxAttempts}): ${err.message}`);
      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, Math.pow(2, attempt - 1) * 1000));
      }
    }
  }
  throw lastErr;
}

// ============================================================================
// Helper: Place the automated triage IVR call to a participant.
// Per PI design this is NOT placed immediately — the participant first gets a
// text/push window to self-resolve; the scheduler places this call ~10 min in
// if still unresolved. Digit mapping (all channels): 1=error/safe (stops),
// 2=transfer to 988, 3=already received support (stops).
// ============================================================================
async function placeParticipantTriageCall(client, fromNumber, participantId, alertId, participantPhone) {
  const actionUrl = `${BACKEND_URL}/api/twilio/call-response?participantId=${participantId}&alertId=${alertId}`;
  const ivrOptions = `
      <Say voice="Polly.Joanna">
        Press 1 if your response was an error and you are not currently in a crisis state.
      </Say>
      <Pause length="1"/>
      <Say voice="Polly.Joanna">
        Press 2 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline, where trained crisis counselors are available to provide immediate support.
      </Say>
      <Pause length="1"/>
      <Say voice="Polly.Joanna">
        Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support, such as from an emergency contact, 988, a therapist, a healthcare provider, or another trusted person.
      </Say>`;
  const gatherBlock = `<Gather numDigits="1" action="${actionUrl}" method="POST" timeout="20">${ivrOptions}</Gather>`;
  const twiml = `<Response>
    <Pause length="2"/>
    <Say voice="Polly.Joanna">Hello. Thank you for picking up this call. This is an automated call from the SocialScope study.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">We are calling because we recently received a response from you indicating that you may be experiencing a mental health crisis or may need additional immediate support. Your safety is very important to us. This call is intended to help you connect with support right away or let us know if the response was no longer accurate.</Say>
    <Pause length="1"/>
    <Say voice="Polly.Joanna">If you are in immediate danger or need emergency medical help, please hang up and call 911 now or go to the nearest emergency department.</Say>
    <Pause length="2"/>
    <Say voice="Polly.Joanna">You will now hear three options. Please listen carefully.</Say>
    <Pause length="1"/>
    ${gatherBlock}
    <Say voice="Polly.Joanna">Again, please listen to the options.</Say>
    <Pause length="1"/>
    ${gatherBlock}
    <Say voice="Polly.Joanna">For a third and final time, here are the options.</Say>
    <Pause length="1"/>
    ${gatherBlock}
    <Say voice="Polly.Joanna">Please make your selection now.</Say>
    <Gather numDigits="1" action="${actionUrl}" method="POST" timeout="10"/>
    <Say voice="Polly.Joanna">We did not receive a valid response. Because your earlier response indicated that you may need immediate support, we encourage you to call or text 988 now, or call 911 if you are in immediate danger. Goodbye.</Say>
  </Response>`;

  const call = await twilioWithRetry("calls.create", () => client.calls.create({
    twiml,
    from: fromNumber,
    to: participantPhone,
    timeout: 60,
  }));
  return { sid: call.sid, status: call.status, phone: participantPhone };
}

// ============================================================================
// Helper: Create a safety event in the audit trail system
// ============================================================================
async function createSafetyEvent(alertData, participantId, alertId) {
  const eventRef = admin.firestore().collection(col("safety_events")).doc(alertId);

  await eventRef.set({
    participantId,
    alertId,
    alertType: alertData.alertType || "confirmed_danger",
    createdAt: admin.firestore.FieldValue.serverTimestamp(),
    currentDisposition: null,
    adverseEventFlag: false,
    escalationStopped: false,
    firstResponseAt: null,
    timeToHumanContactSeconds: null,
    responses: alertData.responses || {},
    confirmationNumber: alertData.confirmationNumber || null,
    triggerQuestion: alertData.triggerQuestion || null,
  });

  // Log initial event in audit trail
  await eventRef.collection("audit_trail").doc().set({
    type: "alert_created",
    alertType: alertData.alertType || "confirmed_danger",
    loggedBy: "system",
    loggedAt: admin.firestore.FieldValue.serverTimestamp(),
  });

  console.log(`Safety event created: ${alertId}`);
  return eventRef;
}

// ============================================================================
// Helper: Get on-call roster
// ============================================================================
async function getOnCallRoster() {
  const roster = {};
  const snapshot = await admin.firestore().collection(col("oncall_roster")).get();
  snapshot.forEach((doc) => {
    roster[doc.id] = doc.data();
  });
  return roster;
}

// ============================================================================
// Helper: SMS participant that team will call
// ============================================================================
async function smsParticipant(client, participantId, fromNumber) {
  // Get participant's phone from their profile (if stored)
  const participantDoc = await admin.firestore()
    .collection(col("participants")).doc(participantId).get();

  if (!participantDoc.exists) return null;

  const participantData = participantDoc.data();
  const participantPhone = participantData.phone || participantData.phoneNumber;

  if (!participantPhone) {
    console.log(`No phone number for participant ${participantId}`);
    return null;
  }

  try {
    const result = await twilioWithRetry("messages.create", () => client.messages.create({
      body: `This is the SocialScope study team. Based on your recent check-in, ` +
            `we want to make sure you're safe. A member of our team will be calling ` +
            `you shortly.\n\nIf you are in crisis, please report to the nearest emergency room, call 911, or call 988.`,
      from: fromNumber,
      to: participantPhone.startsWith("+") ? participantPhone : `+1${participantPhone}`,
    }));
    console.log(`SMS sent to participant ${participantId}: ${result.sid}`);
    return { sid: result.sid, status: result.status, phone: participantPhone };
  } catch (err) {
    console.error(`Failed to SMS participant ${participantId}:`, err.message);
    return { error: err.message };
  }
}

// ============================================================================
// Helper: Initiate Twilio call to participant
// ============================================================================
async function callParticipant(client, participantId, fromNumber) {
  const participantDoc = await admin.firestore()
    .collection(col("participants")).doc(participantId).get();

  if (!participantDoc.exists) return null;

  const participantData = participantDoc.data();
  const participantPhone = participantData.phone || participantData.phoneNumber;

  if (!participantPhone) return null;

  try {
    // TwiML: iOS-optimized structure — pause + short ID for Live Voicemail,
    // then full message with Gather, then repeat fallback Gather.
    // Press 1 = accidental/error, Press 2 = crisis/988 conference, Press 3 = crisis + emergency contacts
    const twiml = `<Response>
      <Pause length="2"/>
      <Say voice="Polly.Joanna">SocialScope study team. Safety check-in call.</Say>
      <Pause length="3"/>
      <Say voice="Polly.Joanna">Hello, this is the SocialScope study team at Dartmouth College calling to check on you after your recent check-in. We want to make sure you are safe.</Say>
      <Pause length="2"/>
      <Gather numDigits="1" action="${BACKEND_URL}/api/twilio/call-response?participantId=${participantId}" method="POST" timeout="20">
        <Say voice="Polly.Joanna">
          Press 1 if you are safe and this was an error or accidental response.
          Press 2 if you are experiencing a crisis and would like to be connected to the 988 Suicide and Crisis Lifeline.
          Press 3 if you are experiencing a crisis and would also like us to notify your emergency contacts.
        </Say>
      </Gather>
      <Gather numDigits="1" action="${BACKEND_URL}/api/twilio/call-response?participantId=${participantId}" method="POST" timeout="15">
        <Say voice="Polly.Joanna">
          This is the SocialScope study team. We are calling about your safety.
          Press 1 if you are safe.
          Press 2 to be connected to 988.
          Press 3 for 988 plus emergency contact notification.
        </Say>
      </Gather>
      <Say voice="Polly.Joanna">We did not receive a response. A member of our team will follow up with you shortly. If you are in crisis, please report to the nearest emergency room, call 911, or call 988. Goodbye.</Say>
    </Response>`;

    const call = await twilioWithRetry("calls.create", () => client.calls.create({
      twiml,
      from: fromNumber,
      to: participantPhone.startsWith("+") ? participantPhone : `+1${participantPhone}`,
      timeout: 60,
    }));

    console.log(`Call initiated to participant ${participantId}: ${call.sid}`);
    return { sid: call.sid, status: call.status, phone: participantPhone };
  } catch (err) {
    console.error(`Failed to call participant ${participantId}:`, err.message);
    return { error: err.message };
  }
}

// ============================================================================
// Helper: Contact emergency contact
// ============================================================================
async function contactEmergencyContact(client, participantId, fromNumber) {
  // Get emergency contact from participant's safety plan in Firestore
  const participantDoc = await admin.firestore()
    .collection(col("participants")).doc(participantId).get();

  if (!participantDoc.exists) return null;

  const data = participantDoc.data();
  const emergencyPhone = data.emergencyContactPhone;
  const emergencyName = data.emergencyContactName || "emergency contact";

  if (!emergencyPhone) {
    console.log(`No emergency contact phone for participant ${participantId}`);
    return null;
  }

  try {
    // SMS emergency contact
    const smsResult = await twilioWithRetry("messages.create", () => client.messages.create({
      body: `This is the SocialScope research study team at Dartmouth College. ` +
            `We are trying to reach a study participant who listed you as an ` +
            `emergency contact. Please contact us as soon as possible. ` +
            `If you believe this person is in immediate danger, please call 911.`,
      from: fromNumber,
      to: emergencyPhone.startsWith("+") ? emergencyPhone : `+1${emergencyPhone}`,
    }));

    console.log(`Emergency contact SMS sent for ${participantId}: ${smsResult.sid}`);
    return {
      name: emergencyName,
      phone: emergencyPhone,
      smsSid: smsResult.sid,
    };
  } catch (err) {
    console.error(`Failed to contact emergency contact for ${participantId}:`, err.message);
    return { error: err.message };
  }
}

// ============================================================================
// Helper: Get participant info (phone, email, emergency contacts, name)
// Checks both the participants collection and redcap_mappings
// ============================================================================
async function getParticipantInfo(participantId) {
  const info = { phone: null, email: null, name: null, emergencyContacts: [], redcapId: null, fcmToken: null };

  // Check participants collection
  const pDoc = await admin.firestore().collection(col("participants")).doc(participantId).get();
  if (pDoc.exists) {
    const data = pDoc.data();
    info.phone = data.phone || data.phoneNumber;
    info.email = data.email;
    info.name = data.name || data.participantName;
    info.fcmToken = data.fcmToken || null;
    info.emergencyContacts = data.emergencyContacts || [];
    if (data.emergencyContactPhone) {
      info.emergencyContacts.push({
        name: data.emergencyContactName || "Emergency Contact",
        phone: data.emergencyContactPhone,
      });
    }
  }

  // Check valid_participants for REDCap link
  const vDoc = await admin.firestore().collection(col("valid_participants")).doc(participantId).get();
  if (vDoc.exists) {
    info.redcapId = vDoc.data().redcap_record_id;
  }

  // Check redcap_mappings for reverse lookup
  if (!info.redcapId) {
    const mappings = await admin.firestore().collection(col("redcap_mappings"))
      .where("app_participant_id", "==", participantId).limit(1).get();
    if (!mappings.empty) {
      info.redcapId = mappings.docs[0].id;
    }
  }

  return info;
}

// ============================================================================
// Helper: Notify emergency contacts via SMS and call
// ============================================================================
async function notifyEmergencyContacts(client, participantId, participantInfo, fromNumber, safetyEventRef) {
  const results = [];

  for (const contact of (participantInfo.emergencyContacts || [])) {
    if (!contact.phone) continue;

    const participantName = participantInfo.name || `Study participant ${participantId}`;
    const contactPhone = contact.phone.startsWith("+") ? contact.phone : `+1${contact.phone}`;

    // SMS first
    try {
      const smsResult = await twilioWithRetry("messages.create", () => client.messages.create({
        body: `This is the SocialScope research study team at Dartmouth College. ` +
              `${participantName} has designated you (${contact.name}) as an emergency contact ` +
              `and has indicated they are currently experiencing a mental health crisis. ` +
              `We encourage you to reach out to them to provide support. ` +
              `If you believe they are in immediate danger, please call 911. ` +
              `You can also call the 988 Suicide & Crisis Lifeline.`,
        from: fromNumber,
        to: contactPhone,
      }));
      results.push({ name: contact.name, phone: contact.phone, smsSid: smsResult.sid, type: "sms" });
    } catch (err) {
      results.push({ name: contact.name, phone: contact.phone, error: err.message, type: "sms" });
    }

    // Voice call with voicemail
    try {
      const callResult = await twilioWithRetry("calls.create", () => client.calls.create({
        twiml: `<Response><Say voice="alice">` +
          `Hello ${contact.name}. This is the SocialScope research study team at Dartmouth College. ` +
          `${participantName} has designated you as an emergency contact and has indicated ` +
          `they are currently experiencing a mental health crisis. ` +
          `We encourage you to proactively reach out to them to provide support. ` +
          `If you believe they are in immediate danger, please call 911. ` +
          `Thank you.</Say></Response>`,
        from: fromNumber,
        to: contactPhone,
        timeout: 30,
      }));
      results.push({ name: contact.name, phone: contact.phone, callSid: callResult.sid, type: "call" });
    } catch (err) {
      results.push({ name: contact.name, phone: contact.phone, error: err.message, type: "call" });
    }

    // Log to audit trail
    if (safetyEventRef) {
      await safetyEventRef.collection("audit_trail").doc().set({
        type: "emergency_contact_notified",
        contactName: contact.name,
        contactPhone: contact.phone,
        results: results.filter(r => r.phone === contact.phone),
        loggedBy: "system",
        loggedAt: admin.firestore.FieldValue.serverTimestamp(),
      });
    }
  }

  return results;
}

// ============================================================================
// Main Safety Alert Trigger
// ============================================================================
const safetyAlertFnName = ENVIRONMENT === "dev" ? "dev_onSafetyAlert" : "onSafetyAlert";
exports[safetyAlertFnName] = onDocumentCreated(
  {
    document: `${col("participants")}/{participantId}/safety_alerts/{alertId}`,
    secrets: [
      twilioAccountSid, twilioAuthToken, twilioFromNumber,
      sendgridApiKey, slackChannelEmail, alertSenderEmail,
    ],
  },
  async (event) => {
    const snapshot = event.data;
    if (!snapshot) {
      console.log("No data in safety alert document");
      return;
    }

    const alertData = snapshot.data();
    const { participantId, alertId } = event.params;

    const timestamp = alertData.triggeredAt
      ? alertData.triggeredAt.toDate().toLocaleString("en-US", {
          timeZone: "America/New_York",
        })
      : new Date().toLocaleString("en-US", { timeZone: "America/New_York" });

    const alertType = alertData.alertType || "confirmed_danger";
    const isConfirmedDanger = alertData.confirmedDanger === true;
    const isFallback = alertType === "incomplete_checkin_fallback";
    const isWalkAway = alertType === "unresolved_walkaway";

    // ================================================================
    // Step 1: Create safety event for audit trail
    // ================================================================
    let safetyEventRef;
    try {
      safetyEventRef = await createSafetyEvent(alertData, participantId, alertId);
    } catch (err) {
      console.error("Failed to create safety event:", err);
    }

    // ================================================================
    // Step 2: Notify Slack channel (via email)
    // ================================================================
    let slackResult = null;
    let slackError = null;

    const slackEmail = slackChannelEmail.value();
    const senderEmailVal = alertSenderEmail.value();
    const sgKey = sendgridApiKey.value();

    if (slackEmail && senderEmailVal && sgKey) {
      try {
        const alertLabel = isConfirmedDanger
          ? "CONFIRMED DANGER"
          : isWalkAway
            ? "POTENTIAL RISK — Participant walked away from check-in"
            : isFallback
              ? "INCOMPLETE CHECK-IN (high-risk responses)"
              : "SAFETY ALERT";

        await sendEmail({
          senderEmail: senderEmailVal,
          to: slackEmail,
          subject: `[${alertLabel}] Participant ${participantId}`,
          body:
            `[SocialScope ${alertLabel}]\n\n` +
            `Participant: ${participantId}\n` +
            `Time: ${timestamp}\n` +
            `Alert Type: ${alertType}\n` +
            (alertData.confirmationNumber ? `Confirmation #: ${alertData.confirmationNumber}\n` : "") +
            (alertData.triggerQuestion ? `Trigger Question: ${alertData.triggerQuestion}\n` : "") +
            `\nA participant endorsed imminent self-harm risk during check-in.\n\n` +
            `View dashboard: ${DASHBOARD_URL}\n` +
            `Alert ID: ${alertId}`,
        });

        slackResult = "sent";
        console.log(`Slack notification sent for alert ${alertId}`);
      } catch (err) {
        slackError = err.message;
        console.error(`Slack notification failed:`, err.message);
      }
    }

    // ================================================================
    // Step 3: Notify on-call team via SMS (uses on-call roster)
    // For CONFIRMED DANGER: on-call is NOT paged immediately — automated
    //   participant outreach (SMS + IVR call) happens first. On-call is
    //   paged by the escalation scheduler after 15 min if unresolved.
    // For other alert types (fallback, walk-away): on-call is paged immediately.
    // ================================================================
    const roster = await getOnCallRoster();
    const recipients = [];

    // Build recipient list from on-call roster (primary first, then backup, then PI)
    for (const role of ["primary", "backup", "pi"]) {
      const person = roster[role];
      if (person && person.phone) {
        recipients.push({ phone: person.phone, name: person.name || role, role });
      }
    }

    // Legacy fallback: also check alert_recipients collection
    try {
      const legacySnapshot = await admin.firestore()
        .collection(col("alert_recipients")).get();
      legacySnapshot.forEach((doc) => {
        const data = doc.data();
        if (!recipients.find(r => r.phone === doc.id)) {
          recipients.push({ phone: doc.id, name: data.name || null, role: "legacy" });
        }
      });
    } catch (e) { /* ignore legacy collection errors */ }

    if (alertData.pageTarget && !recipients.find(r => r.phone === alertData.pageTarget)) {
      recipients.push({ phone: alertData.pageTarget, name: "Legacy Target", role: "legacy" });
    }

    let smsResults = [];
    let smsErrors = [];

    // For confirmed danger: skip immediate on-call page — automated outreach first
    // Escalation scheduler will page on-call after 15 min if participant doesn't resolve
    if (recipients.length > 0 && !isConfirmedDanger) {
      try {
        const client = getTwilioClient();
        const alertLabel = isConfirmedDanger
          ? "CONFIRMED DANGER"
          : isWalkAway
            ? "POTENTIAL RISK (walked away)"
            : isFallback
              ? "INCOMPLETE CHECK-IN"
              : "ALERT";

        const smsBody =
          `[SocialScope ${alertLabel}]\n` +
          `Participant: ${participantId}\n` +
          `Time: ${timestamp}\n` +
          (isConfirmedDanger
            ? `Participant CONFIRMED they are in immediate danger.\n`
            : isWalkAway
              ? `POTENTIAL RISK: Participant gave concerning responses then walked away. Not confirmed — please follow up.\n`
              : isFallback
                ? `High-risk responses, exited before confirmation.\n`
                : `Endorsed imminent self-harm risk.\n`) +
          `\nReply ACK to acknowledge.\n` +
          `Reply SAFE, SUPPORT, NOREACH, FALSE, 988, or ER to log disposition.\n` +
          `Dashboard: ${DASHBOARD_URL}`;

        for (const recipient of recipients) {
          try {
            const result = await twilioWithRetry("messages.create", () => client.messages.create({
              body: smsBody,
              from: twilioFromNumber.value(),
              to: `+1${recipient.phone}`,
            }));
            smsResults.push({
              phone: recipient.phone,
              name: recipient.name,
              role: recipient.role,
              sid: result.sid,
              status: result.status,
            });
          } catch (recipientError) {
            smsErrors.push({
              phone: recipient.phone,
              name: recipient.name,
              error: recipientError.message,
            });
          }
        }
      } catch (error) {
        console.error("Error initializing Twilio client:", error);
        smsErrors.push({ error: error.message });
      }
    }

    // ================================================================
    // Step 4: Automated participant outreach (confirmed danger only)
    //
    // Sequence:
    //   4a. SMS participant: "We'll be calling. Reply ERROR or 1 if accidental."
    //   4b. IVR call: Press 1 = error, Press 2 = crisis (warm handoff 988),
    //       Press 3 = crisis + notify emergency contacts
    //   4c. If no resolution from 4a/4b → page on-call with full history
    //   Emergency contacts notified if press 2 or press 3 in IVR
    // ================================================================
    let participantSmsResult = null;
    let participantCallResult = null;
    let emergencyContactResults = null;

    // Get enriched participant info (phone, email, emergency contacts, REDCap ID)
    const participantInfo = isConfirmedDanger
      ? await getParticipantInfo(participantId)
      : null;

    if (isConfirmedDanger && participantInfo) {
      try {
        const client = getTwilioClient();
        const fromNumber = twilioFromNumber.value();

        // 4a. SMS participant — includes error acknowledgment option
        if (participantInfo.phone) {
          const participantPhone = participantInfo.phone.startsWith("+")
            ? participantInfo.phone : `+1${participantInfo.phone}`;
          try {
            const smsResult = await twilioWithRetry("messages.create", () => client.messages.create({
              body: `This is the SocialScope study team at Dartmouth College. ` +
                    `Based on your recent check-in, we want to make sure you're safe. ` +
                    `A member of our team will be calling you shortly.\n\n` +
                    `If this was an error, reply ERROR or 1.\n\n` +
                    `If you are in crisis, please report to the nearest emergency room, call 911, or call 988.`,
              from: fromNumber,
              to: participantPhone,
            }));
            participantSmsResult = { sid: smsResult.sid, status: smsResult.status, phone: participantInfo.phone };
          } catch (err) {
            participantSmsResult = { error: err.message };
          }

          if (safetyEventRef) {
            await safetyEventRef.collection("audit_trail").doc().set({
              type: "participant_sms_sent",
              result: participantSmsResult,
              message: "Initial outreach SMS with ERROR reply option",
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          }
        }

        // 4a-push. Send an in-app push so the participant can confirm they're
        // at risk or mark it an error directly in the app. An "error" response
        // stops escalation (same as texting 1/ERROR); writes go to the
        // safety_responses subcollection that onParticipantSafetyResponse reacts to.
        if (participantInfo.fcmToken) {
          try {
            await admin.messaging().send({
              token: participantInfo.fcmToken,
              notification: {
                title: "Checking in on you",
                body: "Your recent check-in indicated you may be at risk. "
                  + "Tap to let us know how you're doing.",
              },
              data: { type: "safety_self_confirm", alertId: String(alertId) },
              apns: {
                payload: { aps: { sound: "default", "interruption-level": "time-sensitive" } },
              },
              android: { priority: "high", notification: { channelId: "push_notifications" } },
            });
            if (safetyEventRef) {
              await safetyEventRef.collection("audit_trail").doc().set({
                type: "participant_push_sent",
                message: "Safety self-confirmation push (confirm / error)",
                loggedBy: "system",
                loggedAt: admin.firestore.FieldValue.serverTimestamp(),
              });
            }
          } catch (err) {
            console.error(`[SafetyPush] Failed to send to ${participantId}: ${err.message}`);
          }
        }

        // 4b. The automated IVR triage call is intentionally NOT placed here.
        // Per PI design the participant first gets a text/push window to
        // self-resolve; the checkEscalation scheduler places the call ~10 min
        // in (IVR_CALL_DELAY_MIN) if still unresolved, and pages on-call only
        // after the call fails to resolve (no pickup / no 988 transfer).

        // 4c. Email participant
        if (participantInfo.email && senderEmailVal && sgKey) {
          try {
            await sendEmail({
              senderEmail: senderEmailVal,
                  to: participantInfo.email,
              subject: "SocialScope Study Team - Checking In",
              body:
                `Hello,\n\n` +
                `This is the SocialScope study team at Dartmouth College. ` +
                `Based on your recent check-in, we want to make sure you're safe.\n\n` +
                `A member of our team will be reaching out to you shortly.\n\n` +
                `If you are in immediate danger, please:\n` +
                `- Call 988 (Suicide & Crisis Lifeline)\n` +
                `- Text HOME to 741741 (Crisis Text Line)\n` +
                `- Call 911 or go to your nearest emergency room\n\n` +
                `- SocialScope Study Team, Dartmouth College`,
            });

            if (safetyEventRef) {
              await safetyEventRef.collection("audit_trail").doc().set({
                type: "participant_email_sent",
                participantEmail: participantInfo.email,
                loggedBy: "system",
                loggedAt: admin.firestore.FieldValue.serverTimestamp(),
              });
            }
          } catch (err) {
            console.error("Failed to email participant:", err);
          }
        }

        // Store participant info on the safety event for on-call context
        // Filter out undefined values (Firestore rejects them)
        if (safetyEventRef) {
          const contextUpdate = {};
          if (participantInfo.phone) contextUpdate.participantPhone = participantInfo.phone;
          if (participantInfo.email) contextUpdate.participantEmail = participantInfo.email;
          if (participantInfo.name) contextUpdate.participantName = participantInfo.name;
          if (participantInfo.redcapId) contextUpdate.redcapId = participantInfo.redcapId;
          contextUpdate.emergencyContactCount = (participantInfo.emergencyContacts || []).length;
          if (Object.keys(contextUpdate).length > 0) {
            await safetyEventRef.update(contextUpdate);
          }
        }
      } catch (err) {
        console.error("Participant outreach error:", err);
      }
    }

    // ================================================================
    // Step 5: Update alert document with all results
    // ================================================================
    await snapshot.ref.update({
      handled: smsResults.length > 0 || slackResult === "sent" || (participantSmsResult && participantSmsResult.sid) || (participantCallResult && participantCallResult.sid),
      smsResults: smsResults.length > 0 ? smsResults : null,
      smsErrors: smsErrors.length > 0 ? smsErrors : null,
      recipientCount: recipients.length,
      successCount: smsResults.length,
      slackResult,
      slackError,
      participantSmsResult,
      participantCallResult,
      emergencyContactResults,
      safetyEventId: alertId,
      handledAt: admin.firestore.FieldValue.serverTimestamp(),
    });

    console.log(
      `Safety alert ${alertId}: type=${alertType}, ` +
      `SMS ${smsResults.length}/${recipients.length}, ` +
      `Slack: ${slackResult || "skipped"}, ` +
      `Participant outreach: ${isConfirmedDanger ? "yes" : "skipped"}`
    );
  }
);


// ============================================================================
// Escalation Scheduler: Check for unresponded safety events
// Runs every 5 minutes to check if on-call has responded
// ============================================================================
// ============================================================================
// Participant in-app safety response (confirm / error)
//
// Fires when the app writes participants/{id}/safety_responses/{alertId} after
// the participant taps a choice on the safety self-confirmation push. The
// safety_event doc id equals the alertId (createSafetyEvent uses .doc(alertId)),
// so we resolve it directly. "error" stops escalation exactly like an SMS
// ERROR / IVR press-1; "confirmed" is logged and lets escalation continue.
// ============================================================================
const safetyResponseFnName = ENVIRONMENT === "dev" ? "dev_onParticipantSafetyResponse" : "onParticipantSafetyResponse";
exports[safetyResponseFnName] = onDocumentCreated(
  `${col("participants")}/{participantId}/safety_responses/{alertId}`,
  async (event) => {
    const snapshot = event.data;
    if (!snapshot) return;
    const data = snapshot.data();
    const { participantId, alertId } = event.params;
    const response = data.response;

    const eventRef = admin.firestore().collection(col("safety_events")).doc(alertId);
    const eventSnap = await eventRef.get();
    if (!eventSnap.exists) {
      console.warn(`[SafetyResponse] No safety_event ${alertId} for ${participantId} — logging only`);
    }

    if (response === "error") {
      // Stop escalation — same disposition the SMS ERROR / IVR press-1 paths set
      if (eventSnap.exists) {
        await eventRef.update({
          currentDisposition: "false_alarm",
          escalationStopped: true,
          participantResolved: true,
          participantResolvedAt: admin.firestore.FieldValue.serverTimestamp(),
          participantResolvedVia: "app_push_error",
          lastRespondedAt: admin.firestore.FieldValue.serverTimestamp(),
        });
        await eventRef.collection("audit_trail").doc().set({
          type: "participant_app_response",
          response: "error_not_in_crisis",
          source: "app_push",
          loggedBy: "system",
          loggedAt: admin.firestore.FieldValue.serverTimestamp(),
        });
      }
      console.log(`[SafetyResponse] ${participantId} marked alert ${alertId} an error — escalation stopped`);
    } else if (response === "confirmed") {
      // Confirmed they could use support — DO NOT stop escalation; record the
      // acknowledgement so on-call sees the participant engaged.
      if (eventSnap.exists) {
        await eventRef.update({
          participantConfirmedViaApp: true,
          lastRespondedAt: admin.firestore.FieldValue.serverTimestamp(),
        });
        await eventRef.collection("audit_trail").doc().set({
          type: "participant_app_response",
          response: "confirmed_needs_support",
          source: "app_push",
          loggedBy: "system",
          loggedAt: admin.firestore.FieldValue.serverTimestamp(),
        });
      }
      console.log(`[SafetyResponse] ${participantId} confirmed need for support on alert ${alertId}`);
    } else {
      console.warn(`[SafetyResponse] Unknown response '${response}' for ${alertId}`);
    }
  }
);

// On-call paging ladder (PI-defined). A participant error OR a confirmed 988
// connection resolves the event upstream (escalationStopped=true) so it never
// reaches the ladder. Otherwise: page primary after the response window, then
// backup if no ACK, then PI if still no ACK.
// Confirmed-danger timeline (PI-specified): participant gets a text/push window
// to self-resolve; the automated triage IVR call is placed ~10 min in; on-call
// is paged only after that call fails to resolve (no pickup / no 988 transfer).
const IVR_CALL_DELAY_MIN = 10;       // place the participant triage call this long after the alert
const PRIMARY_PAGE_MIN = 15;         // page primary if still unresolved after the call has had a chance
const BACKUP_AFTER_MIN = 15;         // page backup this long after primary, if unacknowledged
const PI_AFTER_MIN = 30;             // page PI this long after backup, if unacknowledged
const ACK_REMINDER_THROTTLE_MIN = 30; // Slack nudge cadence once acknowledged but no final disposition
const ESCALATION_MAX_AGE_MIN = 1440;  // stop acting on events older than 24h

const escalationFnName = ENVIRONMENT === "dev" ? "dev_checkEscalation" : "checkEscalation";
exports[escalationFnName] = onSchedule(
  {
    schedule: "every 5 minutes",
    secrets: [twilioAccountSid, twilioAuthToken, twilioFromNumber,
              sendgridApiKey, slackChannelEmail, alertSenderEmail],
    timeZone: "America/New_York",
  },
  async () => {
    try {
      const now = new Date();

      // Find safety events that are still open (not fully resolved)
      const eventsSnapshot = await admin.firestore()
        .collection(col("safety_events"))
        .where("escalationStopped", "==", false)
        .get();

      if (eventsSnapshot.empty) return;

      const roster = await getOnCallRoster();
      const client = getTwilioClient();
      const fromNumber = twilioFromNumber.value();

      for (const doc of eventsSnapshot.docs) {
        const eventData = doc.data();
        const createdAt = eventData.createdAt?.toDate?.() || new Date();
        const acknowledged = eventData.acknowledged === true;
        const currentDisposition = eventData.currentDisposition;

        // Every event here is unresolved (escalationStopped==false): not an
        // error, not a confirmed 988 connection, no final disposition.
        const minutesSinceCreation = (now.getTime() - createdAt.getTime()) / (60 * 1000);

        // Don't act on stale events (on-call was long since paged or it's abandoned)
        if (minutesSinceCreation > ESCALATION_MAX_AGE_MIN) continue;

        // Confirmed-danger alerts skip the initial page (automated participant
        // outreach + 988 triage runs first), so the ladder starts at the
        // response window: primary at +5, backup +15, PI +30. Non-confirmed
        // alerts (walk-away/fallback) were already paged to ALL on-call at
        // creation, so we only escalate backup/PI if still unacknowledged.
        const isConfirmedDanger = (eventData.alertType || "confirmed_danger") === "confirmed_danger";

        // Place the automated triage IVR call ~10 min in, if the participant
        // hasn't already self-resolved via text/push. (Confirmed-danger only;
        // non-confirmed alerts don't get the triage-call flow.)
        if (isConfirmedDanger && !eventData.participantCallPlaced &&
            minutesSinceCreation >= IVR_CALL_DELAY_MIN && eventData.participantPhone) {
          const phone = eventData.participantPhone.startsWith("+")
            ? eventData.participantPhone : `+1${eventData.participantPhone}`;
          let callResult;
          try {
            callResult = await placeParticipantTriageCall(
              client, fromNumber, eventData.participantId, doc.id, phone);
          } catch (err) {
            callResult = { error: err.message };
            console.error(`[Escalation] Triage call failed for ${eventData.participantId}: ${err.message}`);
          }
          await doc.ref.update({
            participantCallPlaced: true,
            participantCallPlacedAt: admin.firestore.FieldValue.serverTimestamp(),
          });
          await doc.ref.collection("audit_trail").doc().set({
            type: "participant_call_initiated",
            result: callResult,
            message: "Triage IVR call placed ~10 min after alert (1=error, 2=988, 3=already supported)",
            loggedBy: "system",
            loggedAt: admin.firestore.FieldValue.serverTimestamp(),
          });
        }

        if (!acknowledged) {
          const due = [];
          if (isConfirmedDanger) {
            if (minutesSinceCreation >= PRIMARY_PAGE_MIN && !eventData.primaryPaged) {
              due.push(["primary", roster.primary, "primaryPaged"]);
            }
            if (minutesSinceCreation >= PRIMARY_PAGE_MIN + BACKUP_AFTER_MIN && !eventData.backupEscalated) {
              due.push(["backup", roster.backup, "backupEscalated"]);
            }
            if (minutesSinceCreation >= PRIMARY_PAGE_MIN + BACKUP_AFTER_MIN + PI_AFTER_MIN && !eventData.piEscalated) {
              due.push(["pi", roster.pi, "piEscalated"]);
            }
          } else {
            // Already paged everyone at creation — re-escalate if unacknowledged.
            if (minutesSinceCreation >= BACKUP_AFTER_MIN && !eventData.backupEscalated) {
              due.push(["backup", roster.backup, "backupEscalated"]);
            }
            if (minutesSinceCreation >= BACKUP_AFTER_MIN + PI_AFTER_MIN && !eventData.piEscalated) {
              due.push(["pi", roster.pi, "piEscalated"]);
            }
          }

          for (const [level, target, flag] of due) {
            if (!target || !target.phone) {
              // Roster gap — make it loud so no crisis goes unpaged silently.
              console.error(`[Escalation] No ${level} on-call configured — cannot page for ${eventData.participantId}`);
              continue;
            }
            try {
              await twilioWithRetry("messages.create", () => client.messages.create({
                body: `[SocialScope ESCALATION - ${level.toUpperCase()}]\n` +
                      `Safety event for participant ${eventData.participantId} ` +
                      `is UNRESOLVED after ${Math.round(minutesSinceCreation)} min ` +
                      `(participant did not confirm safe and was not connected to 988).\n` +
                      `Reply ACK to take it.\n` +
                      `Reply SAFE, SUPPORT, NOREACH, FALSE, 988, or ER to log disposition.\n` +
                      `Dashboard: ${DASHBOARD_URL}`,
                from: fromNumber,
                to: `+1${target.phone}`,
              }));
              const u = {};
              u[flag] = true;
              u[`${flag}At`] = admin.firestore.FieldValue.serverTimestamp();
              await doc.ref.update(u);
              await doc.ref.collection("audit_trail").doc().set({
                type: "escalation",
                escalationLevel: level,
                escalatedTo: target.name || level,
                reason: "unresolved",
                minutesSinceCreation: Math.round(minutesSinceCreation),
                loggedBy: "system",
                loggedAt: admin.firestore.FieldValue.serverTimestamp(),
              });
              console.log(`[Escalation] Paged ${level} for ${eventData.participantId} at ${Math.round(minutesSinceCreation)} min`);
            } catch (err) {
              console.error(`[Escalation] Page ${level} failed for ${eventData.participantId}:`, err.message);
            }
          }
        } else {
          // ACKNOWLEDGED: on-call owns it. No secondary paging (PI decision).
          // Nudge via Slack to log a final disposition if still open, throttled.
          const hasFinalDisposition = currentDisposition && currentDisposition !== "ongoing";
          if (!hasFinalDisposition) {
            const lastReminder = eventData.lastAckReminderAt?.toDate?.();
            const minsSinceReminder = lastReminder
              ? (now.getTime() - lastReminder.getTime()) / (60 * 1000)
              : Infinity;
            if (minsSinceReminder >= ACK_REMINDER_THROTTLE_MIN) {
              try {
                await sendEmail({
                  senderEmail: alertSenderEmail.value(),
                  to: slackChannelEmail.value(),
                  subject: `[SocialScope] Disposition still needed — participant ${eventData.participantId}`,
                  body: `A safety event for participant ${eventData.participantId} was acknowledged by ` +
                        `on-call ${Math.round(minutesSinceCreation)} min ago but has no final disposition yet.\n\n` +
                        `Please log the outcome in the dashboard: ${DASHBOARD_URL}`,
                });
                await doc.ref.update({ lastAckReminderAt: admin.firestore.FieldValue.serverTimestamp() });
                await doc.ref.collection("audit_trail").doc().set({
                  type: "disposition_reminder",
                  channel: "slack",
                  minutesSinceCreation: Math.round(minutesSinceCreation),
                  loggedBy: "system",
                  loggedAt: admin.firestore.FieldValue.serverTimestamp(),
                });
                console.log(`[Escalation] Slack disposition reminder for ${eventData.participantId}`);
              } catch (err) {
                console.error(`[Escalation] Slack reminder failed for ${eventData.participantId}:`, err.message);
              }
            }
          }
        }
      }
    } catch (err) {
      console.error("Escalation check error:", err);
    }

    // ================================================================
    // Emergency Contact Auto-Notification (5-minute no-reply escalation)
    //
    // After the initial crisis SMS is sent to a participant, if they do NOT
    // reply ERROR/1 within 5 minutes, automatically notify their emergency
    // contacts via text (at 5 min) and voice call (at ~8 min / 3 min after text).
    //
    // The message tells the emergency contact:
    //   - The participant's name
    //   - They have been designated as an emergency contact
    //   - The participant reported experiencing a mental health crisis
    //   - Encourage them to reach out and support the participant
    //   - If in immediate danger → call 911
    // ================================================================
    try {
      const now = new Date();  // Re-declare for this scope

      // Bound by creation time (single-field index, no composite needed) and
      // filter escalationStopped in code — only the last hour is actionable,
      // so never-closed historical events don't inflate reads forever.
      const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
      const allOpenEvents = await admin.firestore()
        .collection(col("safety_events"))
        .where("createdAt", ">=", oneHourAgo)
        .get();

      for (const doc of allOpenEvents.docs) {
        const eventData = doc.data();

        // Filtered in code (query is time-bounded on a single-field index)
        if (eventData.escalationStopped === true) continue;

        // Digit mapping (all channels): 1 = error/safe (stops escalation),
        // 2 = transfer to 988, 3 = already received support (stops escalation).
        // A confirmed error (press 1 / SMS ERROR / app push) or a confirmed 988
        // connection sets escalationStopped/participantResolved above, so those
        // events are already filtered out. Emergency-contact auto-notify below
        // fires only for events that remain genuinely unresolved.
        if (eventData.participantResolved === true) continue;

        // Skip if this isn't a confirmed danger event that was texted
        if (!eventData.participantPhone) continue;

        // Determine when the participant was first contacted (SMS sent timestamp)
        const createdAt = eventData.createdAt?.toDate?.() || null;
        if (!createdAt) continue;

        const minutesSinceCreation = (now.getTime() - createdAt.getTime()) / (60 * 1000);

        // Only auto-notify for events created within the last 60 minutes.
        // Older events are stale — if they weren't resolved within an hour,
        // the on-call escalation pathway has already taken over.
        if (minutesSinceCreation > 60) continue;

        // ─── TEXT emergency contacts once on-call escalation begins ───
        // Aligned with PRIMARY_PAGE_MIN so family is contacted only after the
        // participant's own text/push window AND the automated triage call have
        // had a chance — not before we've even tried calling the participant.
        if (minutesSinceCreation >= PRIMARY_PAGE_MIN && !eventData.emergencyContactAutoTextSent) {
          console.log(`[EmergencyContactAuto] escalation reached for ${eventData.participantId}, texting emergency contacts`);

          // Get participant info for emergency contacts
          const participantInfo = await getParticipantInfo(eventData.participantId);

          if (participantInfo.emergencyContacts && participantInfo.emergencyContacts.length > 0) {
            const client = getTwilioClient();
            const fromNumber = twilioFromNumber.value();
            const participantName = participantInfo.name || `Study participant ${eventData.participantId}`;
            // Contacts are independent — send in parallel so retry backoff on
            // one slow contact can't push the run past its timeout (which would
            // re-send duplicate crisis texts on the next run).
            const textResults = await Promise.all(participantInfo.emergencyContacts
              .filter((c) => c.phone)
              .map(async (contact) => {
              const contactPhone = contact.phone.startsWith("+") ? contact.phone : `+1${contact.phone}`;
              const contactName = contact.name || "emergency contact";

              try {
                const smsResult = await twilioWithRetry("messages.create", () => client.messages.create({
                  body: `This is the SocialScope research study team at Dartmouth College. ` +
                        `${participantName} has designated you (${contactName}) as an emergency contact ` +
                        `and has reported that they are currently experiencing a mental health crisis to our study team. ` +
                        `We encourage you to reach out to ${participantName} to try to check in on them and provide support. ` +
                        `If you believe they are in immediate danger, please call 911. ` +
                        `You can also encourage them to call 988 (Suicide & Crisis Lifeline). ` +
                        `Thank you for your help.`,
                  from: fromNumber,
                  to: contactPhone,
                }));
                console.log(`[EmergencyContactAuto] Text sent to ${contactName} (${contact.phone}): ${smsResult.sid}`);
                return { name: contactName, phone: contact.phone, sid: smsResult.sid };
              } catch (err) {
                console.error(`[EmergencyContactAuto] Text failed to ${contactName}: ${err.message}`);
                return { name: contactName, phone: contact.phone, error: err.message };
              }
            }));

            // Mark as sent so we don't repeat
            await doc.ref.update({
              emergencyContactAutoTextSent: true,
              emergencyContactAutoTextSentAt: admin.firestore.FieldValue.serverTimestamp(),
              emergencyContactAutoTextResults: textResults,
            });

            await doc.ref.collection("audit_trail").doc().set({
              type: "emergency_contact_auto_text",
              reason: "participant_no_reply_5min",
              minutesSinceAlert: Math.round(minutesSinceCreation),
              contactsNotified: textResults.length,
              results: textResults,
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          } else {
            console.log(`[EmergencyContactAuto] No emergency contacts found for ${eventData.participantId}`);
            await doc.ref.update({ emergencyContactAutoTextSent: true, emergencyContactAutoTextSkipped: "no_contacts" });
          }
        }

        // ─── CALL emergency contacts ~3 min after texting them ───
        if (minutesSinceCreation >= PRIMARY_PAGE_MIN + 3 && eventData.emergencyContactAutoTextSent && !eventData.emergencyContactAutoCallSent) {
          console.log(`[EmergencyContactAuto] calling emergency contacts for ${eventData.participantId}`);

          const participantInfo = await getParticipantInfo(eventData.participantId);

          if (participantInfo.emergencyContacts && participantInfo.emergencyContacts.length > 0) {
            const client = getTwilioClient();
            const fromNumber = twilioFromNumber.value();
            const participantName = participantInfo.name || `Study participant ${eventData.participantId}`;
            // Parallel for the same reason as the text branch above
            const callResults = await Promise.all(participantInfo.emergencyContacts
              .filter((c) => c.phone)
              .map(async (contact) => {
              const contactPhone = contact.phone.startsWith("+") ? contact.phone : `+1${contact.phone}`;
              const contactName = contact.name || "emergency contact";

              try {
                const callResult = await twilioWithRetry("calls.create", () => client.calls.create({
                  twiml: `<Response>` +
                    `<Pause length="2"/>` +
                    `<Say voice="Polly.Joanna">Hello ${contactName}. This is the SocialScope research study team at Dartmouth College.</Say>` +
                    `<Pause length="1"/>` +
                    `<Say voice="Polly.Joanna">${participantName} has designated you as an emergency contact for our study, ` +
                    `and has reported that they are currently experiencing a mental health crisis to our study team.</Say>` +
                    `<Pause length="1"/>` +
                    `<Say voice="Polly.Joanna">We encourage you to reach out to ${participantName} to try to check in on them and provide support.</Say>` +
                    `<Pause length="1"/>` +
                    `<Say voice="Polly.Joanna">If you believe they are in immediate danger, please call 911. ` +
                    `You can also encourage them to call 988, the Suicide and Crisis Lifeline.</Say>` +
                    `<Pause length="1"/>` +
                    `<Say voice="Polly.Joanna">Thank you for your help. Goodbye.</Say>` +
                    `</Response>`,
                  from: fromNumber,
                  to: contactPhone,
                  timeout: 60,
                }));
                console.log(`[EmergencyContactAuto] Call placed to ${contactName} (${contact.phone}): ${callResult.sid}`);
                return { name: contactName, phone: contact.phone, sid: callResult.sid };
              } catch (err) {
                console.error(`[EmergencyContactAuto] Call failed to ${contactName}: ${err.message}`);
                return { name: contactName, phone: contact.phone, error: err.message };
              }
            }));

            // Mark as sent
            await doc.ref.update({
              emergencyContactAutoCallSent: true,
              emergencyContactAutoCallSentAt: admin.firestore.FieldValue.serverTimestamp(),
              emergencyContactAutoCallResults: callResults,
            });

            await doc.ref.collection("audit_trail").doc().set({
              type: "emergency_contact_auto_call",
              reason: "participant_no_reply_8min",
              minutesSinceAlert: Math.round(minutesSinceCreation),
              contactsCalled: callResults.length,
              results: callResults,
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          } else {
            await doc.ref.update({ emergencyContactAutoCallSent: true, emergencyContactAutoCallSkipped: "no_contacts" });
          }
        }
      }
    } catch (err) {
      console.error("Emergency contact auto-notification error:", err);
    }

    // ================================================================
    // Check for unresolved pending safety confirmations (walk-away detection)
    // If a participant exceeded a threshold but walked away without
    // answering the yes/no, send a "potential risk" alert after 15 minutes.
    // ================================================================
    try {
      const now = new Date();  // Re-declare for this scope
      const fifteenMinAgo = new Date(now.getTime() - 15 * 60 * 1000);

      // Get all participants
      const participantsSnapshot = await admin.firestore()
        .collection(col("participants")).get();

      for (const participantDoc of participantsSnapshot.docs) {
        const pid = participantDoc.id;

        // Check for unresolved pending confirmations
        const pendingSnapshot = await admin.firestore()
          .collection(col("participants")).doc(pid)
          .collection("pending_safety_confirmations")
          .where("resolved", "==", false)
          .get();

        for (const pendingDoc of pendingSnapshot.docs) {
          const pending = pendingDoc.data();
          const exceededAt = pending.thresholdExceededAt?.toDate?.();

          if (!exceededAt || exceededAt > fifteenMinAgo) continue;

          // Already alerted for this one?
          if (pending.walkAwayAlertSent) continue;

          console.log(`Walk-away detected: participant ${pid}, pending ${pendingDoc.id}, exceeded ${Math.round((now - exceededAt) / 60000)} min ago`);

          // Mark as alerted
          await pendingDoc.ref.update({
            walkAwayAlertSent: true,
            walkAwayAlertAt: admin.firestore.FieldValue.serverTimestamp(),
          });

          // Create a safety alert (potential risk, not confirmed)
          const alertId = pendingDoc.id + "_walkaway";
          await admin.firestore()
            .collection(col("participants")).doc(pid)
            .collection("safety_alerts").doc(alertId)
            .set({
              participantId: pid,
              sessionId: pending.sessionId,
              responses: pending.responses || {},
              triggeredAt: admin.firestore.FieldValue.serverTimestamp(),
              alertType: "unresolved_walkaway",
              triggerQuestions: pending.triggerQuestions || [],
              confirmedDanger: null,
              handled: false,
              thresholdExceededAt: pending.thresholdExceededAt,
              minutesSinceThreshold: Math.round((now - exceededAt) / 60000),
            });

          console.log(`Walk-away safety alert created for ${pid}: ${alertId}`);

          // The onSafetyAlert trigger will fire and handle notifications,
          // but with alertType "unresolved_walkaway" the messaging will
          // clearly indicate this is a potential (not confirmed) crisis.
        }
      }
    } catch (err) {
      console.error("Walk-away check error:", err);
    }
  }
);


// ============================================================================
// Lossless Screenshot Optimizer
//
// Storage-triggered: every uploaded screenshot JPEG is re-compressed with
// jpegtran (-optimize -progressive) — identical pixels, ~9-12% fewer bytes.
// This is NOT environment-prefixed: Storage paths are shared between dev and
// prod (screenshots/{participantId}/...), so exactly one instance should be
// deployed. The losslessOptimized metadata flag makes reprocessing a no-op,
// so a stray duplicate deployment is harmless.
// ============================================================================
const { onObjectFinalized } = require("firebase-functions/v2/storage");
const path = require("path");
const os = require("os");
const fs = require("fs");
const { execFile } = require("child_process");

function runJpegtran(inPath, outPath) {
  // jpegtran-bin v7 is ESM — the binary path is on .default under require()
  const jpegtranMod = require("jpegtran-bin");
  const jpegtranPath = jpegtranMod.default || jpegtranMod;
  return new Promise((resolve, reject) => {
    execFile(
      jpegtranPath,
      ["-optimize", "-progressive", "-copy", "all", "-outfile", outPath, inPath],
      (err) => (err ? reject(err) : resolve())
    );
  });
}

exports.optimizeScreenshot = onObjectFinalized(
  { region: "us-central1", memory: "512MiB", timeoutSeconds: 120 },
  async (event) => {
    const object = event.data;
    const name = object.name || "";

    // Only screenshot JPEGs, within sane size bounds
    if (!name.startsWith("screenshots/")) return;
    if (object.contentType !== "image/jpeg") return;
    const size = Number(object.size || 0);
    if (size < 5000 || size > 20000000) return;

    // Loop guard: our own re-upload triggers finalize again — exit on the flag
    if (object.metadata && object.metadata.losslessOptimized === "true") return;

    const bucket = admin.storage().bucket(object.bucket);
    const file = bucket.file(name);
    const stamp = `${Date.now()}_${Math.round(Math.random() * 1e6)}`;
    const tmpIn = path.join(os.tmpdir(), `opt_in_${stamp}.jpg`);
    const tmpOut = path.join(os.tmpdir(), `opt_out_${stamp}.jpg`);

    try {
      await file.download({ destination: tmpIn });
      await runJpegtran(tmpIn, tmpOut);
      const optimizedSize = fs.statSync(tmpOut).size;

      if (optimizedSize >= size) {
        // No gain — flag it so it's never reprocessed. A metadata patch does
        // not create a new generation, so this does not retrigger finalize.
        await file.setMetadata({ metadata: { losslessOptimized: "true" } });
        return;
      }

      // Overwrite with optimized bytes. Spreading object.metadata preserves
      // the app's custom fields AND firebaseStorageDownloadTokens, so any
      // previously issued download URL keeps working.
      await bucket.upload(tmpOut, {
        destination: name,
        metadata: {
          contentType: "image/jpeg",
          // Immutable content — long browser cache cuts repeat-view egress
          cacheControl: "private, max-age=31536000, immutable",
          metadata: { ...(object.metadata || {}), losslessOptimized: "true" },
        },
      });

      console.log(
        `[OptimizeScreenshot] ${name}: ${size} -> ${optimizedSize} bytes ` +
        `(-${(100 * (1 - optimizedSize / size)).toFixed(1)}%)`
      );
    } catch (err) {
      // Never fail loudly — the original object is untouched on any error
      console.error(`[OptimizeScreenshot] Failed for ${name}: ${err.message}`);
    } finally {
      for (const f of [tmpIn, tmpOut]) {
        try { fs.unlinkSync(f); } catch (_) { /* tmp cleanup best-effort */ }
      }
    }
  }
);


// ============================================================================
// Daily Firestore Backup
//
// Exports the entire Firestore database to the archive backup bucket every
// day at 08:00 UTC (alongside the daily Storage Transfer Service job that
// mirrors the Storage bucket). Each export lands in a timestamped folder —
// nothing is ever overwritten or deleted. Like optimizeScreenshot, this is
// infrastructure shared by dev and prod (Firestore is one database with
// collection prefixes), so exactly one instance should be deployed.
// ============================================================================
exports.dailyFirestoreBackup = onSchedule(
  { schedule: "0 8 * * *", timeZone: "UTC", region: "us-central1", timeoutSeconds: 300 },
  async () => {
    const { GoogleAuth } = require("google-auth-library");
    const auth = new GoogleAuth({
      scopes: ["https://www.googleapis.com/auth/datastore", "https://www.googleapis.com/auth/cloud-platform"],
    });
    const client = await auth.getClient();
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const outputUriPrefix = `gs://r01-redditx-suicide-archive-backup/firestore-exports/${ts}`;

    const res = await client.request({
      url: "https://firestore.googleapis.com/v1/projects/r01-redditx-suicide/databases/(default):exportDocuments",
      method: "POST",
      data: { outputUriPrefix },
    });

    console.log(`[FirestoreBackup] Export started -> ${outputUriPrefix} (operation: ${res.data.name})`);
  }
);


// ============================================================================
// HTML Brotli Transcode (hourly)
//
// Re-compresses uploaded HTML captures from gzip to brotli (~32% smaller,
// browsers decompress contentEncoding:br natively). Runs on a schedule and
// only touches objects older than 1 hour so the app has definitely finished
// writing the event doc (avoids racing upload_service's set(merge)).
// Every conversion is verified (decompress + hash match) before the original
// is removed. The daily backup mirror retains originals permanently.
// ============================================================================
const zlib = require("zlib");
const crypto = require("crypto");

const LIVE_BUCKET = "r01-redditx-suicide.firebasestorage.app";

function downloadUrlFor(bucketName, objectPath, token) {
  return `https://firebasestorage.googleapis.com/v0/b/${bucketName}/o/` +
    `${encodeURIComponent(objectPath)}?alt=media&token=${token}`;
}

// Update an event doc trying both prod and dev collections (the function is
// deployed once but data may come from either environment). update() only —
// never set(merge), which would create orphan docs in the wrong collection.
// List at most `cap` objects matching a glob, without buffering the whole
// prefix (the listing would otherwise grow unbounded over the study's life).
function listFilesBounded(bucket, prefix, glob, cap) {
  return new Promise((resolve, reject) => {
    const out = [];
    const stream = bucket.getFilesStream({ prefix, matchGlob: glob });
    stream.on("data", (file) => {
      out.push(file);
      if (out.length >= cap) stream.destroy();
    });
    stream.on("close", () => resolve(out));
    stream.on("end", () => resolve(out));
    stream.on("error", reject);
  });
}

async function updateEventDocBothEnvs(participantId, eventId, fields) {
  for (const collection of ["participants", "dev_participants"]) {
    try {
      await admin.firestore().collection(collection).doc(participantId)
        .collection("events").doc(eventId).update(fields);
      return collection;
    } catch (err) {
      if (err.code !== 5) throw err; // 5 = NOT_FOUND, try next collection
    }
  }
  return null;
}

exports.htmlBrotliTranscode = onSchedule(
  { schedule: "10 * * * *", timeZone: "UTC", region: "us-central1", memory: "1GiB", timeoutSeconds: 540 },
  async () => {
    const bucket = admin.storage().bucket(LIVE_BUCKET);
    // Server-side filter to unconverted captures only (.html / .html.gz, not .br)
    const files = await listFilesBounded(bucket, "html/", "html/**/page_*.html{,.gz}", 5000);
    const cutoff = Date.now() - 60 * 60 * 1000;
    let converted = 0, skipped = 0, failed = 0;

    for (const file of files) {
      // .html.gz (gzipped) and legacy plain .html both transcode to .html.br
      if (!file.name.endsWith(".html.gz") && !file.name.endsWith(".html")) { skipped++; continue; }
      if (new Date(file.metadata.timeCreated).getTime() > cutoff) { skipped++; continue; }
      if (converted >= 500) break; // cap per run; hourly schedule drains backlog

      try {
        // Node storage client transparently gunzips contentEncoding:gzip objects
        const [rawHtml] = await file.download();
        const rawHash = crypto.createHash("sha256").update(rawHtml).digest("hex");

        const brBytes = zlib.brotliCompressSync(rawHtml, {
          params: {
            [zlib.constants.BROTLI_PARAM_QUALITY]: 11,
            [zlib.constants.BROTLI_PARAM_SIZE_HINT]: rawHtml.length,
          },
        });

        const meta = file.metadata.metadata || {};
        const token = meta.firebaseStorageDownloadTokens ||
          crypto.randomUUID();
        const newName = file.name.replace(/\.html(\.gz)?$/, ".html.br");

        const newFile = bucket.file(newName);
        await newFile.save(brBytes, {
          resumable: false,
          metadata: {
            contentType: "text/html",
            contentEncoding: "br",
            cacheControl: "private, max-age=31536000, immutable",
            metadata: { ...meta, firebaseStorageDownloadTokens: token, brotliTranscoded: "true" },
          },
        });

        // Verify the stored brotli decompresses to the identical HTML
        const [storedBr] = await newFile.download({ decompress: false });
        const roundtrip = zlib.brotliDecompressSync(storedBr);
        const ok = crypto.createHash("sha256").update(roundtrip).digest("hex") === rawHash;
        if (!ok) {
          console.error(`[HtmlBrotli] VERIFY FAILED for ${file.name} — original kept`);
          await newFile.delete().catch(() => {});
          failed++;
          continue;
        }

        // Point the event doc at the new object, then remove the original
        if (meta.eventId && meta.participantId) {
          const updated = await updateEventDocBothEnvs(meta.participantId, meta.eventId, {
            "html.storageUrl": downloadUrlFor(LIVE_BUCKET, newName, token),
            "html.storagePath": newName,
            "html.compression": "br",
          });
          if (updated) {
            // Older app builds wrote a LITERAL top-level "html.storageUrl"
            // field via set(merge) (dots are not paths in set()). Clear it so
            // no stale .gz pointer remains. Literal field names require the
            // varargs update(FieldPath, value) form.
            await admin.firestore().collection(updated).doc(meta.participantId)
              .collection("events").doc(meta.eventId)
              .update(
                new admin.firestore.FieldPath("html.storageUrl"),
                admin.firestore.FieldValue.delete()
              ).catch(() => { /* field may not exist on newer docs */ });
          }
          if (!updated) {
            console.warn(`[HtmlBrotli] no event doc for ${file.name} — original kept alongside .br`);
            converted++;
            continue;
          }
        }
        await file.delete();
        converted++;
      } catch (err) {
        failed++;
        console.error(`[HtmlBrotli] Failed for ${file.name}: ${err.message}`);
      }
    }
    console.log(`[HtmlBrotli] converted=${converted} skipped=${skipped} failed=${failed}`);
  }
);


// ============================================================================
// HTML Solid Compaction (daily)
//
// HTML captures of the same feeds are highly redundant ACROSS files: solid
// archives (tar of raw HTML, brotli-compressed as one stream) measured 5.2x
// smaller than individually-gzipped files on real study data. Captures older
// than 30 days are bundled into per-participant per-day archives:
//   html-archives/{participantId}/{YYYY-MM-DD}[-partN].tar.br
// Each member is verified (hash match after re-download + untar) before its
// individual object is removed, and event docs are repointed first. The daily
// backup mirror retains every original individual file permanently.
// ============================================================================
const tarStream = require("tar-stream");

const COMPACT_AFTER_DAYS = 30;
const COMPACT_MAX_GROUPS_PER_RUN = 15;
const COMPACT_MAX_RAW_BYTES = 300 * 1024 * 1024;

async function decompressMember(file) {
  // .br objects need manual decompression; gzip is transparent in the client
  if (file.name.endsWith(".br")) {
    const [raw] = await file.download({ decompress: false });
    return zlib.brotliDecompressSync(raw);
  }
  const [raw] = await file.download();
  return raw;
}

function buildTar(members) {
  return new Promise((resolve, reject) => {
    const pack = tarStream.pack();
    const chunks = [];
    pack.on("data", (c) => chunks.push(c));
    pack.on("end", () => resolve(Buffer.concat(chunks)));
    pack.on("error", reject);
    const manifest = members.map((m) => ({
      path: m.tarPath, bytes: m.content.length, sha256: m.hash,
      eventId: m.eventId || null, sessionId: m.sessionId || null,
    }));
    pack.entry({ name: "manifest.json" }, JSON.stringify(manifest, null, 2));
    for (const m of members) pack.entry({ name: m.tarPath }, m.content);
    pack.finalize();
  });
}

function parseTar(buf) {
  return new Promise((resolve, reject) => {
    const extract = tarStream.extract();
    const out = {};
    extract.on("entry", (header, stream, next) => {
      const chunks = [];
      stream.on("data", (c) => chunks.push(c));
      stream.on("end", () => { out[header.name] = Buffer.concat(chunks); next(); });
      stream.resume();
    });
    extract.on("finish", () => resolve(out));
    extract.on("error", reject);
    extract.end(buf);
  });
}

exports.compactOldHtml = onSchedule(
  { schedule: "30 10 * * *", timeZone: "UTC", region: "us-central1", memory: "2GiB", timeoutSeconds: 1800 },
  async () => {
    const bucket = admin.storage().bucket(LIVE_BUCKET);
    const files = await listFilesBounded(bucket, "html/", "html/**/page_*.html*", 50000);
    const cutoff = Date.now() - COMPACT_AFTER_DAYS * 24 * 60 * 60 * 1000;

    // Group eligible captures by participant + UTC date (from filename ms timestamp)
    const groups = new Map();
    for (const f of files) {
      const m = f.name.match(/^html\/([^/]+)\/([^/]+)\/page_(\d+)\.html(\.br|\.gz)?$/);
      if (!m) continue;
      const ts = Number(m[3]);
      if (ts > cutoff) continue;
      const date = new Date(ts).toISOString().slice(0, 10);
      const key = `${m[1]}|${date}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(f);
    }

    let processed = 0;
    for (const [key, groupFiles] of groups) {
      if (processed >= COMPACT_MAX_GROUPS_PER_RUN) break;
      const [participantId, date] = key.split("|");

      // Split the group into parts under the raw-size cap
      let part = 0, batch = [], batchBytes = 0;
      const flushBatch = async () => {
        if (!batch.length) return;
        part++;
        const suffix = part === 1 ? "" : `-part${part}`;
        const archivePath = `html-archives/${participantId}/${date}${suffix}.tar.br`;
        try {
          const tarBuf = await buildTar(batch);
          const brBuf = zlib.brotliCompressSync(tarBuf, {
            params: {
              [zlib.constants.BROTLI_PARAM_QUALITY]: 10,
              [zlib.constants.BROTLI_PARAM_LGWIN]: 24,
              [zlib.constants.BROTLI_PARAM_SIZE_HINT]: tarBuf.length,
            },
          });
          const archiveFile = bucket.file(archivePath);
          await archiveFile.save(brBuf, {
            resumable: false,
            metadata: {
              contentType: "application/x-tar+br",
              metadata: { participantId, date, members: String(batch.length) },
            },
          });

          // VERIFY: re-download, decompress, untar, hash-match every member
          const [stored] = await archiveFile.download({ decompress: false });
          const entries = await parseTar(zlib.brotliDecompressSync(stored));
          for (const m of batch) {
            const got = entries[m.tarPath];
            const ok = got && crypto.createHash("sha256").update(got).digest("hex") === m.hash;
            if (!ok) throw new Error(`verification failed for ${m.tarPath}`);
          }

          // Repoint event docs, then remove the individual objects
          for (const m of batch) {
            if (m.eventId && m.participantId) {
              let updated = null;
              try {
                updated = await updateEventDocBothEnvs(m.participantId, m.eventId, {
                  "html.archive": `gs://${LIVE_BUCKET}/${archivePath}`,
                  "html.archiveMember": m.tarPath,
                  "html.storageUrl": admin.firestore.FieldValue.delete(),
                });
              } catch (e) {
                console.error(`[HtmlCompact] doc update failed for ${m.eventId}: ${e.message}`);
              }
              if (!updated) {
                // Doc missing or update failed — the member is in the archive
                // but keep the individual object so no reference ever dies.
                console.warn(`[HtmlCompact] keeping ${m.file.name} (doc not repointed)`);
                continue;
              }
            }
            await m.file.delete();
          }
          console.log(`[HtmlCompact] ${archivePath}: ${batch.length} files, raw ${(batchBytes / 1e6).toFixed(1)}MB -> ${(brBuf.length / 1e6).toFixed(1)}MB`);
        } catch (err) {
          console.error(`[HtmlCompact] FAILED ${archivePath}: ${err.message} — originals kept`);
        }
        batch = []; batchBytes = 0;
      };

      for (const f of groupFiles) {
        try {
          const content = await decompressMember(f);
          const meta = f.metadata.metadata || {};
          batch.push({
            file: f,
            tarPath: f.name.replace(/^html\//, "").replace(/\.(br|gz)$/, ""),  // plain .html keeps its name
            content,
            hash: crypto.createHash("sha256").update(content).digest("hex"),
            eventId: meta.eventId,
            sessionId: meta.sessionId,
            participantId: meta.participantId || participantId,
          });
          batchBytes += content.length;
          if (batchBytes >= COMPACT_MAX_RAW_BYTES) await flushBatch();
        } catch (err) {
          console.error(`[HtmlCompact] skip ${f.name}: ${err.message}`);
        }
      }
      await flushBatch();
      processed++;
    }
    console.log(`[HtmlCompact] processed ${processed} participant-day groups`);
  }
);


// ============================================================================
// Screenshot JXL Conversion (hourly)
//
// Losslessly transcodes screenshot JPEGs to JPEG XL (~19-21% smaller). The
// JXL container is BYTE-EXACT reversible — djxl reconstructs the identical
// original .jpg file, which is verified here before the original is removed.
// Event docs are repointed to the backend display proxy
// (/api/screenshot-view), which reconstructs a standard JPEG on the fly so
// Chrome/Safari/everything renders exactly as before.
// DO NOT deploy this function before the backend proxy endpoint is live.
// ============================================================================
const { execFile: execFileCb } = require("child_process");
const { promisify } = require("util");
const execFileAsync = promisify(execFileCb);

function jxlTool(name) {
  const p = path.join(__dirname, "bin", name);
  try { fs.chmodSync(p, 0o755); } catch (_) { /* best effort */ }
  return p;
}

exports.convertScreenshotsToJxl = onSchedule(
  { schedule: "40 * * * *", timeZone: "UTC", region: "us-central1", memory: "1GiB", timeoutSeconds: 1200 },
  async () => {
    const bucket = admin.storage().bucket(LIVE_BUCKET);
    // matchGlob filters server-side to unconverted .jpg only — without it the
    // hourly listing grows unbounded as converted .jxl files accumulate.
    const files = await listFilesBounded(bucket, "screenshots/", "screenshots/**/*.jpg", 5000);
    const cutoff = Date.now() - 60 * 60 * 1000;
    let converted = 0, failed = 0;

    for (const file of files) {
      if (!file.name.endsWith(".jpg")) continue;
      if (new Date(file.metadata.timeCreated).getTime() > cutoff) continue;
      const meta = file.metadata.metadata || {};
      if (meta.jxlSkipped === "true") continue;
      if (converted >= 300) break; // hourly schedule drains backlog

      const stamp = `${Date.now()}_${Math.round(Math.random() * 1e6)}`;
      const tmpJpg = path.join(os.tmpdir(), `jx_${stamp}.jpg`);
      const tmpJxl = path.join(os.tmpdir(), `jx_${stamp}.jxl`);
      const tmpRec = path.join(os.tmpdir(), `jx_${stamp}_rec.jpg`);

      try {
        await file.download({ destination: tmpJpg });
        await execFileAsync(jxlTool("cjxl"), [tmpJpg, tmpJxl, "--lossless_jpeg=1", "-e", "7"]);

        // VERIFY byte-exact reconstruction before touching the original
        await execFileAsync(jxlTool("djxl"), [tmpJxl, tmpRec]);
        const original = fs.readFileSync(tmpJpg);
        const roundtrip = fs.readFileSync(tmpRec);
        if (!original.equals(roundtrip)) throw new Error("roundtrip not byte-exact");

        const jxlBytes = fs.readFileSync(tmpJxl);
        if (jxlBytes.length >= original.length) {
          await file.setMetadata({ metadata: { jxlSkipped: "true" } });
          continue;
        }

        const token = meta.firebaseStorageDownloadTokens || crypto.randomUUID();
        const newName = file.name.replace(/\.jpg$/, ".jxl");
        await bucket.file(newName).save(jxlBytes, {
          resumable: false,
          metadata: {
            contentType: "image/jxl",
            cacheControl: "private, max-age=31536000, immutable",
            metadata: { ...meta, firebaseStorageDownloadTokens: token, jxlOfJpeg: "true" },
          },
        });

        // Repoint the event doc at the display proxy, then remove the .jpg.
        // Store the durable storage path + token alongside the absolute URL so
        // the backend can rebuild URLs if the service ever moves domains.
        if (meta.eventId && meta.participantId) {
          const newFields = {
            screenshotUrl: `${BACKEND_URL}/api/screenshot-view?path=${encodeURIComponent(newName)}&token=${token}`,
            screenshotStoragePath: newName,
            screenshotToken: token,
            screenshotFormat: "jxl",
          };
          const updated = await updateEventDocBothEnvs(meta.participantId, meta.eventId, newFields);

          // Deduped sibling events share this object and carry the same .jpg
          // URL — repoint every one of them or their images die with the .jpg.
          const oldUrl = downloadUrlFor(LIVE_BUCKET, file.name, token);
          for (const collection of ["participants", "dev_participants"]) {
            const siblings = await admin.firestore().collection(collection)
              .doc(meta.participantId).collection("events")
              .where("screenshotUrl", "==", oldUrl).get();
            for (const sib of siblings.docs) {
              await sib.ref.update(newFields).catch((e) =>
                console.error(`[JxlConvert] sibling repoint failed ${sib.id}: ${e.message}`));
            }
          }

          if (!updated) {
            // Event doc not found in either env (e.g., device offline, event
            // not yet synced) — keep BOTH objects so no stored URL ever dies.
            console.warn(`[JxlConvert] no event doc for ${file.name} — original kept alongside .jxl`);
            converted++;
            continue;
          }
        }
        await file.delete();
        converted++;
      } catch (err) {
        failed++;
        console.error(`[JxlConvert] Failed for ${file.name}: ${err.message} — original kept`);
      } finally {
        for (const f of [tmpJpg, tmpJxl, tmpRec]) { try { fs.unlinkSync(f); } catch (_) { /* ok */ } }
      }
    }
    console.log(`[JxlConvert] converted=${converted} failed=${failed}`);
  }
);
