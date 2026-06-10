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
  const info = { phone: null, email: null, name: null, emergencyContacts: [], redcapId: null };

  // Check participants collection
  const pDoc = await admin.firestore().collection(col("participants")).doc(participantId).get();
  if (pDoc.exists) {
    const data = pDoc.data();
    info.phone = data.phone || data.phoneNumber;
    info.email = data.email;
    info.name = data.name || data.participantName;
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

          // 4b. IVR call to participant
          // Press 1 = transfer to 988
          // Press 2 = error / not in crisis
          // Press 3 = was in crisis, already received support
          // No answer/no press = unable to reach
          try {
            const actionUrl = `${BACKEND_URL}/api/twilio/call-response?participantId=${participantId}&alertId=${alertId}`;
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
              <Gather numDigits="1" action="${actionUrl}" method="POST" timeout="20">
                <Say voice="Polly.Joanna">
                  Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline, where trained crisis counselors are available to provide immediate support.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 2 if your response was an error and you are not currently in a crisis state.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support, such as from an emergency contact, 988, a therapist, a healthcare provider, or another trusted person.
                </Say>
              </Gather>
              <Say voice="Polly.Joanna">Again, please listen to the options.</Say>
              <Pause length="1"/>
              <Gather numDigits="1" action="${actionUrl}" method="POST" timeout="20">
                <Say voice="Polly.Joanna">
                  Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 2 if your response was an error and you are not currently in a crisis state.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support.
                </Say>
              </Gather>
              <Say voice="Polly.Joanna">For a third and final time, here are the options.</Say>
              <Pause length="1"/>
              <Gather numDigits="1" action="${actionUrl}" method="POST" timeout="20">
                <Say voice="Polly.Joanna">
                  Press 1 if you would like us to try to transfer you now to the 988 Suicide and Crisis Lifeline.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 2 if your response was an error and you are not currently in a crisis state.
                </Say>
                <Pause length="1"/>
                <Say voice="Polly.Joanna">
                  Press 3 if you were in a crisis state, but you are no longer in a crisis state because you have already received support.
                </Say>
              </Gather>
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
            participantCallResult = { sid: call.sid, status: call.status, phone: participantInfo.phone };
          } catch (err) {
            participantCallResult = { error: err.message };
          }

          if (safetyEventRef) {
            await safetyEventRef.collection("audit_trail").doc().set({
              type: "participant_call_initiated",
              result: participantCallResult,
              message: "IVR call: 1=transfer to 988, 2=error/not in crisis, 3=resolved with support",
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          }
        }

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
const escalationFnName = ENVIRONMENT === "dev" ? "dev_checkEscalation" : "checkEscalation";
exports[escalationFnName] = onSchedule(
  {
    schedule: "every 5 minutes",
    secrets: [twilioAccountSid, twilioAuthToken, twilioFromNumber],
    timeZone: "America/New_York",
  },
  async () => {
    try {
      const now = new Date();
      const fifteenMinAgo = new Date(now.getTime() - 15 * 60 * 1000);

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
        const lastCheckInAt = eventData.lastCheckInAt?.toDate?.();
        const currentDisposition = eventData.currentDisposition;

        // Skip fully resolved events
        if (currentDisposition && !["ongoing"].includes(currentDisposition)) continue;

        const minutesSinceCreation = (now.getTime() - createdAt.getTime()) / (60 * 1000);

        // Determine what needs to happen
        if (!acknowledged) {
          // NOT ACKNOWLEDGED: escalate if 15+ min with no ACK
          let escalationTarget = null;
          let escalationLevel = null;

          if (minutesSinceCreation >= 30 && !eventData.piEscalated) {
            escalationTarget = roster.pi;
            escalationLevel = "pi";
          } else if (minutesSinceCreation >= 15 && !eventData.backupEscalated) {
            escalationTarget = roster.backup;
            escalationLevel = "backup";
          }

          if (escalationTarget && escalationTarget.phone) {
            try {
              await twilioWithRetry("messages.create", () => client.messages.create({
                body: `[SocialScope ESCALATION - ${escalationLevel.toUpperCase()}]\n` +
                      `Safety event for participant ${eventData.participantId} ` +
                      `has NOT been acknowledged in ${Math.round(minutesSinceCreation)} min.\n` +
                      `Reply ACK to acknowledge, or log disposition.\n` +
                      `Reply SAFE, SUPPORT, NOREACH, FALSE, 988, or ER.\n` +
                      `Dashboard: ${DASHBOARD_URL}`,
                from: fromNumber,
                to: `+1${escalationTarget.phone}`,
              }));

              const updateData = {};
              updateData[`${escalationLevel}Escalated`] = true;
              updateData[`${escalationLevel}EscalatedAt`] = admin.firestore.FieldValue.serverTimestamp();
              await doc.ref.update(updateData);

              await doc.ref.collection("audit_trail").doc().set({
                type: "escalation",
                escalationLevel,
                escalatedTo: escalationTarget.name,
                reason: "not_acknowledged",
                minutesSinceCreation: Math.round(minutesSinceCreation),
                loggedBy: "system",
                loggedAt: admin.firestore.FieldValue.serverTimestamp(),
              });

              console.log(`Escalation (not ACKed) to ${escalationLevel}: ${eventData.participantId}`);
            } catch (err) {
              console.error(`Escalation to ${escalationLevel} failed:`, err.message);
            }
          }
        } else if (currentDisposition === "ongoing") {
          // ACKNOWLEDGED + ONGOING: send hourly check-in reminders
          // Escalate to backup/PI if no check-in within 15 min of the hour mark
          const minutesSinceLastCheckIn = lastCheckInAt
            ? (now.getTime() - lastCheckInAt.getTime()) / (60 * 1000)
            : minutesSinceCreation;

          if (minutesSinceLastCheckIn >= 60) {
            // Send hourly check-in reminder to primary
            const primary = roster.primary;
            if (primary && primary.phone && !eventData[`hourlyReminder_${Math.floor(minutesSinceCreation / 60)}`]) {
              try {
                await twilioWithRetry("messages.create", () => client.messages.create({
                  body: `[SocialScope CHECK-IN REMINDER]\n` +
                        `Your ongoing event for participant ${eventData.participantId} ` +
                        `needs an update (${Math.round(minutesSinceCreation)} min since alert).\n` +
                        `Reply ONGOING to confirm still working on it.\n` +
                        `Reply SAFE, SUPPORT, 988, or ER to log final disposition.\n` +
                        `If no response in 15 min, backup will be paged.`,
                  from: fromNumber,
                  to: `+1${primary.phone}`,
                }));

                const hourKey = `hourlyReminder_${Math.floor(minutesSinceCreation / 60)}`;
                await doc.ref.update({ [hourKey]: admin.firestore.FieldValue.serverTimestamp() });

                await doc.ref.collection("audit_trail").doc().set({
                  type: "hourly_checkin_reminder",
                  minutesSinceCreation: Math.round(minutesSinceCreation),
                  loggedBy: "system",
                  loggedAt: admin.firestore.FieldValue.serverTimestamp(),
                });

                console.log(`Hourly check-in reminder sent for ${eventData.participantId}`);
              } catch (err) {
                console.error(`Hourly reminder failed:`, err.message);
              }
            }

            // Escalate if 75+ min since last check-in (60 min + 15 min grace)
            if (minutesSinceLastCheckIn >= 75) {
              const escalationTarget = !eventData.backupEscalatedOngoing ? roster.backup : roster.pi;
              const escalationLevel = !eventData.backupEscalatedOngoing ? "backup" : "pi";

              if (escalationTarget && escalationTarget.phone) {
                try {
                  await twilioWithRetry("messages.create", () => client.messages.create({
                    body: `[SocialScope ESCALATION - ${escalationLevel.toUpperCase()}]\n` +
                          `Ongoing safety event for ${eventData.participantId} ` +
                          `— primary on-call has not checked in for ${Math.round(minutesSinceLastCheckIn)} min.\n` +
                          `Reply ACK, ONGOING, SAFE, SUPPORT, 988, or ER.`,
                    from: fromNumber,
                    to: `+1${escalationTarget.phone}`,
                  }));

                  await doc.ref.update({
                    [`${escalationLevel}EscalatedOngoing`]: true,
                  });

                  await doc.ref.collection("audit_trail").doc().set({
                    type: "escalation",
                    escalationLevel,
                    reason: "ongoing_no_checkin",
                    minutesSinceLastCheckIn: Math.round(minutesSinceLastCheckIn),
                    loggedBy: "system",
                    loggedAt: admin.firestore.FieldValue.serverTimestamp(),
                  });
                } catch (err) {
                  console.error(`Ongoing escalation failed:`, err.message);
                }
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

      // Get all open (unresolved) safety events — filter in code to avoid
      // needing composite indexes for inequality + inequality queries
      const allOpenEvents = await admin.firestore()
        .collection(col("safety_events"))
        .where("escalationStopped", "==", false)
        .get();

      for (const doc of allOpenEvents.docs) {
        const eventData = doc.data();

        // Skip if participant already resolved (replied ERROR via SMS, or pressed 2/3 on IVR)
        if (eventData.participantResolved === true) continue;

        // Skip if participant confirmed crisis on IVR (pressed 1 = transfer to 988) —
        // the IVR flow handles those (conference bridge to 988, emergency contact notification)
        if (eventData.participantConfirmedCrisis === true) continue;

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

        // ─── TEXT emergency contacts at 5+ minutes ───
        if (minutesSinceCreation >= 5 && !eventData.emergencyContactAutoTextSent) {
          console.log(`[EmergencyContactAuto] 5+ min elapsed for ${eventData.participantId}, sending texts to emergency contacts`);

          // Get participant info for emergency contacts
          const participantInfo = await getParticipantInfo(eventData.participantId);

          if (participantInfo.emergencyContacts && participantInfo.emergencyContacts.length > 0) {
            const client = getTwilioClient();
            const fromNumber = twilioFromNumber.value();
            const participantName = participantInfo.name || `Study participant ${eventData.participantId}`;
            const textResults = [];

            for (const contact of participantInfo.emergencyContacts) {
              if (!contact.phone) continue;
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
                textResults.push({ name: contactName, phone: contact.phone, sid: smsResult.sid });
                console.log(`[EmergencyContactAuto] Text sent to ${contactName} (${contact.phone}): ${smsResult.sid}`);
              } catch (err) {
                textResults.push({ name: contactName, phone: contact.phone, error: err.message });
                console.error(`[EmergencyContactAuto] Text failed to ${contactName}: ${err.message}`);
              }
            }

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

        // ─── CALL emergency contacts at 8+ minutes (3 min after text) ───
        if (minutesSinceCreation >= 8 && eventData.emergencyContactAutoTextSent && !eventData.emergencyContactAutoCallSent) {
          console.log(`[EmergencyContactAuto] 8+ min elapsed for ${eventData.participantId}, calling emergency contacts`);

          const participantInfo = await getParticipantInfo(eventData.participantId);

          if (participantInfo.emergencyContacts && participantInfo.emergencyContacts.length > 0) {
            const client = getTwilioClient();
            const fromNumber = twilioFromNumber.value();
            const participantName = participantInfo.name || `Study participant ${eventData.participantId}`;
            const callResults = [];

            for (const contact of participantInfo.emergencyContacts) {
              if (!contact.phone) continue;
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
                callResults.push({ name: contactName, phone: contact.phone, sid: callResult.sid });
                console.log(`[EmergencyContactAuto] Call placed to ${contactName} (${contact.phone}): ${callResult.sid}`);
              } catch (err) {
                callResults.push({ name: contactName, phone: contact.phone, error: err.message });
                console.error(`[EmergencyContactAuto] Call failed to ${contactName}: ${err.message}`);
              }
            }

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
