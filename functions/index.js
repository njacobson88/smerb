const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { onSchedule } = require("firebase-functions/v2/scheduler");
const { defineSecret } = require("firebase-functions/params");
const admin = require("firebase-admin");
const nodemailer = require("nodemailer");

admin.initializeApp();

// Twilio credentials stored as Firebase secrets
const twilioAccountSid = defineSecret("TWILIO_ACCOUNT_SID");
const twilioAuthToken = defineSecret("TWILIO_AUTH_TOKEN");
const twilioFromNumber = defineSecret("TWILIO_FROM_NUMBER");

// Slack/email notification config
const slackChannelEmail = defineSecret("SLACK_CHANNEL_EMAIL");
const alertSenderEmail = defineSecret("ALERT_SENDER_EMAIL");
const alertSenderPassword = defineSecret("ALERT_SENDER_PASSWORD");

// ============================================================================
// Helper: Send email (for Slack channel and participant notifications)
// ============================================================================
async function sendEmail({ senderEmail, senderPassword, to, subject, body }) {
  const transporter = nodemailer.createTransport({
    service: "gmail",
    auth: { user: senderEmail, pass: senderPassword },
  });

  await transporter.sendMail({
    from: `"SocialScope Study Team" <${senderEmail}>`,
    to,
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
// Helper: Create a safety event in the audit trail system
// ============================================================================
async function createSafetyEvent(alertData, participantId, alertId) {
  const eventRef = admin.firestore().collection("safety_events").doc(alertId);

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
  const snapshot = await admin.firestore().collection("oncall_roster").get();
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
    .collection("participants").doc(participantId).get();

  if (!participantDoc.exists) return null;

  const participantData = participantDoc.data();
  const participantPhone = participantData.phone || participantData.phoneNumber;

  if (!participantPhone) {
    console.log(`No phone number for participant ${participantId}`);
    return null;
  }

  try {
    const result = await client.messages.create({
      body: `This is the SocialScope study team. Based on your recent check-in, ` +
            `we want to make sure you're safe. A member of our team will be calling ` +
            `you shortly. If you are in immediate danger, please call 988.`,
      from: fromNumber,
      to: participantPhone.startsWith("+") ? participantPhone : `+1${participantPhone}`,
    });
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
    .collection("participants").doc(participantId).get();

  if (!participantDoc.exists) return null;

  const participantData = participantDoc.data();
  const participantPhone = participantData.phone || participantData.phoneNumber;

  if (!participantPhone) return null;

  try {
    // TwiML: Play a message, then offer options
    // Press 1 = accidental/error (logs and stops escalation)
    // Press 2 = connect to study team
    // Press 9 = connect to 988 Suicide & Crisis Lifeline (warm handoff)
    const twiml = `<Response>
      <Gather numDigits="1" action="https://socialscope-dashboard-api-436153481478.us-central1.run.app/api/twilio/call-response?participantId=${participantId}" method="POST" timeout="15">
        <Say voice="alice">
          Hello, this is the SocialScope study team calling to check on you
          after your recent check-in. We want to make sure you are safe.
          Press 1 if you are safe and this was an accidental response.
          Press 2 to speak with a member of the study team.
          Press 9 to be connected to the 988 Suicide and Crisis Lifeline.
        </Say>
      </Gather>
      <Say voice="alice">We did not receive a response. A team member will follow up with you shortly.</Say>
    </Response>`;

    const call = await client.calls.create({
      twiml,
      from: fromNumber,
      to: participantPhone.startsWith("+") ? participantPhone : `+1${participantPhone}`,
      timeout: 30,
    });

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
    .collection("participants").doc(participantId).get();

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
    const smsResult = await client.messages.create({
      body: `This is the SocialScope research study team at Dartmouth College. ` +
            `We are trying to reach a study participant who listed you as an ` +
            `emergency contact. Please contact us as soon as possible. ` +
            `If you believe this person is in immediate danger, please call 911.`,
      from: fromNumber,
      to: emergencyPhone.startsWith("+") ? emergencyPhone : `+1${emergencyPhone}`,
    });

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
// Main Safety Alert Trigger
// ============================================================================
exports.onSafetyAlert = onDocumentCreated(
  {
    document: "participants/{participantId}/safety_alerts/{alertId}",
    secrets: [
      twilioAccountSid, twilioAuthToken, twilioFromNumber,
      slackChannelEmail, alertSenderEmail, alertSenderPassword,
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
    const senderPass = alertSenderPassword.value();

    if (slackEmail && senderEmailVal && senderPass) {
      try {
        const alertLabel = isConfirmedDanger
          ? "CONFIRMED DANGER"
          : isFallback
            ? "INCOMPLETE CHECK-IN (high-risk responses)"
            : "SAFETY ALERT";

        await sendEmail({
          senderEmail: senderEmailVal,
          senderPassword: senderPass,
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
            `View dashboard: https://socialscope-dashboard.web.app\n` +
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
    // Step 3: Notify on-call team via SMS
    // ================================================================
    const recipientsSnapshot = await admin.firestore()
      .collection("alert_recipients").get();

    const recipients = [];
    recipientsSnapshot.forEach((doc) => {
      const data = doc.data();
      recipients.push({ phone: doc.id, name: data.name || null });
    });

    if (alertData.pageTarget && !recipients.find(r => r.phone === alertData.pageTarget)) {
      recipients.push({ phone: alertData.pageTarget, name: "Legacy Target" });
    }

    let smsResults = [];
    let smsErrors = [];

    if (recipients.length > 0) {
      try {
        const client = getTwilioClient();
        const alertLabel = isConfirmedDanger ? "CONFIRMED DANGER" : isFallback ? "INCOMPLETE CHECK-IN" : "ALERT";

        const smsBody =
          `[SocialScope ${alertLabel}]\n` +
          `Participant: ${participantId}\n` +
          `Time: ${timestamp}\n` +
          (isConfirmedDanger
            ? `Participant CONFIRMED they are in immediate danger.\n`
            : isFallback
              ? `Participant gave high-risk responses but exited check-in before confirmation.\n`
              : `A participant endorsed imminent self-harm risk.\n`) +
          `View: https://socialscope-dashboard.web.app`;

        for (const recipient of recipients) {
          try {
            const result = await client.messages.create({
              body: smsBody,
              from: twilioFromNumber.value(),
              to: `+1${recipient.phone}`,
            });
            smsResults.push({
              phone: recipient.phone,
              name: recipient.name,
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
    // Step 4: Participant outreach (only for confirmed danger)
    // ================================================================
    let participantSmsResult = null;
    let participantCallResult = null;
    let emergencyContactResult = null;

    if (isConfirmedDanger) {
      try {
        const client = getTwilioClient();
        const fromNumber = twilioFromNumber.value();

        // SMS participant that team will call
        participantSmsResult = await smsParticipant(client, participantId, fromNumber);

        // Log to audit trail
        if (safetyEventRef) {
          await safetyEventRef.collection("audit_trail").doc().set({
            type: "participant_sms_sent",
            result: participantSmsResult,
            loggedBy: "system",
            loggedAt: admin.firestore.FieldValue.serverTimestamp(),
          });
        }

        // Initiate call to participant (with IVR: press 1=safe, 2=team, 9=988)
        participantCallResult = await callParticipant(client, participantId, fromNumber);

        if (safetyEventRef) {
          await safetyEventRef.collection("audit_trail").doc().set({
            type: "participant_call_initiated",
            result: participantCallResult,
            loggedBy: "system",
            loggedAt: admin.firestore.FieldValue.serverTimestamp(),
          });
        }
      } catch (err) {
        console.error("Participant outreach error:", err);
      }
    }

    // ================================================================
    // Step 5: Email participant (if email available, doesn't need MS Graph yet)
    // ================================================================
    if (isConfirmedDanger && senderEmailVal && senderPass) {
      try {
        const participantDoc = await admin.firestore()
          .collection("participants").doc(participantId).get();
        const participantEmail = participantDoc.exists
          ? participantDoc.data().email
          : null;

        if (participantEmail) {
          await sendEmail({
            senderEmail: senderEmailVal,
            senderPassword: senderPass,
            to: participantEmail,
            subject: "SocialScope Study Team - Checking In",
            body:
              `Hello,\n\n` +
              `This is the SocialScope study team at Dartmouth College. ` +
              `Based on your recent check-in, we want to make sure you're safe ` +
              `and have the support you need.\n\n` +
              `A member of our team will be reaching out to you shortly.\n\n` +
              `If you are in immediate danger, please:\n` +
              `- Call 988 (Suicide & Crisis Lifeline)\n` +
              `- Text HOME to 741741 (Crisis Text Line)\n` +
              `- Call 911 or go to your nearest emergency room\n\n` +
              `Thank you for being part of this study. Your safety is our top priority.\n\n` +
              `- SocialScope Study Team, Dartmouth College`,
          });

          if (safetyEventRef) {
            await safetyEventRef.collection("audit_trail").doc().set({
              type: "participant_email_sent",
              participantEmail: participantEmail,
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          }
        }
      } catch (err) {
        console.error("Failed to email participant:", err);
      }
    }

    // ================================================================
    // Step 6: Update alert document with all results
    // ================================================================
    await snapshot.ref.update({
      handled: smsResults.length > 0 || slackResult === "sent",
      smsResults: smsResults.length > 0 ? smsResults : null,
      smsErrors: smsErrors.length > 0 ? smsErrors : null,
      recipientCount: recipients.length,
      successCount: smsResults.length,
      slackResult,
      slackError,
      participantSmsResult,
      participantCallResult,
      emergencyContactResult,
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
exports.checkEscalation = onSchedule(
  {
    schedule: "every 5 minutes",
    secrets: [twilioAccountSid, twilioAuthToken, twilioFromNumber],
    timeZone: "America/New_York",
  },
  async () => {
    try {
      const now = new Date();
      const fifteenMinAgo = new Date(now.getTime() - 15 * 60 * 1000);

      // Find safety events that haven't been responded to
      const eventsSnapshot = await admin.firestore()
        .collection("safety_events")
        .where("escalationStopped", "==", false)
        .where("currentDisposition", "==", null)
        .get();

      if (eventsSnapshot.empty) return;

      const roster = await getOnCallRoster();
      const client = getTwilioClient();
      const fromNumber = twilioFromNumber.value();

      for (const doc of eventsSnapshot.docs) {
        const eventData = doc.data();
        const createdAt = eventData.createdAt?.toDate?.() || new Date();

        const minutesSinceCreation = (now.getTime() - createdAt.getTime()) / (60 * 1000);

        // Determine escalation level
        let escalationTarget = null;
        let escalationLevel = null;

        if (minutesSinceCreation >= 30 && !eventData.piEscalated) {
          // 30+ minutes: escalate to PI
          escalationTarget = roster.pi;
          escalationLevel = "pi";
        } else if (minutesSinceCreation >= 15 && !eventData.backupEscalated) {
          // 15+ minutes: escalate to backup
          escalationTarget = roster.backup;
          escalationLevel = "backup";
        }

        if (escalationTarget && escalationTarget.phone) {
          try {
            const result = await client.messages.create({
              body: `[SocialScope ESCALATION - ${escalationLevel.toUpperCase()}]\n` +
                    `Safety event for participant ${eventData.participantId} ` +
                    `has not been responded to in ${Math.round(minutesSinceCreation)} minutes.\n` +
                    `Please log a disposition immediately.\n` +
                    `Dashboard: https://socialscope-dashboard.web.app`,
              from: fromNumber,
              to: `+1${escalationTarget.phone}`,
            });

            console.log(`Escalation SMS sent to ${escalationLevel} (${escalationTarget.name}): ${result.sid}`);

            // Mark escalation as sent
            const updateData = {};
            updateData[`${escalationLevel}Escalated`] = true;
            updateData[`${escalationLevel}EscalatedAt`] = admin.firestore.FieldValue.serverTimestamp();
            await doc.ref.update(updateData);

            // Log to audit trail
            await doc.ref.collection("audit_trail").doc().set({
              type: "escalation",
              escalationLevel,
              escalatedTo: escalationTarget.name,
              minutesSinceCreation: Math.round(minutesSinceCreation),
              loggedBy: "system",
              loggedAt: admin.firestore.FieldValue.serverTimestamp(),
            });
          } catch (err) {
            console.error(`Escalation to ${escalationLevel} failed:`, err.message);
          }
        }
      }
    } catch (err) {
      console.error("Escalation check error:", err);
    }
  }
);
