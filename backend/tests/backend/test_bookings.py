"""
Backend tests — room booking flows.

Covers: availability API, booking creation/conflict/cancellation, guest
booking endpoint, contact update on guest booking.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from tests.base import BaseAppTest


class BookingTest(BaseAppTest):

    def _create_bookable_room(self, name: str) -> str:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name=name,
                description="Room used for calendar tests",
                capacity=3,
                photos=[],
                hourly_rate_cents=10000,
                max_booking_duration_minutes=120,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            return str(room.id)

    def test_20_booking_flow(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Booking Room",
                description="Room used for booking smoke tests",
                capacity=3,
                photos=[],
                hourly_rate_cents=10000,
                max_booking_duration_minutes=120,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "booker@example.com",
                "password": "Password123!",
                "full_name": "Booking User",
                "phone": "5551112222",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "booker@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        booking_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=2, hour=10, minute=0)
        target_date = self._future_date(2)

        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        availability = resp.json()
        self.assertEqual(availability["timezone"], "America/Edmonton")
        self.assertIn(start_time.isoformat(), availability["available_start_times"])
        self.assertEqual(availability["max_duration_minutes_by_start"][start_time.isoformat()], 120)
        self.assertNotIn(
            self._future_time(day=2, hour=9, minute=0).isoformat(),
            availability["available_start_times"],
        )
        self.assertNotIn(
            self._future_time(day=2, hour=18, minute=0).isoformat(),
            availability["available_start_times"],
        )

        past_date = datetime.now(business_timezone).date() - timedelta(days=1)
        past_start = datetime(
            past_date.year, past_date.month, past_date.day, 10, 0, tzinfo=business_timezone
        )
        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={past_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["available_start_times"], [])

        resp = self.client.post(
            "/api/bookings/reservations",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": past_start.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Bookings cannot be created for past dates or times")

        resp = self.client.post(
            "/api/bookings/guest",
            json={
                "room_id": room_id,
                "start_time": past_start.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Past Guest",
                "guest_phone": "4035550101",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Bookings cannot be created for past dates or times")

        resp = self.client.post(
            "/api/bookings/reservations",
            headers=booking_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        reservation = resp.json()
        self.assertTrue(reservation["token"].startswith("hold_"))
        self.assertEqual(len(reservation["slot_keys"]), 2)

        resp = self.client.post(
            "/api/bookings",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "reservation_token": reservation["token"],
                "note": "Podcast intro and guest setup",
            },
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], self._room_price(10000, 60))
        self.assertTrue(booking["payment_intent_id"].startswith("pi_"))
        self.assertTrue(booking["booking_code"])
        self.assertEqual(booking["note"], "Podcast intro and guest setup")
        self.assertIsNotNone(booking["payment_expires_at"])
        self.assertGreater(booking["payment_seconds_remaining"], 0)
        self.assertLessEqual(booking["payment_seconds_remaining"], 300)

        resp = self.client.get("/api/bookings", headers=booking_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

        resp = self.client.get(f"/api/bookings/{booking['id']}", headers=booking_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], booking["id"])

        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(start_time.isoformat(), resp.json()["available_start_times"])

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "conflict@example.com",
                "password": "Password123!",
                "full_name": "Conflict User",
                "phone": "5550001111",
            },
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "conflict@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        conflict_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 409)

        resp = self.client.post(
            "/api/bookings",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=5, hour=13, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=2, hour=10, minute=30).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 422)

        resp = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=2, hour=11, minute=0).isoformat(),
                "duration_minutes": 120,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["duration_minutes"], 120)
        self.assertEqual(resp.json()["price_cents"], self._room_price(10000, 120))

        resp = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=3, hour=11, minute=0).isoformat(),
                "duration_minutes": 360,
            },
        )
        self.assertEqual(resp.status_code, 422)

        resp = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=3, hour=9, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "Bookings are only available between 12:00 and 20:00")

    def test_21_guest_booking_endpoint(self) -> None:
        from app.models.booking import Booking
        from app.models.room import Room
        from app.models.user import User

        with self.SessionLocal() as db:
            room = Room(
                name="Guest Booking Room",
                description="Room used for guest booking smoke tests",
                capacity=2,
                photos=[],
                hourly_rate_cents=10000,
                max_booking_duration_minutes=180,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        start_time = self._future_time(day=4, hour=11, minute=0)

        resp = self.client.post(
            "/api/bookings/guest",
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Guest Booker",
                "guest_phone": "4035550102",
            },
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertTrue(payload["access_token"])
        self.assertEqual(payload["booking"]["status"], "PendingPayment")
        self.assertEqual(payload["booking"]["price_cents"], self._room_price(10000, 60))

        guest_headers = {"Authorization": f"Bearer {payload['access_token']}"}
        resp = self.client.get(f"/api/bookings/{payload['booking']['id']}", headers=guest_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], payload["booking"]["id"])
        self.assertEqual(resp.json()["user_full_name"], "Guest Booker")
        self.assertEqual(resp.json()["user_phone"], "4035550102")
        self.assertIsNone(resp.json()["user_email"])

        resp = self.client.put(
            f"/api/bookings/{payload['booking']['id']}/contact",
            headers=guest_headers,
            json={
                "full_name": "Checkout Guest",
                "email": "checkout-guest@example.com",
                "phone": "4035550199",
                "note": "Use the east entrance.",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_full_name"], "Checkout Guest")
        self.assertEqual(resp.json()["user_email"], "checkout-guest@example.com")
        self.assertEqual(resp.json()["user_phone"], "4035550199")
        self.assertEqual(resp.json()["note"], "Use the east entrance.")

        with self.SessionLocal() as db:
            booking = db.query(Booking).filter(Booking.id == UUID(payload["booking"]["id"])).one()
            user = db.query(User).filter(User.id == booking.user_id).one()

        self.assertEqual(user.full_name, "Guest Booker")
        self.assertEqual(user.phone, "4035550102")
        self.assertTrue(user.email.startswith("guest+"))
        self.assertEqual(booking.user_full_name_snapshot, "Checkout Guest")
        self.assertEqual(booking.user_email_snapshot, "checkout-guest@example.com")
        self.assertEqual(booking.user_phone_snapshot, "4035550199")
        self.assertEqual(booking.note, "Use the east entrance.")

    def test_50_monthly_availability_supports_a_single_room(self) -> None:
        """The booking calendar needs a per-day slot count. Asking one day at a
        time meant thirty requests for a thirty-day month — exactly the booking
        rate limit — so the last one 429'd, the whole batch was discarded, and
        every day rendered "0 slots" while the API had real availability."""
        room_id = self._create_bookable_room("Monthly Calendar Room")

        resp = self.client.get(f"/api/availability/monthly?month=2026-09&room_id={room_id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total_rooms"], 1)

        open_days = [d for d in body["days"].values() if d["status"] not in ("closed", "past")]
        self.assertTrue(open_days, "expected at least one open day")
        for day in open_days:
            self.assertIn("open_slots", day)
            self.assertGreaterEqual(day["open_slots"], 0)

    def test_51_site_wide_monthly_carries_no_per_room_slot_count(self) -> None:
        """Regression guard. The grouping loop used `room_id` as its loop
        variable, shadowing the parameter, so after it ran the parameter held
        the last booked slot's room and every site-wide response leaked a
        per-room count."""
        resp = self.client.get("/api/availability/monthly?month=2026-09")
        self.assertEqual(resp.status_code, 200, resp.text)
        for day_key, day in resp.json()["days"].items():
            self.assertNotIn("open_slots", day, f"{day_key} leaked a per-room count")

    def test_52_month_summary_matches_the_single_day_endpoint(self) -> None:
        """The two must agree, including today — where the hours already gone
        are not bookable and must not be counted."""
        room_id = self._create_bookable_room("Month vs Day Room")
        month = self.client.get(
            f"/api/availability/monthly?month=2026-09&room_id={room_id}"
        ).json()["days"]

        checked = 0
        for day_key, day in month.items():
            if day["status"] in ("closed", "past"):
                continue
            single = self.client.get(f"/api/rooms/{room_id}/availability?date={day_key}")
            if single.status_code != 200:
                continue
            self.assertEqual(
                day["open_slots"],
                len(single.json()["available_start_times"]),
                f"month and day disagree on {day_key}",
            )
            checked += 1
            if checked >= 4:
                break
        self.assertGreater(checked, 0, "no days were comparable")
