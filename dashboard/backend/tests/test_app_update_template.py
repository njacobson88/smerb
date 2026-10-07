"""The app-update notification must render cleanly for every platform and
with missing data — a KeyError here would surface as a 500 on Send."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compliance_notifications import (  # noqa: E402
    APP_UPDATE_STEPS, INSTALL_URL, LOW_COMPLIANCE_TEMPLATES, app_update_steps, pipe_template,
)
from template_utils import safe_format  # noqa: E402


def vars_for(platform):
    return {
        "name": "Robin",
        "participant_id": "693493543",
        "current_version": "1.0.18 (build 18)",
        "latest_version": "1.0.20 (build 20)",
        "platform_label": {"ios": "iPhone", "android": "Android"}.get(platform, "your phone"),
        "update_steps": app_update_steps(platform),
        "release_notes": "You can now go back to a previous question during a check-in.",
        "install_url": INSTALL_URL,
    }


class TestAppUpdateTemplates(unittest.TestCase):
    def test_category_registered(self):
        self.assertIn("app_update", LOW_COMPLIANCE_TEMPLATES)
        self.assertGreaterEqual(len(LOW_COMPLIANCE_TEMPLATES["app_update"]), 2)

    def test_every_template_renders_for_every_platform(self):
        for platform in ("ios", "android", None, "weird"):
            for t in LOW_COMPLIANCE_TEMPLATES["app_update"]:
                out = pipe_template(t, vars_for(platform))      # raises KeyError if a placeholder is unmet
                self.assertIn("1.0.20", out["body"])
                self.assertIn("1.0.18", out["body"])
                self.assertIn(INSTALL_URL, out["body"])
                self.assertIn("SocialScope icon", out["body"])   # the name on their home screen
                self.assertNotIn("{", out["body"])               # nothing left unfilled

    def test_templates_also_pass_the_strict_custom_renderer(self):
        # Staff can edit the body; safe_format must accept the same placeholders.
        for t in LOW_COMPLIANCE_TEMPLATES["app_update"]:
            self.assertNotIn("{", safe_format(t["body"], vars_for("ios")))

    def test_platform_steps_are_platform_specific(self):
        ios, android, unk = app_update_steps("ios"), app_update_steps("android"), app_update_steps(None)
        self.assertIn("VPN & Device Management", ios)
        self.assertNotIn("Play Store", ios)
        self.assertIn("Allow from this source", android)
        self.assertNotIn("VPN & Device Management", android.split("3.")[0])
        self.assertIn("iPhone", unk); self.assertIn("Android", unk)
        for steps in (ios, android, unk):
            self.assertIn(INSTALL_URL, steps)
            self.assertIn("already signed in", steps)

    def test_platform_aliases(self):
        self.assertEqual(app_update_steps("iPhone"), APP_UPDATE_STEPS["ios"].format(install_url=INSTALL_URL))
        self.assertEqual(app_update_steps("ANDROID"), APP_UPDATE_STEPS["android"].format(install_url=INSTALL_URL))

    def test_participant_facing_name(self):
        for t in LOW_COMPLIANCE_TEMPLATES["app_update"]:
            self.assertIn("Social Media Wellness", t["subject"] + t["body"])
            # The app itself is referred to by the icon name only once, as a bridge.
            self.assertNotIn("SocialScope Team", t["body"])


if __name__ == "__main__":
    unittest.main()
