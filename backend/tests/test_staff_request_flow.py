"""Step 4: request-first staff booking lifecycle (Requested -> accept/decline)."""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffRequestFlowTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="reqflow-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0089",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "reqflow-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _customer_headers(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Customer", "phone": "403-555-0100"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _staff_id(self, admin_headers) -> str:
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Request Engineer", "booking_rate_cents": 6000, "active": True},
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def _book(self, staff_id, headers, *, hour=10):
        start = self._future_time(day=1, hour=hour).isoformat()
        return self.client.post(
            "/api/staff-bookings",
            headers=headers,
            json={"staff_profile_id": staff_id, "start_time": start, "duration_minutes": 60},
        )

    def _book_at(self, staff_id, headers, start):
        return self.client.post(
            "/api/staff-bookings",
            headers=headers,
            json={"staff_profile_id": staff_id, "start_time": start.isoformat(), "duration_minutes": 60},
        )

    def test_01_create_is_requested_without_payment(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        resp = self._book(staff_id, self._customer_headers("c1@example.com"))
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "Requested")
        self.assertIsNone(body["payment_client_secret"])
        self.assertIsNotNone(body["request_expires_at"])

    def test_02_accept_enables_payment(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        customer = self._customer_headers("c2@example.com")
        booking = self._book(staff_id, customer).json()

        accepted = self.client.post(
            f"/api/admin/staff-bookings/{booking['id']}/accept", headers=admin
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "AcceptedPendingPayment")
        self.assertTrue(accepted.json()["payment_client_secret"])

        session = self.client.post(
            f"/api/staff-bookings/{booking['id']}/payment-session", headers=customer
        )
        self.assertEqual(session.status_code, 200, session.text)
        self.assertTrue(session.json()["payment_intent_id"])

    def test_03_decline(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        booking = self._book(staff_id, self._customer_headers("c3@example.com")).json()
        resp = self.client.post(
            f"/api/admin/staff-bookings/{booking['id']}/decline",
            json={"reason": "Unavailable that day"},
            headers=admin,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "Declined")
        self.assertEqual(resp.json()["cancellation_reason"], "Unavailable that day")

    def test_04_double_accept_conflicts(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        booking = self._book(staff_id, self._customer_headers("c4@example.com")).json()
        self.assertEqual(
            self.client.post(f"/api/admin/staff-bookings/{booking['id']}/accept", headers=admin).status_code,
            200,
        )
        # Second accept is no longer valid (not Requested).
        resp = self.client.post(f"/api/admin/staff-bookings/{booking['id']}/accept", headers=admin)
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_05_requested_booking_holds_the_slot(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        first = self._book(staff_id, self._customer_headers("c5a@example.com"))
        self.assertEqual(first.status_code, 201, first.text)
        # A second customer can't request the same staff member at the same time.
        second = self._book(staff_id, self._customer_headers("c5b@example.com"))
        self.assertEqual(second.status_code, 409, second.text)

    def test_06_request_expires_after_window(self) -> None:
        from app.models.staff_booking import StaffBooking
        from app.services.staff_booking_service import expire_stale_pending_staff_bookings
        from datetime import datetime, timezone

        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        booking = self._book(staff_id, self._customer_headers("c6@example.com")).json()

        with self.SessionLocal() as db:
            row = db.query(StaffBooking).filter(StaffBooking.id == booking["id"]).first()
            row.created_at = datetime.now(timezone.utc) - timedelta(hours=49)
            db.commit()
            expire_stale_pending_staff_bookings(db)
            refreshed = db.query(StaffBooking).filter(StaffBooking.id == booking["id"]).first()
            self.assertEqual(refreshed.status, "Expired")

    def test_07_direct_booking_respects_staff_weekly_rules(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        friday_start = self._future_time(day=3, hour=12)
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={
                "weekday": friday_start.weekday(),
                "start_minute": 840,
                "end_minute": 1080,
            },
            headers=admin,
        )

        customer = self._customer_headers("c7@example.com")
        outside_rule = self._future_time(day=3, hour=10)
        resp = self._book_at(staff_id, customer, outside_rule)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"], "Selected staff member is not available for this time")

        inside_rule = self._book_at(staff_id, customer, friday_start)
        self.assertEqual(inside_rule.status_code, 201, inside_rule.text)

    def test_08_direct_booking_respects_blocked_exceptions(self) -> None:
        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        start = self._future_time(day=3, hour=12)
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={
                "weekday": start.weekday(),
                "start_minute": 720,
                "end_minute": 1200,
            },
            headers=admin,
        )
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/exceptions",
            json={
                "exception_date": start.date().isoformat(),
                "start_minute": start.hour * 60,
                "end_minute": start.hour * 60 + 60,
                "is_available": False,
            },
            headers=admin,
        )

        resp = self._book_at(staff_id, self._customer_headers("c8@example.com"), start)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"], "Selected staff member is not available for this time")

    def test_09_webhook_success_after_payment_expiry_auto_refunds(self) -> None:
        from datetime import datetime, timezone

        from app.config import settings
        from app.models.booking import AuditLog
        from app.models.staff_booking import StaffBooking
        from app.services.staff_booking_service import handle_staff_booking_payment_webhook_event

        admin = self._admin_headers()
        staff_id = self._staff_id(admin)
        booking = self._book(staff_id, self._customer_headers("c9@example.com")).json()
        accepted = self.client.post(f"/api/admin/staff-bookings/{booking['id']}/accept", headers=admin)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        payment_intent_id = accepted.json()["payment_intent_id"]

        with self.SessionLocal() as db:
            row = db.query(StaffBooking).filter(StaffBooking.id == booking["id"]).first()
            row.responded_at = datetime.now(timezone.utc) - timedelta(
                minutes=settings.PENDING_BOOKING_EXPIRY_MINUTES + 1
            )
            db.commit()

            result = handle_staff_booking_payment_webhook_event(
                db,
                {
                    "type": "payment_intent.succeeded",
                    "data": {
                        "object": {
                            "id": payment_intent_id,
                            "metadata": {
                                "booking_type": "staff",
                                "staff_booking_id": booking["id"],
                            },
                        }
                    },
                },
            )

            refreshed = db.query(StaffBooking).filter(StaffBooking.id == booking["id"]).first()
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.action == "staff_payment_received_after_expiry")
                .first()
            )

        self.assertTrue(result["auto_refunded"])
        self.assertEqual(result["status"], "Cancelled")
        self.assertEqual(refreshed.status, "Cancelled")
        self.assertIsNotNone(audit)
        self.assertTrue(audit.details["stripe_refund_id"].startswith("re_stub_"))
