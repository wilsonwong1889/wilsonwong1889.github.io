"""Backend tests for the '5th hour free' room-booking incentive."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class FifthHourFreeUnitTest(BaseAppTest):
    def test_billable_and_free_minutes(self) -> None:
        from app.services.booking_service import billable_room_minutes, free_room_minutes

        # Under 5 hours: nothing free.
        self.assertEqual(free_room_minutes(60), 0)
        self.assertEqual(billable_room_minutes(240), 240)
        # Exactly 5 hours: the 5th hour is free -> billed as 4 hours.
        self.assertEqual(free_room_minutes(300), 60)
        self.assertEqual(billable_room_minutes(300), 240)

    def test_incentive_applies_to_room_time_only(self) -> None:
        from app.services.booking_service import calculate_booking_total_cents, calculate_price_cents
        from app.staffing import staff_add_on_total_cents

        # Room-only: a 5h booking at $100/hr is billed as 4 room hours.
        self.assertEqual(calculate_booking_total_cents(10000, 300, []), 40000)

        # With a staff add-on, the room is still discounted to 4h and the staff
        # add-on is charged in full (independent of the free hour).
        assignments = [{"id": "eng-1", "name": "Engineer", "add_on_price_cents": 5000}]
        self.assertEqual(staff_add_on_total_cents(assignments), 5000)
        total = calculate_booking_total_cents(10000, 300, assignments)
        self.assertEqual(total, calculate_price_cents(10000, 240) + 5000)
        self.assertEqual(total, 45000)


class FifthHourFreeBookingTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="fifth-admin@example.com",
                password="AdminPass1!",
                full_name="Fifth Admin",
                phone="403-000-0049",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "fifth-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _register_and_login(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Booker", "phone": "403-555-0100"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _book(self, room_id, headers, duration_minutes):
        start = self._future_time(day=1, hour=10).isoformat()
        reservation = self.client.post(
            "/api/bookings/reservations",
            headers=headers,
            json={"room_id": room_id, "start_time": start, "duration_minutes": duration_minutes},
        )
        self.assertEqual(reservation.status_code, 201, reservation.text)
        return self.client.post(
            "/api/bookings",
            headers=headers,
            json={
                "room_id": room_id,
                "start_time": start,
                "duration_minutes": duration_minutes,
                "reservation_token": reservation.json()["token"],
            },
        )

    def test_five_hour_booking_charges_four_room_hours(self) -> None:
        admin = self._admin_headers()
        room = self.client.post(
            "/api/rooms",
            json={"name": "Five Hour Room", "hourly_rate_cents": 10000, "max_booking_duration_minutes": 300},
            headers=admin,
        ).json()
        booker = self._register_and_login("fifth-booker@example.com")

        resp = self._book(room["id"], booker, 300)
        self.assertEqual(resp.status_code, 201, resp.text)
        booking = resp.json()
        # 4 room hours @ $100 = $400 original, +5% GST = $420 total.
        self.assertEqual(booking["original_price_cents"], 40000)
        self.assertEqual(booking["price_cents"], 42000)
