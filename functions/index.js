const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { defineSecret } = require("firebase-functions/params");
const admin = require("firebase-admin");

admin.initializeApp();

// Twilio credentials stored as Firebase secrets
const twilioAccountSid = defineSecret("TWILIO_ACCOUNT_SID");
const twilioAuthToken = defineSecret("TWILIO_AUTH_TOKEN");
const twilioFromNumber = defineSecret("TWILIO_FROM_NUMBER");

/**
 * Triggered when a safety alert is created in Firestore.
 * Sends an SMS via Twilio to ALL configured alert recipients.
 * Recipients are stored in the alert_recipients collection.
 */
exports.onSafetyAlert = onDocumentCreated(
  {
    document: "participants/{participantId}/safety_alerts/{alertId}",
    secrets: [twilioAccountSid, twilioAuthToken, twilioFromNumber],
  },
  async (event) => {
    const snapshot = event.data;
    if (!snapshot) {
      console.log("No data in safety alert document");
      return;
    }

    const alertData = snapshot.data();
    const { participantId, alertId } = event.params;

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

    if (recipients.length === 0) {
      console.warn("No alert recipients configured - SMS not sent");
      await snapshot.ref.update({
        smsError: "No recipients configured",
        smsAttemptedAt: admin.firestore.FieldValue.serverTimestamp(),
      });
      return;
    }

    // Build SMS message
    const timestamp = alertData.triggeredAt
      ? alertData.triggeredAt.toDate().toLocaleString("en-US", {
          timeZone: "America/New_York",
        })
      : new Date().toLocaleString("en-US", { timeZone: "America/New_York" });

    const message =
      `[SocialScope SAFETY ALERT]\n` +
      `Participant: ${participantId}\n` +
      `Time: ${timestamp}\n` +
      `A participant endorsed imminent self-harm risk during check-in.\n` +
      `View details: https://socialscope-dashboard.web.app`;

    try {
      const client = require("twilio")(
        twilioAccountSid.value(),
        twilioAuthToken.value()
      );

      const results = [];
      const errors = [];

      // Send SMS to all recipients
      for (const recipient of recipients) {
        try {
          const result = await client.messages.create({
            body: message,
            from: twilioFromNumber.value(),
            to: `+1${recipient.phone}`,
          });
          results.push({
            phone: recipient.phone,
            name: recipient.name,
            sid: result.sid,
            status: result.status,
          });
          console.log(`SMS sent to ${recipient.name || recipient.phone}. SID: ${result.sid}`);
        } catch (recipientError) {
          errors.push({
            phone: recipient.phone,
            name: recipient.name,
            error: recipientError.message,
          });
          console.error(`Failed to send SMS to ${recipient.phone}:`, recipientError.message);
        }
      }

      // Update the alert document with results
      await snapshot.ref.update({
        handled: results.length > 0,
        smsResults: results,
        smsErrors: errors.length > 0 ? errors : null,
        recipientCount: recipients.length,
        successCount: results.length,
        handledAt: admin.firestore.FieldValue.serverTimestamp(),
      });

      console.log(`Safety alert ${alertId}: Sent ${results.length}/${recipients.length} SMS messages`);
    } catch (error) {
      console.error("Error initializing Twilio client:", error);

      await snapshot.ref.update({
        smsError: error.message,
        smsAttemptedAt: admin.firestore.FieldValue.serverTimestamp(),
      });
    }
  }
);
