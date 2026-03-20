const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { defineSecret } = require("firebase-functions/params");
const admin = require("firebase-admin");
const nodemailer = require("nodemailer");

admin.initializeApp();

// Twilio credentials stored as Firebase secrets
const twilioAccountSid = defineSecret("TWILIO_ACCOUNT_SID");
const twilioAuthToken = defineSecret("TWILIO_AUTH_TOKEN");
const twilioFromNumber = defineSecret("TWILIO_FROM_NUMBER");

// Slack email-to-channel address and sender email config
const slackChannelEmail = defineSecret("SLACK_CHANNEL_EMAIL");
const alertSenderEmail = defineSecret("ALERT_SENDER_EMAIL");
const alertSenderPassword = defineSecret("ALERT_SENDER_PASSWORD");

/**
 * Send an email to the Slack channel via email-to-channel integration.
 * Uses Gmail SMTP (works with Google Workspace / Gmail app passwords).
 */
async function sendSlackEmail({ senderEmail, senderPassword, slackEmail, subject, body }) {
  const transporter = nodemailer.createTransport({
    service: "gmail",
    auth: {
      user: senderEmail,
      pass: senderPassword,
    },
  });

  await transporter.sendMail({
    from: `"SocialScope Alerts" <${senderEmail}>`,
    to: slackEmail,
    subject: subject,
    text: body,
  });
}

/**
 * Triggered when a safety alert is created in Firestore.
 * Sends an SMS via Twilio AND a Slack notification (via email-to-channel).
 * Recipients are stored in the alert_recipients collection.
 */
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

    // Build timestamp string
    const timestamp = alertData.triggeredAt
      ? alertData.triggeredAt.toDate().toLocaleString("en-US", {
          timeZone: "America/New_York",
        })
      : new Date().toLocaleString("en-US", { timeZone: "America/New_York" });

    // ================================================================
    // Slack Notification (via email-to-channel)
    // ================================================================
    let slackResult = null;
    let slackError = null;

    const slackEmail = slackChannelEmail.value();
    const senderEmail = alertSenderEmail.value();
    const senderPass = alertSenderPassword.value();

    if (slackEmail && senderEmail && senderPass) {
      try {
        const subject = `SAFETY ALERT - Participant ${participantId}`;
        const body =
          `[SocialScope SAFETY ALERT]\n\n` +
          `Participant: ${participantId}\n` +
          `Time: ${timestamp}\n\n` +
          `A participant endorsed imminent self-harm risk during check-in.\n\n` +
          `View dashboard: https://socialscope-dashboard.web.app\n\n` +
          `Alert ID: ${alertId}`;

        await sendSlackEmail({
          senderEmail: senderEmail,
          senderPassword: senderPass,
          slackEmail: slackEmail,
          subject,
          body,
        });

        slackResult = "sent";
        console.log(`Slack email notification sent for alert ${alertId}`);
      } catch (err) {
        slackError = err.message;
        console.error(`Slack email notification failed for alert ${alertId}:`, err.message);
      }
    } else {
      console.warn("Slack email config incomplete - notification skipped");
    }

    // ================================================================
    // Twilio SMS
    // ================================================================

    // Get all configured alert recipients from Firestore
    const recipientsSnapshot = await admin
      .firestore()
      .collection("alert_recipients")
      .get();

    const recipients = [];
    recipientsSnapshot.forEach((doc) => {
      const data = doc.to_dict ? doc.to_dict() : doc.data();
      recipients.push({
        phone: doc.id,
        name: data.name || null,
      });
    });

    // Also include the legacy pageTarget if specified (backwards compatibility)
    if (alertData.pageTarget && !recipients.find(r => r.phone === alertData.pageTarget)) {
      recipients.push({ phone: alertData.pageTarget, name: "Legacy Target" });
    }

    const smsMessage =
      `[SocialScope SAFETY ALERT]\n` +
      `Participant: ${participantId}\n` +
      `Time: ${timestamp}\n` +
      `A participant endorsed imminent self-harm risk during check-in.\n` +
      `View details: https://socialscope-dashboard.web.app`;

    let smsResults = [];
    let smsErrors = [];

    if (recipients.length === 0) {
      console.warn("No alert recipients configured - SMS not sent");
    } else {
      try {
        const client = require("twilio")(
          twilioAccountSid.value(),
          twilioAuthToken.value()
        );

        for (const recipient of recipients) {
          try {
            const result = await client.messages.create({
              body: smsMessage,
              from: twilioFromNumber.value(),
              to: `+1${recipient.phone}`,
            });
            smsResults.push({
              phone: recipient.phone,
              name: recipient.name,
              sid: result.sid,
              status: result.status,
            });
            console.log(`SMS sent to ${recipient.name || recipient.phone}. SID: ${result.sid}`);
          } catch (recipientError) {
            smsErrors.push({
              phone: recipient.phone,
              name: recipient.name,
              error: recipientError.message,
            });
            console.error(`Failed to send SMS to ${recipient.phone}:`, recipientError.message);
          }
        }
      } catch (error) {
        console.error("Error initializing Twilio client:", error);
        smsErrors.push({ error: error.message });
      }
    }

    // ================================================================
    // Update alert document with all notification results
    // ================================================================
    await snapshot.ref.update({
      handled: smsResults.length > 0 || slackResult === "sent",
      // SMS results
      smsResults: smsResults.length > 0 ? smsResults : null,
      smsErrors: smsErrors.length > 0 ? smsErrors : null,
      recipientCount: recipients.length,
      successCount: smsResults.length,
      // Slack results
      slackResult: slackResult,
      slackError: slackError,
      // Timestamp
      handledAt: admin.firestore.FieldValue.serverTimestamp(),
    });

    console.log(
      `Safety alert ${alertId}: SMS ${smsResults.length}/${recipients.length}, Slack: ${slackResult || "skipped"}`
    );
  }
);
