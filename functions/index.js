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
 * Sends an SMS via Twilio to the configured page target.
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
    const { participantId } = event.params;
    const pageTarget = alertData.pageTarget;

    if (!pageTarget) {
      console.error("No pageTarget in safety alert");
      return;
    }

    // Build SMS message
    const timestamp = alertData.triggeredAt
      ? alertData.triggeredAt.toDate().toLocaleString("en-US", {
          timeZone: "America/Chicago",
        })
      : new Date().toLocaleString("en-US", { timeZone: "America/Chicago" });

    const message =
      `[SocialScope SAFETY ALERT]\n` +
      `Participant: ${participantId}\n` +
      `Time: ${timestamp}\n` +
      `A participant endorsed imminent self-harm risk during check-in.`;

    try {
      const client = require("twilio")(
        twilioAccountSid.value(),
        twilioAuthToken.value()
      );

      const result = await client.messages.create({
        body: message,
        from: twilioFromNumber.value(),
        to: `+1${pageTarget}`,
      });

      console.log(`SMS sent successfully. SID: ${result.sid}`);

      // Mark the alert as handled
      await snapshot.ref.update({
        handled: true,
        smsSid: result.sid,
        smsStatus: result.status,
        handledAt: admin.firestore.FieldValue.serverTimestamp(),
      });
    } catch (error) {
      console.error("Error sending Twilio SMS:", error);

      // Log the failure on the document
      await snapshot.ref.update({
        smsError: error.message,
        smsAttemptedAt: admin.firestore.FieldValue.serverTimestamp(),
      });
    }
  }
);
