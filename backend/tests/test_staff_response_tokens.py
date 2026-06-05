"""Step 5: secure one-time accept/decline links for staff."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffResponseTokenTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="token-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0099",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "token-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _customer_headers(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Customer", "phone": "403-555-0100"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _booking_id(self, email, *, hour=10) -> str:
        admin = self._admin_headers()
        staff = self.client.post(
            "/api/admin/staff",
            json={"name": f"Tok Engineer {email}", "booking_rate_cents": 6000, "active": True, "schedule_published": True},
            headers=admin,
        ).json()
        start = self._future_time(day=1, hour=hour)
        self._make_staff_available_for_time(staff["id"], start)
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers(email),
            json={"staff_profile_id": staff["id"], "start_time": start.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def _mint_token(self, booking_id, *, expired=False) -> str:
        from app.models.staff_booking import StaffBooking
        from app.services.staff_token_service import _hash_token, create_response_token

        with self.SessionLocal() as db:
            booking = db.query(StaffBooking).filter(StaffBooking.id == booking_id).first()
            raw = create_response_token(db, booking)
            if expired:
                from app.models.staff_booking_token import StaffBookingResponseToken
                # Target exactly the token we just minted (creation also mints one
                # via the eager notification dispatch).
                token = db.query(StaffBookingResponseToken).filter(
                    StaffBookingResponseToken.token_hash == _hash_token(raw)
                ).first()
                token.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
        return raw

    def test_01_accept_link_accepts(self) -> None:
        booking_id = self._booking_id("t1@example.com")
        token = self._mint_token(booking_id)
        resp = self.client.post(f"/api/staff-bookings/{booking_id}/accept?token={token}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "AcceptedPendingPayment")

    def test_02_token_is_one_time(self) -> None:
        booking_id = self._booking_id("t2@example.com")
        token = self._mint_token(booking_id)
        self.assertEqual(
            self.client.post(f"/api/staff-bookings/{booking_id}/accept?token={token}").status_code, 200
        )
        # Reuse -> rejected (already used).
        resp = self.client.post(f"/api/staff-bookings/{booking_id}/decline?token={token}")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_03_decline_link_declines(self) -> None:
        booking_id = self._booking_id("t3@example.com")
        token = self._mint_token(booking_id)
        resp = self.client.post(
            f"/api/staff-bookings/{booking_id}/decline?token={token}&reason=Busy"
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "Declined")
        self.assertEqual(resp.json()["cancellation_reason"], "Busy")

    def test_04_invalid_token_rejected(self) -> None:
        booking_id = self._booking_id("t4@example.com")
        resp = self.client.post(f"/api/staff-bookings/{booking_id}/accept?token=not-a-real-token")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_05_expired_token_rejected(self) -> None:
        booking_id = self._booking_id("t5@example.com")
        token = self._mint_token(booking_id, expired=True)
        resp = self.client.post(f"/api/staff-bookings/{booking_id}/accept?token={token}")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_06_fresh_token_after_response_conflicts(self) -> None:
        booking_id = self._booking_id("t6@example.com")
        first = self._mint_token(booking_id)
        self.assertEqual(
            self.client.post(f"/api/staff-bookings/{booking_id}/accept?token={first}").status_code, 200
        )
        # A new token can't re-accept an already-accepted (non-Requested) booking.
        second = self._mint_token(booking_id)
        resp = self.client.post(f"/api/staff-bookings/{booking_id}/accept?token={second}")
        self.assertEqual(resp.status_code, 409, resp.text)
