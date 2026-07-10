"""Tests for the notification gaps: reschedule + payment-state emails, the
admin NotificationLog view, and the CASL unsubscribe flow."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import notification_service
from tests.base import BaseAppTest


class NotificationTemplateTest(unittest.TestCase):
    """Unit tests for the new email templates (send_email mocked)."""

    def _capture(self):
        captured = {}

        def fake_send_email(**kwargs):
            captured.update(kwargs)
            return {"backend": "console", "status_code": 202}

        return captured, fake_send_email

    def test_html_wrap_unsubscribe_footer_conditional(self) -> None:
        without = notification_service._html_wrap("<p>hi</p>")
        self.assertNotIn("Unsubscribe", without)
        with_url = notification_service._html_wrap(
            "<p>hi</p>", unsubscribe_url="https://example.com/u?token=abc"
        )
        self.assertIn("Unsubscribe", with_url)
        self.assertIn("https://example.com/u?token=abc", with_url)

    def test_booking_rescheduled_email(self) -> None:
        captured, fake = self._capture()
        new_start = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
        prev_start = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
        with patch.object(notification_service, "send_email", fake):
            notification_service.booking_rescheduled_email(
                to_email="user@example.com",
                booking_code="BK-123",
                new_start_dt=new_start,
                new_end_dt=new_start + timedelta(hours=1),
                previous_start_dt=prev_start,
                full_name="Rae Booker",
                room_name="Studio A",
                duration_minutes=60,
                booking_id="bid-1",
                unsubscribe_url="https://example.com/u?token=t",
            )
        self.assertIn("rescheduled", captured["subject"].lower())
        self.assertIn("BK-123", captured["plain_text_content"])
        self.assertIn("Previous time", captured["html_content"])
        self.assertIn("Unsubscribe", captured["html_content"])
        self.assertIsNotNone(captured["ics_bytes"])  # updated invite attached

    def test_deposit_paid_email_shows_balance(self) -> None:
        captured, fake = self._capture()
        start = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
        with patch.object(notification_service, "send_email", fake):
            notification_service.deposit_paid_email(
                to_email="user@example.com",
                booking_code="BK-9",
                deposit_paid_cents=2100,
                balance_due_cents=3000,
                start_dt=start,
                end_dt=start + timedelta(hours=1),
                full_name="Dee Posit",
                room_name="Studio B",
                duration_minutes=60,
            )
        self.assertIn("deposit", captured["subject"].lower())
        self.assertIn("Balance due", captured["html_content"])
        self.assertIn("$30.00", captured["html_content"])  # balance
        self.assertIn("$21.00", captured["html_content"])  # deposit paid
        self.assertIsNotNone(captured["ics_bytes"])

    def test_payment_failed_email(self) -> None:
        captured, fake = self._capture()
        with patch.object(notification_service, "send_email", fake):
            notification_service.payment_failed_email(
                to_email="user@example.com",
                booking_code="BK-77",
                full_name="Pay Fail",
                room_name="Studio C",
                start_dt=datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc),
            )
        self.assertIn("didn't go through", captured["subject"].lower())
        self.assertIn("released", captured["html_content"].lower())
        self.assertIn("BK-77", captured["plain_text_content"])


class UnsubscribeEndpointTest(BaseAppTest):
    def _make_user(self, email="unsub@example.com"):
        with self.SessionLocal() as db:
            user = self.User(
                email=email,
                password_hash="x",
                full_name="Unsub User",
                opt_in_email=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return str(user.id), str(user.unsubscribe_token)

    def _opt_in(self, user_id) -> bool:
        with self.SessionLocal() as db:
            return db.query(self.User).filter(self.User.id == user_id).one().opt_in_email

    def test_unsubscribe_token_is_assigned_on_create(self) -> None:
        _, token = self._make_user()
        self.assertTrue(token)

    def test_get_landing_does_not_unsubscribe(self) -> None:
        user_id, token = self._make_user()
        resp = self.client.get(f"/api/notifications/unsubscribe?token={token}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("Unsubscribe", resp.text)
        # GET is prefetch-safe: still subscribed.
        self.assertTrue(self._opt_in(user_id))

    def test_post_unsubscribe_then_resubscribe(self) -> None:
        user_id, token = self._make_user()
        resp = self.client.post("/api/notifications/unsubscribe", data={"token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(self._opt_in(user_id))

        resp = self.client.post("/api/notifications/resubscribe", data={"token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(self._opt_in(user_id))

    def test_invalid_token_is_handled_gracefully(self) -> None:
        resp = self.client.get("/api/notifications/unsubscribe?token=not-a-uuid")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("invalid", resp.text.lower())
        resp = self.client.post("/api/notifications/unsubscribe", data={"token": "not-a-uuid"})
        self.assertEqual(resp.status_code, 200, resp.text)


class AdminNotificationLogViewTest(BaseAppTest):
    def _admin_headers(self):
        with self.SessionLocal() as db:
            type(self).ensure_admin_user(
                db, email="notif-admin@example.com", password="Password123!"
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "notif-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _seed_log(self, notification_type="deposit_paid_email_worker", status="Sent", email="loguser@example.com"):
        with self.SessionLocal() as db:
            user = self.User(email=email, password_hash="x", full_name="Log User")
            db.add(user)
            db.commit()
            db.refresh(user)
            log = self.NotificationLog(
                user_id=user.id,
                booking_id=None,
                type=notification_type,
                status=status,
                details={"delivery": {"backend": "supabase", "status_code": 200}},
                sent_at=datetime.now(timezone.utc),
            )
            db.add(log)
            db.commit()

    def test_requires_admin(self) -> None:
        resp = self.client.get("/api/admin/notifications")
        self.assertIn(resp.status_code, (401, 403), resp.text)

    def test_admin_lists_notifications(self) -> None:
        headers = self._admin_headers()
        self._seed_log()
        resp = self.client.get("/api/admin/notifications", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["type"], "deposit_paid_email_worker")
        self.assertEqual(row["status"], "Sent")
        self.assertEqual(row["user_email"], "loguser@example.com")
        self.assertEqual(row["backend"], "supabase")

    def test_admin_filters_by_status(self) -> None:
        headers = self._admin_headers()
        self._seed_log(notification_type="payment_failed_email_worker", status="Failed", email="failed@example.com")
        self._seed_log(notification_type="deposit_paid_email_worker", status="Sent", email="sent@example.com")
        resp = self.client.get("/api/admin/notifications?status=Failed", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "Failed" for r in rows))


if __name__ == "__main__":
    unittest.main()
