"""Unit tests for the Microsoft Graph email module (pure parts)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import graph_email as g


class TestBuildGraphMessage(unittest.TestCase):
    def test_html_message(self):
        m = g.build_graph_message("a@b.edu", "Hi", html="<p>x</p>")
        self.assertEqual(m["message"]["subject"], "Hi")
        self.assertEqual(m["message"]["body"]["contentType"], "HTML")
        self.assertEqual(m["message"]["body"]["content"], "<p>x</p>")
        self.assertEqual(m["message"]["toRecipients"][0]["emailAddress"]["address"], "a@b.edu")
        self.assertFalse(m["saveToSentItems"])

    def test_text_message(self):
        m = g.build_graph_message("a@b.edu", "Hi", text="plain")
        self.assertEqual(m["message"]["body"]["contentType"], "Text")
        self.assertEqual(m["message"]["body"]["content"], "plain")

    def test_html_wins_over_text(self):
        m = g.build_graph_message("a@b.edu", "Hi", html="<b>h</b>", text="t")
        self.assertEqual(m["message"]["body"]["contentType"], "HTML")
        self.assertEqual(m["message"]["body"]["content"], "<b>h</b>")

    def test_no_attachments_key_when_none(self):
        m = g.build_graph_message("a@b.edu", "Hi", text="x")
        self.assertNotIn("attachments", m["message"])

    def test_attachment(self):
        m = g.build_graph_message("a@b.edu", "Hi", text="x", attachments=[
            {"name": "r.pdf", "contentType": "application/pdf", "contentBytes": "QUJD"}])
        att = m["message"]["attachments"][0]
        self.assertEqual(att["@odata.type"], "#microsoft.graph.fileAttachment")
        self.assertEqual(att["name"], "r.pdf")
        self.assertEqual(att["contentType"], "application/pdf")
        self.assertEqual(att["contentBytes"], "QUJD")

    def test_attachment_default_content_type(self):
        m = g.build_graph_message("a@b.edu", "Hi", text="x", attachments=[
            {"name": "f.bin", "contentBytes": "QQ=="}])
        self.assertEqual(m["message"]["attachments"][0]["contentType"], "application/octet-stream")


class TestConfigured(unittest.TestCase):
    def _set(self, ten, cid, sec):
        for k, v in (("MSGRAPH_TENANT_ID", ten), ("MSGRAPH_CLIENT_ID", cid),
                     ("MSGRAPH_CLIENT_SECRET", sec)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def tearDown(self):
        self._set(None, None, None)

    def test_all_present(self):
        self._set("t", "c", "s")
        self.assertTrue(g.graph_email_configured())

    def test_missing_any(self):
        self._set("t", "c", None)
        self.assertFalse(g.graph_email_configured())
        self._set("t", None, "s")
        self.assertFalse(g.graph_email_configured())
        self._set(None, "c", "s")
        self.assertFalse(g.graph_email_configured())

    def test_blank_secret_is_unconfigured(self):
        self._set("t", "c", "   ")
        self.assertFalse(g.graph_email_configured())


if __name__ == "__main__":
    unittest.main()
