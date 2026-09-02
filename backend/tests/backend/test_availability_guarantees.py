"""
Backend tests — availability guarantees.

These exist because of a live incident: every day of the booking calendar read
"0 slots" while the API was returning real availability, so nobody could book
anything. The cause was a client that asked for availability one day at a time,
hit the booking rate limit on the thirtieth request, and threw away the
twenty-nine answers that had already arrived.

The guarantee these tests protect is deliberately blunt:

    A visitor must see bookable times on an open day unless those times are
    genuinely taken by a booking that holds the slot.

"Genuinely taken" means a booking in ACTIVE_BOOKING_STATUSES — the ones that
reserve a slot. Anything else (cancelled, expired, refunded) must give the hour
back.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.base import BaseAppTest


class _RoomFactory:
    """Shared room builder for the classes below."""

    def _create_room(self, name: str) -> str:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name=name,
                description="Availability guarantee tests",
                capacity=4,
                photos=[],
                hourly_rate_cents=10000,
                max_booking_duration_minutes=480,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            return str(room.id)


class AvailabilityGuaranteesTest(_RoomFactory, BaseAppTest):
    # ---------------------------------------------------------------- helpers

    def _window(self):
        from app.services.booking_service.core import get_booking_window_hours

        return get_booking_window_hours()

    def _next_open_days(self, count: int = 3):
        """Upcoming business days, skipping today so no hour has passed yet."""
        from app.services.booking_service.core import (
            BOOKING_OPEN_WEEKDAYS,
            get_business_timezone,
        )

        today = datetime.now(get_business_timezone()).date()
        found, offset = [], 1
        while len(found) < count and offset < 60:
            candidate = today + timedelta(days=offset)
            if candidate.weekday() in BOOKING_OPEN_WEEKDAYS:
                found.append(candidate)
            offset += 1
        self.assertEqual(len(found), count, "could not find enough open days")
        return found

    def _occupy_whole_day(self, room_id: str, day, status: str = "Paid") -> None:
        """Fill every bookable hour of *day* with slot-holding bookings."""
        from app.models.booking import Booking, BookingSlot
        from app.services.booking_service.core import get_business_timezone

        open_hour, close_hour = self._window()
        tz = get_business_timezone()

        with self.SessionLocal() as db:
            for hour in range(open_hour, close_hour):
                start = datetime(day.year, day.month, day.day, hour, tzinfo=tz)
                booking = Booking(
                    room_id=uuid.UUID(room_id),
                    start_time=start.astimezone(timezone.utc),
                    end_time=(start + timedelta(hours=1)).astimezone(timezone.utc),
                    duration_minutes=60,
                    price_cents=10000,
                    status=status,
                    booking_code=f"TEST{uuid.uuid4().hex[:8].upper()}",
                )
                db.add(booking)
                db.flush()
                db.add(
                    BookingSlot(
                        booking_id=booking.id,
                        room_id=uuid.UUID(room_id),
                        slot_start=start.astimezone(timezone.utc),
                    )
                )
            db.commit()

    def _month_days(self, room_id: str, day):
        resp = self.client.get(
            f"/api/availability/monthly?month={day.strftime('%Y-%m')}&room_id={room_id}"
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["days"]

    # ------------------------------------------------------------------ tests

    def test_01_an_open_day_offers_every_hour_when_nothing_is_booked(self) -> None:
        """The base case the incident violated. No auth: this is what a visitor
        who has not signed in sees."""
        room_id = self._create_room("Empty Day Room")
        day = self._next_open_days(1)[0]
        open_hour, close_hour = self._window()

        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={day.isoformat()}")
        self.assertEqual(resp.status_code, 200, resp.text)
        starts = resp.json()["available_start_times"]
        self.assertEqual(
            len(starts),
            close_hour - open_hour,
            f"{day} has no bookings, so every hour of the window must be offered",
        )

    def test_02_the_month_never_reads_all_zero_while_a_room_is_free(self) -> None:
        """The exact symptom customers saw: a calendar of nothing but 0 slots."""
        room_id = self._create_room("Free Month Room")
        day = self._next_open_days(1)[0]

        days = self._month_days(room_id, day)
        bookable = {k: v for k, v in days.items() if v.get("open_slots", 0) > 0}
        self.assertTrue(
            bookable,
            "every day reported zero openings while the room was entirely free — "
            "this is the customer-facing failure these tests exist to catch",
        )

    def test_03_a_day_reads_zero_only_when_every_hour_is_taken(self) -> None:
        room_id = self._create_room("Fully Booked Day Room")
        booked_day, free_day = self._next_open_days(2)
        self._occupy_whole_day(room_id, booked_day)

        days = self._month_days(room_id, booked_day)
        self.assertEqual(
            days[booked_day.isoformat()]["open_slots"], 0, "a fully booked day must read zero"
        )
        self.assertGreater(
            days[free_day.isoformat()]["open_slots"],
            0,
            "one fully booked day must not take the rest of the month with it",
        )

    def test_04_a_partly_booked_day_still_offers_the_rest(self) -> None:
        """Losing one hour must not lose the day."""
        from app.models.booking import Booking, BookingSlot
        from app.services.booking_service.core import get_business_timezone

        room_id = self._create_room("Partly Booked Room")
        day = self._next_open_days(1)[0]
        open_hour, close_hour = self._window()
        tz = get_business_timezone()

        start = datetime(day.year, day.month, day.day, open_hour, tzinfo=tz)
        with self.SessionLocal() as db:
            booking = Booking(
                room_id=uuid.UUID(room_id),
                start_time=start.astimezone(timezone.utc),
                end_time=(start + timedelta(hours=1)).astimezone(timezone.utc),
                duration_minutes=60,
                price_cents=10000,
                status="Paid",
                booking_code=f"TEST{uuid.uuid4().hex[:8].upper()}",
            )
            db.add(booking)
            db.flush()
            db.add(
                BookingSlot(
                    booking_id=booking.id,
                    room_id=uuid.UUID(room_id),
                    slot_start=start.astimezone(timezone.utc),
                )
            )
            db.commit()

        days = self._month_days(room_id, day)
        self.assertEqual(days[day.isoformat()]["open_slots"], (close_hour - open_hour) - 1)

    def test_05_a_cancelled_booking_gives_the_hour_back(self) -> None:
        """Only ACTIVE_BOOKING_STATUSES hold a slot. A cancelled booking that
        kept blocking one would quietly shrink availability forever."""
        from app.models.booking import Booking

        room_id = self._create_room("Cancelled Booking Room")
        day = self._next_open_days(1)[0]
        open_hour, close_hour = self._window()

        self._occupy_whole_day(room_id, day)
        days = self._month_days(room_id, day)
        self.assertEqual(days[day.isoformat()]["open_slots"], 0)

        with self.SessionLocal() as db:
            for booking in db.query(Booking).filter(Booking.room_id == uuid.UUID(room_id)).all():
                booking.status = "Cancelled"
            db.commit()

        days = self._month_days(room_id, day)
        self.assertEqual(
            days[day.isoformat()]["open_slots"],
            close_hour - open_hour,
            "cancelling every booking must return every hour",
        )

    def test_06_a_whole_month_of_openings_arrives_in_one_response(self) -> None:
        """The incident's real cause. The client asked day by day, which for a
        thirty-day month is thirty requests — exactly the booking rate limit —
        so the last one was refused and the batch was discarded. One request per
        month means the limit cannot be reached by looking at a calendar."""
        from app.config import settings

        room_id = self._create_room("Single Request Room")
        day = self._next_open_days(1)[0]

        days = self._month_days(room_id, day)
        self.assertGreaterEqual(
            len(days), 28, "the month response must describe every day, not a subset"
        )
        self.assertLess(
            1,
            settings.BOOKING_RATE_LIMIT_MAX_REQUESTS,
            "one call per month must sit far under the booking rate limit",
        )
        for key, value in days.items():
            if value["status"] not in ("closed", "past"):
                self.assertIn("open_slots", value, f"{key} is missing its count")

    def test_07_every_bookable_room_is_visible_to_a_visitor(self) -> None:
        """A room that is active and bookable must appear in the public list —
        otherwise a customer cannot reach its calendar at all."""
        room_id = self._create_room("Publicly Listed Room")
        listed = {r["id"] for r in self.client.get("/api/rooms").json()}
        self.assertIn(room_id, listed)


class AvailabilityCanaryTest(_RoomFactory, BaseAppTest):
    """The tests above run before a deploy. This runs in production.

    Tests cannot catch bad data, a config change, or a room deactivated by
    hand — so /ready carries a warning when bookable rooms exist and yet
    nothing at all can be booked.
    """

    def setUp(self) -> None:
        super().setUp()
        from app import main

        main._availability_canary["checked_at"] = 0.0
        main._availability_canary["warning"] = None

    def test_silent_while_customers_can_book(self) -> None:
        from app import main

        self._create_room("Canary Quiet Room")
        self.assertIsNone(main.availability_warning())

        body = self.client.get("/ready").json()
        self.assertEqual(body["status"], "ready")
        for warning in body.get("warnings", []):
            self.assertNotIn("availability", warning.lower())

    def test_warns_when_rooms_exist_but_nothing_is_bookable(self) -> None:
        """The exact production symptom: a calendar customers cannot book from."""
        from unittest.mock import patch

        from app import main

        self._create_room("Canary Alarm Room")

        def all_closed(db, month, room_id=None):
            return {
                "month": month,
                "total_rooms": 3,
                "days": {f"{month}-{d:02d}": {"status": "full", "open_rooms": 0, "total_rooms": 3}
                         for d in range(1, 29)},
            }

        with patch(
            "app.services.booking_service.core.get_monthly_availability_summary",
            side_effect=all_closed,
        ):
            warning = main.availability_warning()

        self.assertIsNotNone(warning, "an unbookable calendar must raise a warning")
        self.assertIn("cannot book", warning)

    def test_the_canary_never_breaks_ready(self) -> None:
        """A monitoring aid that can take the service down is worse than none."""
        from unittest.mock import patch

        from app import main

        with patch(
            "app.services.booking_service.core.get_monthly_availability_summary",
            side_effect=RuntimeError("database on fire"),
        ):
            warning = main.availability_warning()
            resp = self.client.get("/ready")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ready")
        self.assertIn("could not run", warning)

    def test_a_zero_availability_warning_does_not_flip_the_verdict(self) -> None:
        """An empty calendar is serious, but the service is still up. Marking it
        degraded would restart a healthy container without fixing anything."""
        from unittest.mock import patch

        from app import main

        with patch.object(main, "availability_warning", return_value="nothing is bookable"):
            body = self.client.get("/ready").json()

        self.assertEqual(body["status"], "ready")
        self.assertIn("nothing is bookable", body["warnings"])
