"""Reservation holds vs availability: a slot another customer is holding must
not show as open to everyone else, but stays visible to the holder."""
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class ReservationHoldTest(BaseAppTest):
    def setUp(self) -> None:
        super().setUp()
        # Force the deterministic in-memory hold store (base clears it each test).
        from app.services import reservation_service

        self._orig_redis = reservation_service.redis
        reservation_service.redis = None

    def tearDown(self) -> None:
        from app.services import reservation_service

        reservation_service.redis = self._orig_redis

    def _room(self, db):
        room = self.Room(
            name=f"Hold Room {uuid4().hex[:6]}",
            description="Reservation hold test room",
            capacity=4,
            photos=[],
            hourly_rate_cents=10000,
            max_booking_duration_minutes=300,
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    def test_01_held_slot_hidden_from_others_but_visible_to_owner(self) -> None:
        from app.services.booking_service import create_reservation_hold, get_room_availability

        start = self._future_time(day=1, hour=10)  # noon local on a business day
        held_iso = start.isoformat()
        with self.SessionLocal() as db:
            room = self._room(db)

            # Slot is open before anyone holds it.
            before = get_room_availability(db, room.id, start.date())
            self.assertIn(held_iso, before["available_start_times"])

            hold = create_reservation_hold(db, str(room.id), start, 60)

            # Another customer no longer sees the held slot as open.
            others = get_room_availability(db, room.id, start.date())
            self.assertNotIn(held_iso, others["available_start_times"])

            # The holder still sees their own slot (own token excluded).
            owner = get_room_availability(db, room.id, start.date(), exclude_hold_token=hold.token)
            self.assertIn(held_iso, owner["available_start_times"])

    def test_02_extend_hold_renews_only_for_owner(self) -> None:
        from app.services.booking_service import create_reservation_hold
        from app.services.reservation_service import active_held_slot_keys, extend_hold

        start = self._future_time(day=2, hour=10)
        with self.SessionLocal() as db:
            room = self._room(db)
            hold = create_reservation_hold(db, str(room.id), start, 60)

        # Wrong token can't extend; the real token can.
        self.assertFalse(extend_hold(hold.slot_keys, "hold_not_mine"))
        self.assertTrue(extend_hold(hold.slot_keys, hold.token))

        # The slots read as held to others, but not to the owner.
        self.assertEqual(active_held_slot_keys(hold.slot_keys), set(hold.slot_keys))
        self.assertEqual(active_held_slot_keys(hold.slot_keys, ignore_token=hold.token), set())

    def test_03_extend_endpoint_round_trip(self) -> None:
        from app.services.booking_service import create_reservation_hold

        # A logged-in user is required for the reservation endpoints.
        self.client.post(
            "/api/auth/signup",
            json={"email": "holder@example.com", "password": "TestPass1!", "full_name": "Holder", "phone": "403-555-0102"},
        )
        token = self.client.post(
            "/api/auth/login", data={"username": "holder@example.com", "password": "TestPass1!"}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        start = self._future_time(day=3, hour=10)
        with self.SessionLocal() as db:
            room = self._room(db)
            room_id = str(room.id)
            hold = create_reservation_hold(db, room_id, start, 60)

        ok = self.client.post(
            "/api/bookings/reservations/extend",
            headers=headers,
            json={"token": hold.token, "slot_keys": hold.slot_keys},
        )
        self.assertEqual(ok.status_code, 200, ok.text)

        expired = self.client.post(
            "/api/bookings/reservations/extend",
            headers=headers,
            json={"token": "hold_stale", "slot_keys": hold.slot_keys},
        )
        self.assertEqual(expired.status_code, 409, expired.text)
