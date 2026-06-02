"""Backend tests for per-room, admin-configurable booking deposits."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class RoomDepositTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="deposit-admin@example.com",
                password="AdminPass1!",
                full_name="Deposit Admin",
                phone="403-000-0039",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "deposit-admin@example.com", "password": "AdminPass1!"},
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

    def _create_room(self, headers, **overrides) -> dict:
        payload = {"name": "Deposit Room", "hourly_rate_cents": 10000, "max_booking_duration_minutes": 300}
        payload.update(overrides)
        resp = self.client.post("/api/rooms", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def test_01_create_room_with_custom_deposit(self) -> None:
        headers = self._admin_headers()
        room = self._create_room(headers, name="Custom Deposit", deposit_cents=3500)
        self.assertEqual(room["deposit_cents"], 3500)

    def test_02_default_deposit_is_2000(self) -> None:
        headers = self._admin_headers()
        room = self._create_room(headers, name="Default Deposit")
        self.assertEqual(room["deposit_cents"], 2000)

    def test_03_public_rooms_expose_deposit(self) -> None:
        headers = self._admin_headers()
        self._create_room(headers, name="Public Room", deposit_cents=2500)
        resp = self.client.get("/api/rooms")
        self.assertEqual(resp.status_code, 200, resp.text)
        rooms = resp.json()
        self.assertTrue(rooms)
        self.assertTrue(all("deposit_cents" in room for room in rooms))

    def test_04_admin_can_update_deposit(self) -> None:
        headers = self._admin_headers()
        room = self._create_room(headers, name="Updatable", deposit_cents=2000)
        resp = self.client.put(
            f"/api/admin/rooms/{room['id']}", json={"deposit_cents": 4000}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["deposit_cents"], 4000)
        # Hourly rate untouched (deposit is separate)
        self.assertEqual(resp.json()["hourly_rate_cents"], 10000)

    def test_05_booking_persists_room_deposit(self) -> None:
        admin_headers = self._admin_headers()
        room = self._create_room(admin_headers, name="Booked Room", deposit_cents=3500)
        booker = self._register_and_login("booker@example.com")
        start = self._future_time(day=1, hour=10).isoformat()

        reservation = self.client.post(
            "/api/bookings/reservations",
            headers=booker,
            json={"room_id": room["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(reservation.status_code, 201, reservation.text)

        resp = self.client.post(
            "/api/bookings",
            headers=booker,
            json={
                "room_id": room["id"],
                "start_time": start,
                "duration_minutes": 60,
                "reservation_token": reservation.json()["token"],
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["deposit_amount_cents"], 3500)
