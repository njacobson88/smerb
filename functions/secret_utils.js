/**
 * Sanitizers for Secret Manager values.
 *
 * Extracted so they can be unit tested: a trailing newline on a secret is
 * invisible in the console, in logs, and in code review, and only surfaces when
 * the value reaches a wire protocol. On this project a newline on
 * ALERT_SENDER_EMAIL percent-encoded to %0A inside the Graph sendMail URL path;
 * Azure rejected it before authentication with an HTML "Bad Request - Invalid
 * URL" page, and every safety-alert Slack email failed for seven months without
 * anyone noticing — the error was recorded only inside the alert document.
 */

/**
 * Read a Secret Manager param with surrounding whitespace stripped.
 * Returns "" when the secret is unset or unreadable.
 */
function secretValue(param) {
  try {
    return String(param.value() || "").trim();
  } catch (_) {
    return "";
  }
}

/**
 * Validate an address that is about to be interpolated into a URL path.
 * Throws rather than letting a malformed value reach the wire, where the
 * resulting error names neither the field nor the cause.
 */
function assertSafeMailbox(address, label = "sender address") {
  const clean = String(address || "").trim();
  if (!clean || /[\s<>"]/.test(clean)) {
    throw new Error(`Refusing to send: malformed ${label} ${JSON.stringify(address)}`);
  }
  return clean;
}

module.exports = { secretValue, assertSafeMailbox };
