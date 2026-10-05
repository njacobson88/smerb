/**
 * Regression tests for Secret Manager value sanitization.
 *
 * The case that matters: a trailing newline on ALERT_SENDER_EMAIL broke every
 * safety-alert Slack email for seven months. These tests fail if anything
 * reintroduces an untrimmed read or an unvalidated mailbox.
 *
 * Run: node --test functions/test/
 */
const test = require("node:test");
const assert = require("node:assert");
const { secretValue, assertSafeMailbox } = require("../secret_utils");

const stub = (v) => ({ value: () => v });

test("secretValue strips the trailing newline that broke Graph sendMail", () => {
  assert.strictEqual(
    secretValue(stub("Social.Media.Wellness@dartmouth.edu\n")),
    "Social.Media.Wellness@dartmouth.edu");
});

test("secretValue strips \\r\\n, spaces and tabs", () => {
  for (const raw of ["a@b.edu\r\n", "  a@b.edu  ", "\ta@b.edu\n"]) {
    assert.strictEqual(secretValue(stub(raw)), "a@b.edu");
  }
});

test("secretValue leaves a clean value untouched", () => {
  assert.strictEqual(secretValue(stub("a@b.edu")), "a@b.edu");
});

test("secretValue returns empty string for unset or throwing secrets", () => {
  assert.strictEqual(secretValue(stub("")), "");
  assert.strictEqual(secretValue(stub(null)), "");
  assert.strictEqual(secretValue(stub(undefined)), "");
  assert.strictEqual(secretValue({ value: () => { throw new Error("unset"); } }), "");
});

test("secretValue coerces non-strings without throwing", () => {
  assert.strictEqual(secretValue(stub(12345)), "12345");
});

test("assertSafeMailbox accepts a clean address", () => {
  assert.strictEqual(
    assertSafeMailbox("Social.Media.Wellness@dartmouth.edu"),
    "Social.Media.Wellness@dartmouth.edu");
});

test("assertSafeMailbox normalizes surrounding whitespace rather than rejecting", () => {
  // The production failure was a TRAILING newline. Trimming is the right
  // response — reject only what survives the trim.
  for (const raw of ["a@b.edu\n", "a@b.edu\r\n", "  a@b.edu\t"]) {
    assert.strictEqual(assertSafeMailbox(raw), "a@b.edu");
  }
});

test("assertSafeMailbox rejects characters embedded inside the address", () => {
  // These survive trim() and would still corrupt the URL path.
  for (const bad of ["a@b .edu", "a@b\n.edu", "a@b\t.edu", 'a@"b.edu', "a@<b>.edu"]) {
    assert.throws(() => assertSafeMailbox(bad), /malformed/);
  }
});

test("assertSafeMailbox rejects empty and missing addresses", () => {
  for (const bad of ["", "   ", null, undefined]) {
    assert.throws(() => assertSafeMailbox(bad), /malformed/);
  }
});

test("assertSafeMailbox names the field in the error", () => {
  assert.throws(
    () => assertSafeMailbox("bad addr", "Slack channel address"),
    /Slack channel address/);
});
