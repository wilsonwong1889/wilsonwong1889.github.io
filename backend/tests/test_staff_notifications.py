"""Step 6: staff booking request-flow notification tasks."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffNotificationTaskTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="notif-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0109",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "notif-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _customer_headers(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Real Customer", "phone": "403-555-0100"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _make_booking(self, customer_email, **staff_overrides) -> str:
        admin = self._admin_headers()
        staff_payload = {"name": f"Notify Engineer {customer_email}", "booking_rate_cents": 6000, "active": True, "schedule_published": True}
        staff_payload.update(staff_overrides)
        staff = self.client.post("/api/admin/staff", json=staff_payload, headers=admin).json()
        start = self._future_time(day=1, hour=10).isoformat()
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers(customer_email),
            json={"staff_profile_id": staff["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def test_01_request_email_sends_and_mints_token(self) -> None:
        from app.models.staff_booking_token import StaffBookingResponseToken
        from app.tasks import send_staff_booking_request_email_task

        booking_id = self._make_booking("notif1@example.com", notification_email="eng@example.com")
        result = send_staff_booking_request_email_task(booking_id)
        self.assertTrue(result["sent"])
        with self.SessionLocal() as db:
            tokens = (
                db.query(StaffBookingResponseToken)
                .filter(StaffBookingResponseToken.staff_booking_id == booking_id)
                .all()
            )
            # At least one accept/decline token was minted for the request.
            self.assertGreaterEqual(len(tokens), 1)

    def test_02_request_sms_skipped_when_disabled(self) -> None:
        from app.tasks import send_staff_booking_request_sms_task

        # notify_by_sms defaults to False -> task skips (no Twilio needed).
        booking_id = self._make_booking("notif2@example.com")
        result = send_staff_booking_request_sms_task(booking_id)
        self.assertFalse(result["sent"])

    def test_03_accepted_customer_email(self) -> None:
        from app.tasks import send_staff_booking_accepted_customer_email_task

        booking_id = self._make_booking("notif3@example.com")
        result = send_staff_booking_accepted_customer_email_task(booking_id)
        self.assertTrue(result["sent"])

    def test_04_declined_customer_email(self) -> None:
        from app.tasks import send_staff_booking_declined_customer_email_task

        booking_id = self._make_booking("notif4@example.com")
        result = send_staff_booking_declined_customer_email_task(booking_id)
        self.assertTrue(result["sent"])
