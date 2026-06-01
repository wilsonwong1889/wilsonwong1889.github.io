"""Backend tests — notification provider payload verification.

These tests prove the SendGrid email integration and the Twilio SMS
integration build the right request payloads when the provider backends
are enabled. They mock the SDK / HTTP layer so we never hit a real
provider — the goal is to catch regressions in the request *shape*
(auth header, from/to addresses, body, subject, ICS attachment encoding)
that would otherwise only surface when a real customer didn't receive
their email or SMS.

This closes the formerly `not_working` "Live email and SMS provider
verification" entry in the admin test catalog
(backend/app/services/test_case_service.py).
"""
import base64
import importlib
import os
import sys
import unittest
from io import BytesIO
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class NotificationProviderTest(unittest.TestCase):
    """No DB needed — these are pure integration shape tests for the
    notification_service module."""

    @classmethod
    def setUpClass(cls) -> None:
        # Re-import notification_service fresh so settings overrides below
        # take effect.
        import app.services.notification_service as ns
        cls.ns = ns

    def _with_settings(self, **overrides):
        """Patch app.config.settings attributes for the duration of a test."""
        from app.config import settings
        return mock.patch.multiple(settings, **overrides)

    # ── SendGrid ──────────────────────────────────────────────────────────

    def test_sendgrid_send_email_builds_mail_with_expected_fields(self) -> None:
        captured = {}

        class FakeResponse:
            status_code = 202

        class FakeClient:
            def __init__(self, api_key):
                captured["api_key"] = api_key

            def send(self, message):
                captured["message"] = message
                return FakeResponse()

        with self._with_settings(
            EMAIL_BACKEND="sendgrid",
            SENDGRID_API_KEY="SG.realtestkeyABC123",
            EMAIL_FROM="studio@bipoc.example",
            EMAIL_REPLY_TO="reply@bipoc.example",
        ), mock.patch.object(self.ns, "SendGridAPIClient", FakeClient):
            result = self.ns.send_email(
                to_email="customer@example.com",
                subject="Booking confirmed",
                plain_text_content="Hi there",
                html_content="<p>Hi there</p>",
            )

        self.assertEqual(result, {"backend": "sendgrid", "status_code": 202})
        self.assertEqual(captured["api_key"], "SG.realtestkeyABC123")
        mail = captured["message"]
        # Mail object exposes from/to/subject/content via get() but we
        # poke its attributes — SendGrid SDK stores them as private dicts.
        rendered = mail.get()
        self.assertEqual(rendered["from"]["email"], "studio@bipoc.example")
        self.assertEqual(rendered["personalizations"][0]["to"][0]["email"], "customer@example.com")
        self.assertEqual(rendered["subject"], "Booking confirmed")
        self.assertEqual(rendered["reply_to"]["email"], "reply@bipoc.example")
        plain = next(c for c in rendered["content"] if c["type"] == "text/plain")
        html = next(c for c in rendered["content"] if c["type"] == "text/html")
        self.assertEqual(plain["value"], "Hi there")
        self.assertEqual(html["value"], "<p>Hi there</p>")

    def test_sendgrid_send_email_attaches_ics_base64_encoded(self) -> None:
        captured = {}

        class FakeResponse:
            status_code = 202

        class FakeClient:
            def __init__(self, api_key):
                pass

            def send(self, message):
                captured["message"] = message
                return FakeResponse()

        ics_payload = b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        with self._with_settings(
            EMAIL_BACKEND="sendgrid",
            SENDGRID_API_KEY="SG.real-test-key",
            EMAIL_FROM="studio@bipoc.example",
            EMAIL_REPLY_TO="",
        ), mock.patch.object(self.ns, "SendGridAPIClient", FakeClient):
            self.ns.send_email(
                to_email="customer@example.com",
                subject="Booking confirmed",
                plain_text_content="Hi there",
                ics_bytes=ics_payload,
            )

        rendered = captured["message"].get()
        self.assertEqual(len(rendered.get("attachments", [])), 1)
        attachment = rendered["attachments"][0]
        self.assertEqual(attachment["filename"], "studio-booking.ics")
        self.assertEqual(attachment["type"], "text/calendar")
        self.assertEqual(attachment["disposition"], "attachment")
        # SendGrid base64-encodes the file content; round-trip to confirm.
        self.assertEqual(base64.b64decode(attachment["content"]), ics_payload)

    def test_sendgrid_send_email_rejects_placeholder_key(self) -> None:
        with self._with_settings(
            EMAIL_BACKEND="sendgrid",
            SENDGRID_API_KEY="placeholder-key-do-not-ship",
            EMAIL_FROM="studio@bipoc.example",
        ):
            with self.assertRaises(ValueError) as ctx:
                self.ns.send_email(
                    to_email="customer@example.com",
                    subject="x",
                    plain_text_content="y",
                )
            self.assertIn("SENDGRID_API_KEY", str(ctx.exception))

    # ── Twilio ────────────────────────────────────────────────────────────

    def test_twilio_send_sms_builds_basic_auth_request_with_form_payload(self) -> None:
        captured = {}

        class FakeResponse:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, *args, **kwargs):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["data"] = request.data
            captured["method"] = request.get_method()
            return FakeResponse()

        with self._with_settings(
            SMS_BACKEND="twilio",
            TWILIO_ACCOUNT_SID="AC_TEST_SID",
            TWILIO_AUTH_TOKEN="TEST_TOKEN",
            TWILIO_FROM_NUMBER="+15555550100",
        ), mock.patch.object(self.ns, "urlopen", fake_urlopen):
            result = self.ns.send_sms(
                to_number="4035559999",
                body="Your booking is confirmed.",
            )

        self.assertEqual(result, {"backend": "twilio", "status_code": 201})
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["url"],
            "https://api.twilio.com/2010-04-01/Accounts/AC_TEST_SID/Messages.json",
        )
        # Basic auth header is base64(SID:TOKEN)
        expected_auth = "Basic " + base64.b64encode(b"AC_TEST_SID:TEST_TOKEN").decode()
        # urllib normalizes header names to title-case (Authorization, Content-type)
        self.assertEqual(captured["headers"].get("Authorization"), expected_auth)
        self.assertEqual(captured["headers"].get("Content-type"), "application/x-www-form-urlencoded")

        # urlencoded body should carry the three Twilio fields with our 10-digit
        # number normalised to E.164 (+1 prefix).
        body = captured["data"].decode("utf-8")
        body_fields = dict(pair.split("=", 1) for pair in body.split("&"))
        from urllib.parse import unquote_plus
        self.assertEqual(unquote_plus(body_fields["To"]), "+14035559999")
        self.assertEqual(unquote_plus(body_fields["From"]), "+15555550100")
        self.assertEqual(unquote_plus(body_fields["Body"]), "Your booking is confirmed.")

    def test_twilio_send_sms_normalises_phone_to_e164(self) -> None:
        cases = [
            ("4035559999", "+14035559999"),  # 10-digit Canada/US
            ("14035559999", "+14035559999"),  # 11-digit with country prefix
            ("+14035559999", "+14035559999"),  # already E.164
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.ns.normalize_phone_number(raw), expected)

    def test_twilio_send_sms_rejects_missing_credentials(self) -> None:
        with self._with_settings(
            SMS_BACKEND="twilio",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        ):
            with self.assertRaises(ValueError) as ctx:
                self.ns.send_sms(to_number="4035559999", body="x")
            self.assertIn("Twilio", str(ctx.exception))

    def test_disabled_backend_short_circuits_without_provider_call(self) -> None:
        with self._with_settings(EMAIL_BACKEND="disabled"):
            result = self.ns.send_email(
                to_email="customer@example.com",
                subject="x",
                plain_text_content="y",
            )
        self.assertEqual(result["backend"], "disabled")
        self.assertEqual(result["status_code"], 204)

    def test_console_fallback_returns_payload_for_inspection(self) -> None:
        with self._with_settings(EMAIL_BACKEND="console"):
            result = self.ns.send_email(
                to_email="customer@example.com",
                subject="hello",
                plain_text_content="world",
            )
        self.assertEqual(result["backend"], "console")
        self.assertEqual(result["status_code"], 202)
        import json
        body = json.loads(result["message"])
        self.assertEqual(body["to"], "customer@example.com")
        self.assertEqual(body["subject"], "hello")
        self.assertEqual(body["body"], "world")
        self.assertFalse(body["has_ics"])
