"""
Backend tests — staff booking flows.

Covers: guest staff booking, promo discount on staff booking, staff booking
feed, contact update, admin lookup merging room and staff bookings.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from tests.base import BaseAppTest


class StaffTest(BaseAppTest):

    def test_22_guest_staff_booking_appears_in_feed(self) -> None:
        from app.models.promo_code import PromoCode
        from app.models.staff_booking import StaffBooking
        from app.models.staff_profile import StaffProfile
        from app.models.user import User

        with self.SessionLocal() as db:
            promo_code = PromoCode(
                code="SUMMER60",
                description="Opening checkout test discount",
                percent_off=60,
                active=True,
            )
            profile = StaffProfile(
                name="Podcast Engineer",
                description="Independent staff booking profile",
                skills=["Podcast support"],
                talents=["Editing"],
                add_on_price_cents=3500,
                booking_rate_cents=6500,
                service_types=["Podcast support", "Consultation"],
                booking_enabled=True,
                active=True,
            )
            db.add(promo_code)
            db.add(profile)
            db.commit()
            db.refresh(profile)
            profile_id = str(profile.id)

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=5, hour=11, minute=0)

        past_date = datetime.now(business_timezone).date() - timedelta(days=1)
        past_start = datetime(
            past_date.year, past_date.month, past_date.day, 11, 0, tzinfo=business_timezone
        )

        resp = self.client.get(f"/api/staff/{profile_id}/availability?date={past_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["available_start_times"], [])

        resp = self.client.post(
            "/api/staff-bookings/guest",
            json={
                "staff_profile_id": profile_id,
                "service_type": "Podcast support",
                "start_time": past_start.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Past Staff Guest",
                "guest_phone": "4035550134",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Bookings cannot be created for past dates or times")

        resp = self.client.post(
            "/api/staff-bookings/guest",
            json={
                "staff_profile_id": profile_id,
                "service_type": "Podcast support",
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "promo_code": "summer60",
                "guest_name": "Staff Guest",
                "guest_phone": "4035550133",
                "guest_email": "staff-guest@example.com",
                "notes": "Need production support for a remote podcast.",
            },
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertTrue(payload["access_token"])
        self.assertEqual(payload["booking"]["status"], "PendingPayment")
        self.assertEqual(payload["booking"]["service_type"], "Podcast support")
        staff_rate, promo_pct = 6500, 60
        expected_original = self._staff_price(staff_rate, 60)
        expected_discount = expected_original * promo_pct // 100
        self.assertEqual(payload["booking"]["original_price_cents"], expected_original)
        self.assertEqual(payload["booking"]["discount_cents"], expected_discount)
        self.assertEqual(payload["booking"]["price_cents"], expected_original - expected_discount)
        self.assertEqual(payload["booking"]["promo_code"], "SUMMER60")
        self.assertEqual(payload["booking"]["staff_profile"]["name"], "Podcast Engineer")

        guest_headers = {"Authorization": f"Bearer {payload['access_token']}"}
        resp = self.client.get(f"/api/staff-bookings/{payload['booking']['id']}", headers=guest_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["staff_profile"]["name"], "Podcast Engineer")

        resp = self.client.get("/api/bookings/feed", headers=guest_headers)
        self.assertEqual(resp.status_code, 200)
        feed = resp.json()
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["booking_kind"], "staff")
        self.assertEqual(feed[0]["staff_profile_name"], "Podcast Engineer")
        self.assertEqual(feed[0]["can_pay"], True)

        resp = self.client.post(
            f"/api/staff-bookings/{payload['booking']['id']}/payment-session",
            headers=guest_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["payment_intent_id"])
        self.assertTrue(resp.json()["payment_client_secret"])

        resp = self.client.put(
            f"/api/staff-bookings/{payload['booking']['id']}/contact",
            headers=guest_headers,
            json={
                "full_name": "Staff Checkout Guest",
                "email": "staff-checkout@example.com",
                "phone": "4035550144",
                "note": "Bring two microphones.",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_full_name"], "Staff Checkout Guest")
        self.assertEqual(resp.json()["user_email"], "staff-checkout@example.com")
        self.assertEqual(resp.json()["user_phone"], "4035550144")
        self.assertEqual(resp.json()["note"], "Bring two microphones.")

        with self.SessionLocal() as db:
            booking = db.query(StaffBooking).filter(StaffBooking.id == UUID(payload["booking"]["id"])).one()
            user = db.query(User).filter(User.id == booking.user_id).one()

        self.assertEqual(user.full_name, "Staff Guest")
        self.assertEqual(user.phone, "4035550133")
        self.assertEqual(user.email, "staff-guest@example.com")
        self.assertEqual(booking.user_full_name_snapshot, "Staff Checkout Guest")
        self.assertEqual(booking.user_email_snapshot, "staff-checkout@example.com")
        self.assertEqual(booking.user_phone_snapshot, "4035550144")
        self.assertEqual(booking.note, "Bring two microphones.")

    def test_23_admin_booking_lookup_includes_staff_bookings(self) -> None:
        from app.models.staff_profile import StaffProfile

        with self.SessionLocal() as db:
            type(self).ensure_admin_user(
                db,
                email="staff-admin@example.com",
                password="Password123!",
            )
            profile = StaffProfile(
                name="Independent Producer",
                description="Admin lookup should include this staff-only booking",
                skills=["Production"],
                talents=["Podcasting"],
                add_on_price_cents=3000,
                booking_rate_cents=7000,
                service_types=["Producer session"],
                booking_enabled=True,
                active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            profile_id = str(profile.id)

        start_time = self._future_time(day=6, hour=12, minute=0)

        resp = self.client.post(
            "/api/staff-bookings/guest",
            json={
                "staff_profile_id": profile_id,
                "service_type": "Producer session",
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Admin Staff Guest",
                "guest_phone": "4035550188",
                "guest_email": "admin-staff-guest@example.com",
            },
        )
        self.assertEqual(resp.status_code, 201)
        staff_booking = resp.json()["booking"]

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "staff-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.get(
            f"/api/admin/bookings?booking_code={staff_booking['booking_code']}",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        lookup_rows = resp.json()
        self.assertEqual(len(lookup_rows), 1)
        self.assertEqual(lookup_rows[0]["booking_kind"], "staff")
        self.assertEqual(lookup_rows[0]["staff_name"], "Independent Producer")
        self.assertEqual(lookup_rows[0]["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking['id']}/mark-paid",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")

        resp = self.client.get(
            f"/api/admin/bookings?booking_code={staff_booking['booking_code']}",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        refreshed_rows = resp.json()
        self.assertEqual(refreshed_rows[0]["booking_kind"], "staff")
        self.assertEqual(refreshed_rows[0]["status"], "Paid")
