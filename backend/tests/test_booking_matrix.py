import os
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


BUSINESS_TIMEZONE = ZoneInfo("America/Edmonton")


class BookingSchemaMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.schemas.booking import (
            BookingCreate,
            ReservationCreate,
            validate_booking_duration_minutes,
        )
        from app.schemas.room import RoomCreate, validate_room_max_duration
        from app.staffing import normalize_staff_selection_ids, resolve_staff_assignments

        cls.BookingCreate = BookingCreate
        cls.ReservationCreate = ReservationCreate
        cls.RoomCreate = RoomCreate
        cls.validate_booking_duration_minutes = staticmethod(validate_booking_duration_minutes)
        cls.validate_room_max_duration = staticmethod(validate_room_max_duration)
        cls.normalize_staff_selection_ids = staticmethod(normalize_staff_selection_ids)
        cls.resolve_staff_assignments = staticmethod(resolve_staff_assignments)

    def _aware_time(self, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
        target_date = datetime.now(BUSINESS_TIMEZONE).date() + timedelta(days=30)
        shifted_hour = hour + 2
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            shifted_hour,
            minute,
            second,
            tzinfo=BUSINESS_TIMEZONE,
        )


class ReservationHoldMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.services import reservation_service

        reservation_service.redis = None
        cls.reservation_service = reservation_service

    def setUp(self) -> None:
        self.reservation_service._memory_holds.clear()

    def _slot_keys(self, *suffixes: str) -> list[str]:
        return [f"room:test:{suffix}" for suffix in suffixes]


class BookingServiceMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_database_url = os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres",
        )
        cls.test_database_name = f"studio_booking_matrix_{uuid4().hex[:8]}"
        cls.test_database_url = os.environ.get(
            "TEST_DATABASE_URL",
            f"postgresql://postgres:password@localhost:5432/{cls.test_database_name}",
        )
        cls._create_database()

        os.environ["DATABASE_URL"] = cls.test_database_url
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "booking-matrix-secret")
        os.environ["PAYMENT_BACKEND"] = "stub"

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                sys.modules.pop(module_name)

        from app.core.security import hash_password
        from app.database import Base, SessionLocal, engine
        from app.main import app
        from app.models.booking import (
            AuditLog,
            Booking,
            BookingSlot,
            BookingStaffAssignment,
            NotificationLog,
            Refund,
            Review,
            WebhookEventLog,
        )
        from app.models.promo_code import PromoCode
        from app.models.room import Room
        from app.models.staff_availability import StaffAvailabilityException
        from app.models.staff_booking import StaffBooking
        from app.models.staff_profile import StaffProfile
        from app.models.user import User
        from app.schemas.booking import BookingCreate, GuestBookingCreate, ManualBookingCreate, RefundCreate
        from app.schemas.staff_booking import StaffBookingRescheduleIn
        from app.services import booking_service
        from app.services.staff_booking_service import StaffBookingConflictError, reschedule_staff_booking
        from app.services.booking_service import (
            BookingConflictError,
            DailyBookingLimitError,
            PaymentSessionError,
            StaffAvailabilityError,
            StaffSelectionError,
            build_slot_starts,
            calculate_booking_total_cents,
            calculate_price_cents,
            cancel_booking,
            clear_bookings_for_admin_day,
            clear_past_bookings_for_admin,
            create_booking,
            create_or_update_booking_review,
            create_guest_booking,
            create_manual_booking,
            create_reservation_hold,
            expire_pending_booking,
            expire_stale_pending_bookings,
            get_booking_for_user,
            get_booking_payment_session,
            get_day_bounds,
            get_pending_booking_expiry_minutes,
            get_pending_booking_expiry_reason,
            get_room_availability,
            get_room_max_booking_duration_minutes,
            handle_payment_webhook_event,
            list_bookings_for_user,
            list_room_reviews,
            mark_booking_paid,
            reschedule_booking,
            normalize_booking_start,
            process_refund,
            serialize_admin_booking,
            mark_booking_paid_manually,
            waive_booking_payment,
            validate_booking_window,
        )
        from app.services.payment_service import PaymentConfigurationError
        from app.services import reservation_service

        reservation_service.redis = None

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.app = app
        cls.hash_password = staticmethod(hash_password)
        cls.AuditLog = AuditLog
        cls.Booking = Booking
        cls.BookingSlot = BookingSlot
        cls.BookingStaffAssignment = BookingStaffAssignment
        cls.NotificationLog = NotificationLog
        cls.Refund = Refund
        cls.Review = Review
        cls.WebhookEventLog = WebhookEventLog
        cls.PromoCode = PromoCode
        cls.Room = Room
        cls.StaffAvailabilityException = StaffAvailabilityException
        cls.StaffBooking = StaffBooking
        cls.StaffProfile = StaffProfile
        cls.User = User
        cls.BookingCreate = BookingCreate
        cls.GuestBookingCreate = GuestBookingCreate
        cls.ManualBookingCreate = ManualBookingCreate
        cls.RefundCreate = RefundCreate
        cls.StaffBookingRescheduleIn = StaffBookingRescheduleIn
        cls.BookingConflictError = BookingConflictError
        cls.DailyBookingLimitError = DailyBookingLimitError
        cls.PaymentSessionError = PaymentSessionError
        cls.StaffAvailabilityError = StaffAvailabilityError
        cls.StaffSelectionError = StaffSelectionError
        cls.StaffBookingConflictError = StaffBookingConflictError
        cls.build_slot_starts = staticmethod(build_slot_starts)
        cls.calculate_booking_total_cents = staticmethod(calculate_booking_total_cents)
        cls.calculate_price_cents = staticmethod(calculate_price_cents)
        cls.cancel_booking = staticmethod(cancel_booking)
        cls.create_guest_booking = staticmethod(create_guest_booking)
        cls.clear_bookings_for_admin_day = staticmethod(clear_bookings_for_admin_day)
        cls.clear_past_bookings_for_admin = staticmethod(clear_past_bookings_for_admin)
        cls.create_booking = staticmethod(create_booking)
        cls.create_or_update_booking_review = staticmethod(create_or_update_booking_review)
        cls.create_manual_booking = staticmethod(create_manual_booking)
        cls.create_reservation_hold = staticmethod(create_reservation_hold)
        cls.expire_pending_booking = staticmethod(expire_pending_booking)
        cls.expire_stale_pending_bookings = staticmethod(expire_stale_pending_bookings)
        cls.get_booking_for_user = staticmethod(get_booking_for_user)
        cls.get_booking_payment_session = staticmethod(get_booking_payment_session)
        cls.get_day_bounds = staticmethod(get_day_bounds)
        cls.get_pending_booking_expiry_minutes = staticmethod(get_pending_booking_expiry_minutes)
        cls.get_pending_booking_expiry_reason = staticmethod(get_pending_booking_expiry_reason)
        cls.get_room_availability = staticmethod(get_room_availability)
        cls.get_room_max_booking_duration_minutes = staticmethod(get_room_max_booking_duration_minutes)
        cls.handle_payment_webhook_event = staticmethod(handle_payment_webhook_event)
        cls.list_bookings_for_user = staticmethod(list_bookings_for_user)
        cls.list_room_reviews = staticmethod(list_room_reviews)
        cls.mark_booking_paid = staticmethod(mark_booking_paid)
        cls.reschedule_booking = staticmethod(reschedule_booking)
        cls.reschedule_staff_booking = staticmethod(reschedule_staff_booking)
        cls.normalize_booking_start = staticmethod(normalize_booking_start)
        cls.process_refund = staticmethod(process_refund)
        cls.serialize_admin_booking = staticmethod(serialize_admin_booking)
        cls.mark_booking_paid_manually = staticmethod(mark_booking_paid_manually)
        cls.waive_booking_payment = staticmethod(waive_booking_payment)
        cls.validate_booking_window = staticmethod(validate_booking_window)
        cls.PaymentConfigurationError = PaymentConfigurationError
        cls.memory_holds = reservation_service._memory_holds

        with cls.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        cls.Base.metadata.create_all(bind=cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls._drop_database()

    @classmethod
    def _create_database(cls) -> None:
        admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {cls.test_database_name}"))
            conn.execute(text(f"CREATE DATABASE {cls.test_database_name}"))
        admin_engine.dispose()

    @classmethod
    def _drop_database(cls) -> None:
        admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": cls.test_database_name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {cls.test_database_name}"))
        admin_engine.dispose()

    def setUp(self) -> None:
        self.memory_holds.clear()
        with self.SessionLocal() as db:
            for model in (
                self.AuditLog,
                self.NotificationLog,
                self.WebhookEventLog,
                self.Refund,
                self.Review,
                self.PromoCode,
                self.StaffAvailabilityException,
                self.BookingStaffAssignment,
                self.BookingSlot,
                self.Booking,
                self.StaffBooking,
                self.Room,
                self.StaffProfile,
                self.User,
            ):
                db.query(model).delete()
            db.commit()

    def _aware_date(self, day: int = 1) -> date:
        base = datetime.now(BUSINESS_TIMEZONE).date() + timedelta(days=30)
        days_until_wed = (2 - base.weekday()) % 7
        wednesday = base + timedelta(days=days_until_wed)
        week_offset = (day - 1) // 4
        day_in_week = (day - 1) % 4
        return wednesday + timedelta(weeks=week_offset, days=day_in_week)

    def _aware_time(self, day: int = 1, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
        target_date = self._aware_date(day)
        shifted_hour = hour + 2
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            shifted_hour,
            minute,
            second,
            tzinfo=BUSINESS_TIMEZONE,
        )

    def _create_user(
        self,
        db,
        *,
        email_prefix: str = "user",
        is_admin: bool = False,
        full_name: str = "Test User",
        phone: str = "5551111111",
    ):
        user = self.User(
            email=f"{email_prefix}-{uuid4().hex[:8]}@example.com",
            password_hash=self.hash_password("Password123!"),
            full_name=full_name,
            phone=phone,
            opt_in_email=True,
            opt_in_sms=True,
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def _create_room(
        self,
        db,
        *,
        name: str = "Matrix Room",
        max_booking_duration_minutes: int = 300,
        hourly_rate_cents: int = 10000,
        staff_roles=None,
        active: bool = True,
    ):
        room = self.Room(
            name=f"{name} {uuid4().hex[:6]}",
            description="Regression test room",
            capacity=4,
            photos=[],
            staff_roles=staff_roles or [],
            hourly_rate_cents=hourly_rate_cents,
            max_booking_duration_minutes=max_booking_duration_minutes,
            active=active,
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    def _create_pending_booking(
        self,
        db,
        *,
        user,
        room,
        start_time: datetime,
        duration_minutes: int = 60,
        staff_assignments=None,
        promo_code: str = None,
        note: str = None,
    ):
        payload = self.BookingCreate(
            room_id=room.id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            staff_assignments=staff_assignments or [],
            promo_code=promo_code,
            note=note,
        )
        return self.create_booking(db, user, payload)

    def _create_promo_code(
        self,
        db,
        *,
        code: str = "FOUNDATION10",
        percent_off: int = 10,
        amount_off_cents=None,
        active: bool = True,
        max_redemptions=None,
    ):
        promo_code = self.PromoCode(
            code=code,
            percent_off=percent_off,
            amount_off_cents=amount_off_cents,
            active=active,
            max_redemptions=max_redemptions,
        )
        db.add(promo_code)
        db.commit()
        db.refresh(promo_code)
        return promo_code

    def _insert_booking_direct(
        self,
        db,
        *,
        user,
        room,
        start_time: datetime,
        duration_minutes: int = 60,
        status: str = "Paid",
        payment_intent_id: str = None,
        confirmed_at: datetime = None,
        checked_in_at: datetime = None,
        cancelled_at: datetime = None,
        cancellation_reason: str = None,
        created_at: datetime = None,
        note: str = None,
        staff_assignments=None,
        create_slots: bool = True,
        user_email_snapshot: str = None,
        user_full_name_snapshot: str = None,
        user_phone_snapshot: str = None,
    ):
        normalized_start = self.normalize_booking_start(start_time)
        booking = self.Booking(
            user_id=user.id if user else None,
            room_id=room.id,
            start_time=normalized_start,
            end_time=normalized_start + timedelta(minutes=duration_minutes),
            duration_minutes=duration_minutes,
            price_cents=5000,
            currency="CAD",
            status=status,
            booking_code=f"BOOK{uuid4().hex[:8].upper()}",
            user_email_snapshot=user_email_snapshot or (user.email if user else None),
            user_full_name_snapshot=user_full_name_snapshot or (user.full_name if user else None),
            user_phone_snapshot=user_phone_snapshot or (user.phone if user else None),
            payment_intent_id=payment_intent_id or f"pi_stub_{uuid4().hex[:18]}",
            confirmed_at=confirmed_at,
            checked_in_at=checked_in_at,
            cancelled_at=cancelled_at,
            cancellation_reason=cancellation_reason,
            created_at=created_at,
            note=note,
            staff_assignments=staff_assignments or [],
        )
        db.add(booking)
        db.flush()
        if create_slots:
            db.add_all(
                [
                    self.BookingSlot(
                        booking_id=booking.id,
                        room_id=room.id,
                        slot_start=slot_start,
                    )
                    for slot_start in self.build_slot_starts(normalized_start, duration_minutes)
                ]
            )
        db.commit()
        db.refresh(booking)
        return booking

    def test_116_create_booking_persists_pending_and_payment_intent(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)

            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=1, hour=10),
            )

            self.assertEqual(booking.status, "PendingPayment")
            self.assertTrue(booking.payment_intent_id.startswith("pi_stub_"))
            self.assertIsNotNone(booking.payment_expires_at)
            self.assertGreaterEqual(
                db.query(self.BookingSlot).filter(self.BookingSlot.booking_id == booking.id).count(),
                2,
            )

    def test_117_create_booking_includes_staff_price_and_snapshot(self) -> None:
        staff_roles = [
            {
                "id": "sound-engineer",
                "name": "Sound Engineer",
                "description": "Tracks the session.",
                "add_on_price_cents": 3500,
                "photo_url": "/assets/media/staff/sound.jpg",
                "skills": ["Mixing"],
                "talents": ["Recording"],
            }
        ]
        with self.SessionLocal() as db:
            user = self._create_user(db, full_name="Sound Client", phone="5552223333")
            room = self._create_room(db, staff_roles=staff_roles)

            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=1, hour=11),
                staff_assignments=["sound-engineer"],
            )

            # Room time (10000) + one staff at flat $25/hr ($25 for 1h) = 12500, +5% tax.
            self.assertEqual(booking.price_cents, 13125)
            self.assertEqual(booking.staff_assignments[0]["name"], "Sound Engineer")
            self.assertEqual(booking.staff_assignments[0]["photo_url"], "/assets/media/staff/sound.jpg")
            self.assertEqual(booking.user_full_name_snapshot, "Sound Client")
            self.assertEqual(booking.user_phone_snapshot, "5552223333")
            guard = (
                db.query(self.BookingStaffAssignment)
                .filter(self.BookingStaffAssignment.booking_id == booking.id)
                .one()
            )
            self.assertEqual(guard.staff_key, "sound-engineer")
            self.assertEqual(guard.staff_name, "Sound Engineer")

    def test_118_create_booking_rejects_invalid_staff_selection(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db, staff_roles=[{"id": "filmer", "name": "Filmer"}])

            with self.assertRaises(self.StaffSelectionError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room,
                    start_time=self._aware_time(day=1, hour=12),
                    staff_assignments=["photographer"],
                )

    def test_119_create_booking_blocks_overlapping_staff(self) -> None:
        staff_roles = [{"id": "filmer", "name": "Filmer", "add_on_price_cents": 2000}]
        with self.SessionLocal() as db:
            user_one = self._create_user(db, email_prefix="filmer-one")
            user_two = self._create_user(db, email_prefix="filmer-two")
            room_one = self._create_room(db, name="Room One", staff_roles=staff_roles)
            room_two = self._create_room(db, name="Room Two", staff_roles=staff_roles)
            self._create_pending_booking(
                db,
                user=user_one,
                room=room_one,
                start_time=self._aware_time(day=1, hour=13),
                staff_assignments=["filmer"],
            )

            with self.assertRaises(self.StaffAvailabilityError):
                self._create_pending_booking(
                    db,
                    user=user_two,
                    room=room_two,
                    start_time=self._aware_time(day=1, hour=13),
                    staff_assignments=["filmer"],
                )

    def test_120_cancelled_booking_frees_staff_availability(self) -> None:
        staff_roles = [{"id": "photographer", "name": "Photographer", "add_on_price_cents": 2500}]
        with self.SessionLocal() as db:
            user = self._create_user(db)
            other_user = self._create_user(db, email_prefix="other")
            room_one = self._create_room(db, name="Photo Room", staff_roles=staff_roles)
            room_two = self._create_room(db, name="Alt Room", staff_roles=staff_roles)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room_one,
                start_time=self._aware_time(day=1, hour=14),
                staff_assignments=["photographer"],
            )

            cancelled = self.cancel_booking(db, booking, user, "Need a different time")
            self.assertEqual(cancelled.status, "Cancelled")

            replacement = self._create_pending_booking(
                db,
                user=other_user,
                room=room_two,
                start_time=self._aware_time(day=1, hour=14),
                staff_assignments=["photographer"],
            )
            self.assertEqual(replacement.status, "PendingPayment")

    def test_120b_staff_assignment_db_guard_blocks_overlap_without_app_check(self) -> None:
        staff_roles = [{"id": "producer", "name": "Producer", "add_on_price_cents": 2000}]
        with self.SessionLocal() as db:
            user_one = self._create_user(db, email_prefix="producer-one")
            user_two = self._create_user(db, email_prefix="producer-two")
            room_one = self._create_room(db, name="Producer Room One", staff_roles=staff_roles)
            room_two = self._create_room(db, name="Producer Room Two", staff_roles=staff_roles)
            start_time = self._aware_time(day=1, hour=15)
            first = self._create_pending_booking(
                db,
                user=user_one,
                room=room_one,
                start_time=start_time,
                staff_assignments=["producer"],
            )

            second = self.Booking(
                user_id=user_two.id,
                room_id=room_two.id,
                start_time=first.start_time,
                end_time=first.end_time,
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="PendingPayment",
                booking_code=f"BOOK{uuid4().hex[:8].upper()}",
                user_email_snapshot=user_two.email,
                user_full_name_snapshot=user_two.full_name,
                user_phone_snapshot=user_two.phone,
                payment_intent_id=f"pi_stub_{uuid4().hex[:18]}",
                staff_assignments=[],
            )
            db.add(second)
            db.flush()
            db.add(
                self.BookingStaffAssignment(
                    booking_id=second.id,
                    room_id=room_two.id,
                    staff_key="producer",
                    staff_name="Producer",
                    start_time=second.start_time,
                    end_time=second.end_time,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_120c_payment_intent_ids_are_unique_across_booking_tables(self) -> None:
        with self.SessionLocal() as db:
            user_one = self._create_user(db, email_prefix="payment-one")
            user_two = self._create_user(db, email_prefix="payment-two")
            room_one = self._create_room(db, name="Payment Room One")
            room_two = self._create_room(db, name="Payment Room Two")
            payment_intent_id = f"pi_stub_unique_{uuid4().hex[:12]}"

            first_booking = self._insert_booking_direct(
                db,
                user=user_one,
                room=room_one,
                start_time=self._aware_time(day=1, hour=12),
                payment_intent_id=payment_intent_id,
                create_slots=False,
            )
            db.commit()
            duplicate_booking = self.Booking(
                user_id=user_two.id,
                room_id=room_two.id,
                start_time=self.normalize_booking_start(self._aware_time(day=1, hour=15)),
                end_time=self.normalize_booking_start(self._aware_time(day=1, hour=16)),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code=f"BOOK{uuid4().hex[:8].upper()}",
                user_email_snapshot=user_two.email,
                user_full_name_snapshot=user_two.full_name,
                user_phone_snapshot=user_two.phone,
                payment_intent_id=first_booking.payment_intent_id,
                confirmed_at=datetime.now(timezone.utc),
            )
            db.add(duplicate_booking)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            profile = self.StaffProfile(
                name="Unique Payment Staff",
                booking_rate_cents=5000,
                booking_enabled=True,
                schedule_published=True,
                active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            staff_payment_intent_id = f"pi_stub_staff_unique_{uuid4().hex[:12]}"
            first_staff_start = self.normalize_booking_start(self._aware_time(day=2, hour=10))
            second_staff_start = self.normalize_booking_start(self._aware_time(day=2, hour=15))
            db.add(
                self.StaffBooking(
                    user_id=user_one.id,
                    staff_profile_id=profile.id,
                    start_time=first_staff_start,
                    end_time=first_staff_start + timedelta(minutes=60),
                    duration_minutes=60,
                    price_cents=5000,
                    currency="CAD",
                    status="Paid",
                    booking_code=f"STAFF{uuid4().hex[:8].upper()}",
                    user_email_snapshot=user_one.email,
                    user_full_name_snapshot=user_one.full_name,
                    user_phone_snapshot=user_one.phone,
                    payment_intent_id=staff_payment_intent_id,
                    confirmed_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
            db.add(
                self.StaffBooking(
                    user_id=user_two.id,
                    staff_profile_id=profile.id,
                    start_time=second_staff_start,
                    end_time=second_staff_start + timedelta(minutes=60),
                    duration_minutes=60,
                    price_cents=5000,
                    currency="CAD",
                    status="Paid",
                    booking_code=f"STAFF{uuid4().hex[:8].upper()}",
                    user_email_snapshot=user_two.email,
                    user_full_name_snapshot=user_two.full_name,
                    user_phone_snapshot=user_two.phone,
                    payment_intent_id=staff_payment_intent_id,
                    confirmed_at=datetime.now(timezone.utc),
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_120a_db_exclusion_constraint_blocks_overlapping_bookings_without_slots(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)

            self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=5, hour=10),
                duration_minutes=120,
                create_slots=False,
            )

            overlapping_booking = self.Booking(
                user_id=user.id,
                room_id=room.id,
                start_time=self.normalize_booking_start(self._aware_time(day=5, hour=11)),
                end_time=self.normalize_booking_start(self._aware_time(day=5, hour=13)),
                duration_minutes=120,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code=f"BOOK{uuid4().hex[:8].upper()}",
                user_email_snapshot=user.email,
                user_full_name_snapshot=user.full_name,
                user_phone_snapshot=user.phone,
                payment_intent_id=f"pi_stub_{uuid4().hex[:18]}",
                confirmed_at=datetime.now(timezone.utc),
                staff_assignments=[],
            )
            db.add(overlapping_booking)

            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_121_customer_daily_limit_blocks_second_same_day(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room_one = self._create_room(db, name="Morning Room")
            room_two = self._create_room(db, name="Afternoon Room")
            # Fill the full 5-hour daily limit with one booking
            self._create_pending_booking(
                db,
                user=user,
                room=room_one,
                start_time=self._aware_time(day=2, hour=10),
                duration_minutes=300,
            )

            # Any additional booking on the same day should now be blocked
            with self.assertRaises(self.DailyBookingLimitError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room_two,
                    start_time=self._aware_time(day=2, hour=15),
                    duration_minutes=60,
                )

    def test_121a_customer_daily_limit_counts_standalone_staff_bookings(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db, name="Room After Staff")
            profile = self.StaffProfile(
                name="Daily Limit Engineer",
                booking_rate_cents=5000,
                booking_enabled=True,
                schedule_published=True,
                active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            staff_start = self.normalize_booking_start(self._aware_time(day=2, hour=10))
            db.add(
                self.StaffBooking(
                    user_id=user.id,
                    staff_profile_id=profile.id,
                    start_time=staff_start,
                    end_time=staff_start + timedelta(minutes=240),
                    duration_minutes=240,
                    price_cents=20000,
                    currency="CAD",
                    status="Requested",
                    booking_code=f"STAFF{uuid4().hex[:8].upper()}",
                    user_email_snapshot=user.email,
                    user_full_name_snapshot=user.full_name,
                    user_phone_snapshot=user.phone,
                )
            )
            db.commit()

            with self.assertRaises(self.DailyBookingLimitError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room,
                    start_time=self._aware_time(day=2, hour=14),
                    duration_minutes=120,
                )

    def test_121b_staff_reschedule_db_guard_returns_conflict(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="staff-admin", is_admin=True)
            user_one = self._create_user(db, email_prefix="staff-one")
            user_two = self._create_user(db, email_prefix="staff-two")
            profile = self.StaffProfile(
                name="Race Guard Engineer",
                booking_rate_cents=5000,
                booking_enabled=True,
                schedule_published=True,
                active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)

            first_start = self.normalize_booking_start(self._aware_time(day=3, hour=10))
            second_start = self.normalize_booking_start(self._aware_time(day=3, hour=15))
            first_start_local = first_start.astimezone(BUSINESS_TIMEZONE)
            first_start_minute = first_start_local.hour * 60 + first_start_local.minute
            first = self.StaffBooking(
                user_id=user_one.id,
                staff_profile_id=profile.id,
                start_time=first_start,
                end_time=first_start + timedelta(minutes=60),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Requested",
                booking_code=f"STAFF{uuid4().hex[:8].upper()}",
                user_email_snapshot=user_one.email,
                user_full_name_snapshot=user_one.full_name,
                user_phone_snapshot=user_one.phone,
            )
            second = self.StaffBooking(
                user_id=user_two.id,
                staff_profile_id=profile.id,
                start_time=second_start,
                end_time=second_start + timedelta(minutes=60),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Requested",
                booking_code=f"STAFF{uuid4().hex[:8].upper()}",
                user_email_snapshot=user_two.email,
                user_full_name_snapshot=user_two.full_name,
                user_phone_snapshot=user_two.phone,
            )
            db.add_all(
                [
                    first,
                    second,
                    self.StaffAvailabilityException(
                        staff_profile_id=profile.id,
                        exception_date=first_start_local.date(),
                        start_minute=first_start_minute,
                        end_minute=first_start_minute + 60,
                        is_available=True,
                        reason="Test availability",
                    ),
                ]
            )
            db.commit()
            db.refresh(second)

            payload = self.StaffBookingRescheduleIn(start_time=first_start)
            with patch("app.services.staff_booking_service.ensure_staff_is_available"):
                with self.assertRaises(self.StaffBookingConflictError):
                    self.reschedule_staff_booking(db, second, admin, payload)

    def test_122_admin_self_booking_bypasses_daily_limit(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True, full_name="Admin User")
            room_one = self._create_room(db, name="Admin Room 1")
            room_two = self._create_room(db, name="Admin Room 2")

            first = self._create_pending_booking(
                db,
                user=admin,
                room=room_one,
                start_time=self._aware_time(day=2, hour=10),
            )
            second = self._create_pending_booking(
                db,
                user=admin,
                room=room_two,
                start_time=self._aware_time(day=2, hour=12),
            )

            self.assertEqual(first.status, "PendingPayment")
            self.assertEqual(second.status, "PendingPayment")

    def test_123_manual_booking_bypasses_daily_limit(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db, email_prefix="manual-target")
            room_one = self._create_room(db, name="Manual Room 1")
            room_two = self._create_room(db, name="Manual Room 2")
            self._create_pending_booking(
                db,
                user=user,
                room=room_one,
                start_time=self._aware_time(day=3, hour=10),
            )

            manual_booking = self.create_manual_booking(
                db,
                admin,
                self.ManualBookingCreate(
                    room_id=room_two.id,
                    user_email=user.email,
                    full_name=user.full_name,
                    start_time=self._aware_time(day=3, hour=12),
                    duration_minutes=60,
                ),
            )

            self.assertEqual(manual_booking["status"], "Paid")
            self.assertEqual(manual_booking["user_email"], user.email)

    def test_124_manual_booking_creates_missing_user(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            room = self._create_room(db)

            booking = self.create_manual_booking(
                db,
                admin,
                self.ManualBookingCreate(
                    room_id=room.id,
                    user_email="new-manual-user@example.com",
                    full_name="Manual Customer",
                    start_time=self._aware_time(day=3, hour=11),
                    duration_minutes=60,
                ),
            )

            created_user = db.query(self.User).filter(self.User.email == "new-manual-user@example.com").first()
            self.assertIsNotNone(created_user)
            self.assertEqual(booking["status"], "Paid")
            self.assertEqual(booking["user_full_name"], "Manual Customer")

    def test_125_room_duration_limit_blocks_long_booking(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db, max_booking_duration_minutes=120)

            with self.assertRaises(ValueError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room,
                    start_time=self._aware_time(day=4, hour=10),
                    duration_minutes=180,
                )

    def test_125a_coming_soon_room_is_not_bookable(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            room.coming_soon = True
            db.commit()

            with self.assertRaises(ValueError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room,
                    start_time=self._aware_time(day=4, hour=10),
                )

            with self.assertRaises(ValueError):
                self.get_room_availability(db, str(room.id), self._aware_date(4))

    def test_125b_tbc_room_is_not_bookable(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            room.status = "tbc"
            db.commit()

            with self.assertRaises(ValueError):
                self._create_pending_booking(
                    db,
                    user=user,
                    room=room,
                    start_time=self._aware_time(day=4, hour=11),
                )

    def test_126_availability_reports_timezone_and_open_slot(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db)

            availability = self.get_room_availability(db, str(room.id), self._aware_date(4))

            self.assertEqual(availability["timezone"], "America/Edmonton")
            open_slot = self._aware_time(day=4, hour=10).isoformat()
            self.assertIn(open_slot, availability["available_start_times"])
            self.assertEqual(availability["max_duration_minutes_by_start"][open_slot], 300)

    def test_127_availability_hides_booked_start(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=5, hour=10),
            )

            availability = self.get_room_availability(db, str(room.id), self._aware_date(5))

            self.assertNotIn(self._aware_time(day=5, hour=10).isoformat(), availability["available_start_times"])
            self.assertIn(self._aware_time(day=5, hour=11).isoformat(), availability["available_start_times"])

    def test_127a_reservation_hold_rejects_booked_slot(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            start_time = self._aware_time(day=5, hour=12)
            self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=start_time,
            )

            with self.assertRaises(self.BookingConflictError):
                self.create_reservation_hold(db, room.id, start_time, 60)

    def test_128_availability_clamps_to_room_max_duration(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db, max_booking_duration_minutes=120)

            availability = self.get_room_availability(db, str(room.id), self._aware_date(5))

            open_slot = self._aware_time(day=5, hour=10).isoformat()
            self.assertEqual(availability["max_duration_minutes_by_start"][open_slot], 120)

    def test_129_availability_clamps_last_slot_to_close(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db)

            availability = self.get_room_availability(db, str(room.id), self._aware_date(5))

            last_slot = self._aware_time(day=5, hour=17).isoformat()
            self.assertEqual(availability["max_duration_minutes_by_start"][last_slot], 60)

    def test_130_payment_session_returns_stub_client_secret(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=10),
            )

            payment_session = self.get_booking_payment_session(db, booking, user)

            self.assertEqual(str(payment_session["booking_id"]), str(booking.id))
            self.assertTrue(payment_session["payment_client_secret"].startswith("pi_client_secret_stub_"))
            self.assertEqual(payment_session["payment_backend"], "stub")

    def test_131_payment_session_rejects_paid_booking(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=11),
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            with self.assertRaises(self.PaymentSessionError):
                self.get_booking_payment_session(db, booking, user)

    def test_131a_payment_session_persists_replaced_intent_and_secret(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=11),
                status="PendingPayment",
                payment_intent_id="pi_stub_existing",
            )

            with patch(
                "app.services.booking_service.core.get_payment_intent_session",
                return_value=SimpleNamespace(
                    intent_id="pi_live_123",
                    client_secret="pi_client_secret_live_123",
                ),
            ):
                payment_session = self.get_booking_payment_session(db, booking, user)

            db.refresh(booking)
            self.assertEqual(payment_session["payment_intent_id"], "pi_live_123")
            self.assertEqual(payment_session["payment_client_secret"], "pi_client_secret_live_123")
            self.assertEqual(booking.payment_intent_id, "pi_live_123")
            self.assertEqual(booking.payment_client_secret, "pi_client_secret_live_123")

    def test_131b_create_booking_rolls_back_when_payment_setup_fails(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            payload = self.BookingCreate(
                room_id=room.id,
                start_time=self._aware_time(day=6, hour=12),
                duration_minutes=60,
                staff_assignments=[],
            )

            with patch(
                "app.services.booking_service.core.create_payment_intent",
                side_effect=self.PaymentConfigurationError("Stripe checkout is not configured."),
            ):
                with self.assertRaises(self.PaymentConfigurationError):
                    self.create_booking(db, user, payload)

            self.assertEqual(db.query(self.Booking).count(), 0)
            self.assertEqual(db.query(self.BookingSlot).count(), 0)

    def test_132_expire_pending_booking_cancels_and_releases_slots(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            booking = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=12),
                status="PendingPayment",
                created_at=stale_created_at,
            )

            expired = self.expire_pending_booking(db, booking, now=datetime.now(timezone.utc))
            db.commit()
            db.refresh(booking)

            self.assertTrue(expired)
            self.assertEqual(booking.status, "Cancelled")
            self.assertEqual(
                db.query(self.BookingSlot).filter(self.BookingSlot.booking_id == booking.id).count(),
                0,
            )
            self.assertEqual(
                db.query(self.BookingStaffAssignment).filter(self.BookingStaffAssignment.booking_id == booking.id).count(),
                0,
            )

    def test_133_expire_stale_pending_bookings_only_cleans_old_pending(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=13),
                status="PendingPayment",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            fresh = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=14),
                status="PendingPayment",
                created_at=datetime.now(timezone.utc),
            )
            paid = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=6, hour=15),
                status="Paid",
                confirmed_at=datetime.now(timezone.utc),
            )

            cleaned = self.expire_stale_pending_bookings(db, now=datetime.now(timezone.utc))
            db.refresh(fresh)
            db.refresh(paid)

            self.assertEqual(cleaned, 1)
            self.assertEqual(fresh.status, "PendingPayment")
            self.assertEqual(paid.status, "Paid")

    def test_134_cancel_booking_sets_reason_and_releases_slots(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=7, hour=10),
            )

            cancelled = self.cancel_booking(db, booking, user, "Customer cancelled")

            self.assertEqual(cancelled.status, "Cancelled")
            self.assertEqual(cancelled.cancellation_reason, "Customer cancelled")
            self.assertEqual(
                db.query(self.BookingSlot).filter(self.BookingSlot.booking_id == booking.id).count(),
                0,
            )

    def test_135_cancel_booking_rejects_checked_in_booking(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            room = self._create_room(db)
            booking = self._insert_booking_direct(
                db,
                user=admin,
                room=room,
                start_time=self._aware_time(day=7, hour=11),
                status="Paid",
                checked_in_at=datetime.now(timezone.utc),
                confirmed_at=datetime.now(timezone.utc),
            )

            with self.assertRaises(ValueError):
                self.cancel_booking(db, booking, admin, "Too late")

    def test_136_process_refund_rejects_over_total(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=7, hour=12),
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            with self.assertRaises(ValueError):
                self.process_refund(
                    db,
                    str(booking.id),
                    admin,
                    self.RefundCreate(amount_cents=booking.price_cents + 1, reason="Too much"),
                )

    def test_136a_partial_refund_keeps_booking_and_staff_guard_active(self) -> None:
        staff_roles = [{"id": "engineer", "name": "Engineer", "add_on_price_cents": 2500}]
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db, staff_roles=staff_roles)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=7, hour=13),
                staff_assignments=["engineer"],
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            refund = self.process_refund(
                db,
                str(booking.id),
                admin,
                self.RefundCreate(amount_cents=1000, reason="Partial credit"),
            )
            db.refresh(booking)

            self.assertEqual(refund.amount_cents, 1000)
            self.assertEqual(booking.status, "Paid")
            self.assertGreater(
                db.query(self.BookingSlot).filter(self.BookingSlot.booking_id == booking.id).count(),
                0,
            )
            self.assertEqual(
                db.query(self.BookingStaffAssignment)
                .filter(self.BookingStaffAssignment.booking_id == booking.id)
                .count(),
                1,
            )

    def test_137_clear_bookings_for_admin_day_only_deletes_target_day(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db)
            target = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=10),
            )
            keep = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=9, hour=10),
            )

            result = self.clear_bookings_for_admin_day(db, admin, self._aware_date(8))

            self.assertEqual(result["deleted_count"], 1)
            self.assertIsNone(db.query(self.Booking).filter(self.Booking.id == target.id).first())
            self.assertIsNotNone(db.query(self.Booking).filter(self.Booking.id == keep.id).first())

    def test_138_clear_past_bookings_for_admin_only_deletes_past(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db)
            past_time = datetime.now(BUSINESS_TIMEZONE) - timedelta(days=1)
            future_time = datetime.now(BUSINESS_TIMEZONE) + timedelta(days=1)
            past_hour = min(max(past_time.hour, 10), 17)
            future_hour = min(max(future_time.hour, 10), 17)
            past = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=past_time.replace(hour=past_hour, minute=0, second=0, microsecond=0),
            )
            future = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=future_time.replace(hour=future_hour, minute=0, second=0, microsecond=0),
            )

            result = self.clear_past_bookings_for_admin(db, admin)

            self.assertEqual(result["deleted_count"], 1)
            self.assertIsNone(db.query(self.Booking).filter(self.Booking.id == past.id).first())
            self.assertIsNotNone(db.query(self.Booking).filter(self.Booking.id == future.id).first())

    def test_138b_clear_bookings_for_admin_day_preserves_audit_history(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            room = self._create_room(db)
            manual_booking = self.create_manual_booking(
                db,
                admin,
                self.ManualBookingCreate(
                    user_email="walkin@example.com",
                    full_name="Walk In",
                    room_id=room.id,
                    start_time=self._aware_time(day=8, hour=10),
                    duration_minutes=60,
                    note="Front desk override",
                ),
            )

            result = self.clear_bookings_for_admin_day(db, admin, self._aware_date(8))

            self.assertEqual(result["deleted_count"], 1)
            db.expire_all()
            audit_logs = (
                db.query(self.AuditLog)
                .filter(
                    self.AuditLog.action.in_(
                        ["manual_booking_created", "bulk_bookings_cleared_for_day"]
                    )
                )
                .order_by(self.AuditLog.created_at.asc())
                .all()
            )

            self.assertEqual(len(audit_logs), 2)
            manual_audit = next(
                audit_log for audit_log in audit_logs if audit_log.action == "manual_booking_created"
            )
            clear_audit = next(
                audit_log for audit_log in audit_logs if audit_log.action == "bulk_bookings_cleared_for_day"
            )
            self.assertIsNone(manual_audit.booking_id)
            self.assertIsNone(clear_audit.booking_id)
            self.assertIn(str(manual_booking["id"]), clear_audit.details["booking_ids"])
            self.assertEqual(clear_audit.details["deleted_count"], 1)

    def test_139_mark_booking_paid_sets_confirmed_at(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=11),
            )

            paid = self.mark_booking_paid(db, booking, booking.payment_intent_id)

            self.assertEqual(paid.status, "Paid")
            self.assertIsNotNone(paid.confirmed_at)

    def test_139a_waive_booking_payment_marks_booking_paid_for_free(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=11),
            )
            original_price_cents = booking.price_cents

            updated = self.waive_booking_payment(db, str(booking.id), admin)
            db.refresh(updated)

            self.assertEqual(updated.status, "Paid")
            self.assertEqual(updated.price_cents, 0)
            self.assertIsNotNone(updated.confirmed_at)
            self.assertTrue(updated.payment_intent_id.startswith("admin_waived_"))

            audit_logs = (
                db.query(self.AuditLog)
                .filter(self.AuditLog.booking_id == booking.id)
                .order_by(self.AuditLog.created_at.asc())
                .all()
            )
            self.assertEqual([audit.action for audit in audit_logs], ["payment_confirmed", "payment_waived_by_admin"])
            waived_audit = audit_logs[-1]
            self.assertEqual(waived_audit.actor_id, admin.id)
            self.assertEqual(waived_audit.details["original_price_cents"], original_price_cents)

    def test_139b_mark_booking_paid_manually_keeps_price(self) -> None:
        with self.SessionLocal() as db:
            admin = self._create_user(db, email_prefix="admin", is_admin=True)
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=12),
            )
            original_price_cents = booking.price_cents

            updated = self.mark_booking_paid_manually(db, str(booking.id), admin)
            db.refresh(updated)

            self.assertEqual(updated.status, "Paid")
            self.assertEqual(updated.price_cents, original_price_cents)
            self.assertIsNotNone(updated.confirmed_at)
            self.assertTrue(updated.payment_intent_id.startswith("admin_manual_paid_"))

            audit_logs = (
                db.query(self.AuditLog)
                .filter(self.AuditLog.booking_id == booking.id)
                .order_by(self.AuditLog.created_at.asc())
                .all()
            )
            self.assertEqual(
                [audit.action for audit in audit_logs],
                ["payment_confirmed", "payment_marked_paid_by_admin"],
            )
            manual_audit = audit_logs[-1]
            self.assertEqual(manual_audit.actor_id, admin.id)
            self.assertEqual(manual_audit.details["price_cents"], original_price_cents)

    def test_139c_create_booking_applies_promo_code_discount(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db, hourly_rate_cents=10000)
            self._create_promo_code(db, code="FOUNDATION10", percent_off=10)

            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=14),
                promo_code="FOUNDATION10",
            )

            self.assertEqual(booking.original_price_cents, 10000)
            self.assertEqual(booking.discount_cents, 1000)
            self.assertEqual(booking.price_cents, 9450)
            self.assertEqual(booking.promo_code, "FOUNDATION10")

    def test_140_webhook_success_is_idempotent_for_paid_booking(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=12),
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            result = self.handle_payment_webhook_event(
                db,
                {
                    "type": "payment_intent.succeeded",
                    "data": {
                        "object": {
                            "id": booking.payment_intent_id,
                            "metadata": {"booking_id": str(booking.id)},
                        }
                    },
                },
            )

            self.assertEqual(result["status"], "Paid")
            self.assertTrue(result["received"])

    def test_141_webhook_payment_failed_cancels_booking(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=13),
            )

            result = self.handle_payment_webhook_event(
                db,
                {
                    "type": "payment_intent.payment_failed",
                    "data": {
                        "object": {
                            "id": booking.payment_intent_id,
                            "metadata": {"booking_id": str(booking.id)},
                        }
                    },
                },
            )
            db.refresh(booking)

            self.assertEqual(result["status"], "Cancelled")
            self.assertEqual(booking.cancellation_reason, "Payment failed")

    def test_142_webhook_charge_refunded_marks_refunded(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=14),
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            result = self.handle_payment_webhook_event(
                db,
                {
                    "type": "charge.refunded",
                    "data": {
                        "object": {
                            "id": booking.payment_intent_id,
                            "metadata": {"booking_id": str(booking.id)},
                        }
                    },
                },
            )
            db.refresh(booking)

            self.assertEqual(result["status"], "Refunded")
            self.assertEqual(booking.status, "Refunded")

    def test_142a_webhook_partial_charge_refund_keeps_booking_active(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=8, hour=15),
            )
            self.mark_booking_paid(db, booking, booking.payment_intent_id)

            result = self.handle_payment_webhook_event(
                db,
                {
                    "type": "charge.refunded",
                    "data": {
                        "object": {
                            "id": booking.payment_intent_id,
                            "amount": booking.price_cents,
                            "amount_refunded": 1000,
                            "metadata": {"booking_id": str(booking.id)},
                        }
                    },
                },
            )
            db.refresh(booking)

            self.assertEqual(result["status"], "Paid")
            self.assertEqual(booking.status, "Paid")
            self.assertGreater(
                db.query(self.BookingSlot).filter(self.BookingSlot.booking_id == booking.id).count(),
                0,
            )

    def test_143_list_bookings_for_user_expires_stale_pending_first(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db)
            room = self._create_room(db)
            booking = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=9, hour=10),
                status="PendingPayment",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )

            bookings = self.list_bookings_for_user(db, user)

            stale = next(item for item in bookings if item.id == booking.id)
            self.assertEqual(stale.status, "Cancelled")

    def test_144_get_booking_for_user_hides_other_users_booking(self) -> None:
        with self.SessionLocal() as db:
            owner = self._create_user(db, email_prefix="owner")
            other = self._create_user(db, email_prefix="other")
            room = self._create_room(db)
            booking = self._create_pending_booking(
                db,
                user=owner,
                room=room,
                start_time=self._aware_time(day=9, hour=11),
            )

            hidden = self.get_booking_for_user(db, str(booking.id), other)
            visible = self.get_booking_for_user(db, str(booking.id), owner)

            self.assertIsNone(hidden)
            self.assertEqual(str(visible.id), str(booking.id))

    def test_145_serialize_admin_booking_prefers_snapshots(self) -> None:
        with self.SessionLocal() as db:
            user = self._create_user(db, full_name="Live Name", phone="5553334444")
            room = self._create_room(db, name="Snapshot Room")
            booking = self._insert_booking_direct(
                db,
                user=user,
                room=room,
                start_time=self._aware_time(day=9, hour=12),
                user_email_snapshot="snapshot@example.com",
                user_full_name_snapshot="Snapshot Name",
                user_phone_snapshot="5559998888",
            )

            serialized = self.serialize_admin_booking(
                booking,
                user_email="live@example.com",
                user_full_name="Live Different",
                user_phone="5550001111",
                room_name=room.name,
            )

            self.assertEqual(serialized["user_email"], "snapshot@example.com")
            self.assertEqual(serialized["user_full_name"], "Snapshot Name")
            self.assertEqual(serialized["user_phone"], "5559998888")
            self.assertEqual(serialized["room_name"], room.name)


def _add_booking_schema_duration_tests() -> None:
    valid_values = [60, 120, 180, 240, 300]
    invalid_values = [0, 30, 59, 61, 90, 301, 360]

    def make_valid_test(value: int):
        def test(self) -> None:
            self.assertEqual(
                self.validate_booking_duration_minutes(value, label="Bookings"),
                value,
            )

        return test

    def make_invalid_test(value: int):
        def test(self) -> None:
            with self.assertRaises(ValueError):
                self.validate_booking_duration_minutes(value, label="Bookings")

        return test

    def make_valid_room_test(value: int):
        def test(self) -> None:
            room = self.RoomCreate(
                name="Matrix Room",
                description="Booking test room",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
                max_booking_duration_minutes=value,
            )
            self.assertEqual(room.max_booking_duration_minutes, value)

        return test

    def make_invalid_room_test(value: int):
        def test(self) -> None:
            with self.assertRaises(ValueError):
                self.RoomCreate(
                    name="Matrix Room",
                    description="Booking test room",
                    capacity=4,
                    photos=[],
                    hourly_rate_cents=5000,
                    max_booking_duration_minutes=value,
                )

        return test

    for index, value in enumerate(valid_values, start=1):
        setattr(
            BookingSchemaMatrixTest,
            f"test_{index:03d}_booking_duration_{value}_is_valid",
            make_valid_test(value),
        )

    for offset, value in enumerate(invalid_values, start=len(valid_values) + 1):
        setattr(
            BookingSchemaMatrixTest,
            f"test_{offset:03d}_booking_duration_{value}_is_invalid",
            make_invalid_test(value),
        )

    start_offset = len(valid_values) + len(invalid_values)
    for index, value in enumerate(valid_values, start=start_offset + 1):
        setattr(
            BookingSchemaMatrixTest,
            f"test_{index:03d}_room_max_duration_{value}_is_valid",
            make_valid_room_test(value),
        )

    invalid_offset = start_offset + len(valid_values)
    for index, value in enumerate(invalid_values, start=invalid_offset + 1):
        setattr(
            BookingSchemaMatrixTest,
            f"test_{index:03d}_room_max_duration_{value}_is_invalid",
            make_invalid_room_test(value),
        )


def _add_booking_schema_model_tests() -> None:
    def test_025_booking_create_accepts_aware_aligned_start(self) -> None:
        payload = self.BookingCreate(
            room_id=uuid4(),
            start_time=self._aware_time(hour=10),
            duration_minutes=60,
            staff_assignments=["engineer", "engineer"],
        )
        self.assertEqual(payload.start_time.minute, 0)
        self.assertEqual(payload.staff_assignments, ["engineer"])

    def test_026_booking_create_rejects_naive_start(self) -> None:
        with self.assertRaises(ValueError):
            self.BookingCreate(
                room_id=uuid4(),
                start_time=datetime(2026, 5, 1, 10, 0),
                duration_minutes=60,
            )

    def test_027_booking_create_rejects_half_hour_start(self) -> None:
        with self.assertRaises(ValueError):
            self.BookingCreate(
                room_id=uuid4(),
                start_time=self._aware_time(hour=10, minute=30),
                duration_minutes=60,
            )

    def test_027a_room_create_normalizes_valid_status(self) -> None:
        room = self.RoomCreate(name="Status Room", status="TBC")
        self.assertEqual(room.status, "tbc")

    def test_027b_room_create_rejects_invalid_status(self) -> None:
        with self.assertRaises(ValueError):
            self.RoomCreate(name="Status Room", status="offline")

    def test_028_booking_create_rejects_non_zero_seconds(self) -> None:
        with self.assertRaises(ValueError):
            self.BookingCreate(
                room_id=uuid4(),
                start_time=self._aware_time(hour=10, second=1),
                duration_minutes=60,
            )

    def test_029_reservation_create_accepts_aware_aligned_start(self) -> None:
        payload = self.ReservationCreate(
            room_id=uuid4(),
            start_time=self._aware_time(hour=11),
            duration_minutes=120,
        )
        self.assertEqual(payload.duration_minutes, 120)

    def test_030_reservation_create_rejects_naive_start(self) -> None:
        with self.assertRaises(ValueError):
            self.ReservationCreate(
                room_id=uuid4(),
                start_time=datetime(2026, 5, 1, 11, 0),
                duration_minutes=60,
            )

    def test_031_reservation_create_rejects_half_hour_start(self) -> None:
        with self.assertRaises(ValueError):
            self.ReservationCreate(
                room_id=uuid4(),
                start_time=self._aware_time(hour=11, minute=30),
                duration_minutes=60,
            )

    def test_032_reservation_create_rejects_non_zero_seconds(self) -> None:
        with self.assertRaises(ValueError):
            self.ReservationCreate(
                room_id=uuid4(),
                start_time=self._aware_time(hour=11, second=1),
                duration_minutes=60,
            )

    def test_033_normalize_staff_selection_ids_handles_empty_value(self) -> None:
        self.assertEqual(self.normalize_staff_selection_ids(None), [])

    def test_034_normalize_staff_selection_ids_dedupes_strings(self) -> None:
        self.assertEqual(
            self.normalize_staff_selection_ids(["engineer", "engineer", "filmer"]),
            ["engineer", "filmer"],
        )

    def test_035_normalize_staff_selection_ids_supports_dict_ids(self) -> None:
        self.assertEqual(
            self.normalize_staff_selection_ids([{"id": "engineer"}, {"id": "filmer"}]),
            ["engineer", "filmer"],
        )

    def test_036_normalize_staff_selection_ids_falls_back_to_name(self) -> None:
        self.assertEqual(
            self.normalize_staff_selection_ids([{"name": "Sound Engineer"}]),
            ["Sound Engineer"],
        )

    def test_037_normalize_staff_selection_ids_ignores_blank_entries(self) -> None:
        self.assertEqual(
            self.normalize_staff_selection_ids(["", None, "engineer"]),
            ["engineer"],
        )

    def test_038_resolve_staff_assignments_matches_by_id(self) -> None:
        assignments = self.resolve_staff_assignments(
            [{"id": "engineer", "name": "Sound Engineer"}],
            ["engineer"],
        )
        self.assertEqual(assignments[0]["name"], "Sound Engineer")

    def test_039_resolve_staff_assignments_matches_by_name_case_insensitive(self) -> None:
        assignments = self.resolve_staff_assignments(
            [{"id": "engineer", "name": "Sound Engineer"}],
            ["sound engineer"],
        )
        self.assertEqual(assignments[0]["id"], "engineer")

    def test_040_resolve_staff_assignments_dedupes_same_staff(self) -> None:
        assignments = self.resolve_staff_assignments(
            [{"id": "engineer", "name": "Sound Engineer"}],
            ["engineer", "Sound Engineer"],
        )
        self.assertEqual(len(assignments), 1)

    def test_041_resolve_staff_assignments_rejects_missing_staff(self) -> None:
        with self.assertRaises(ValueError):
            self.resolve_staff_assignments(
                [{"id": "engineer", "name": "Sound Engineer"}],
                ["filmer"],
            )

    def test_042_resolve_staff_assignments_returns_copy_not_source_reference(self) -> None:
        source = [{"id": "engineer", "name": "Sound Engineer", "skills": ["Mixing"]}]
        assignments = self.resolve_staff_assignments(source, ["engineer"])
        assignments[0]["name"] = "Changed"
        self.assertEqual(source[0]["name"], "Sound Engineer")

    setattr(BookingSchemaMatrixTest, "test_025_booking_create_accepts_aware_aligned_start", test_025_booking_create_accepts_aware_aligned_start)
    setattr(BookingSchemaMatrixTest, "test_026_booking_create_rejects_naive_start", test_026_booking_create_rejects_naive_start)
    setattr(BookingSchemaMatrixTest, "test_027_booking_create_rejects_half_hour_start", test_027_booking_create_rejects_half_hour_start)
    setattr(BookingSchemaMatrixTest, "test_028_booking_create_rejects_non_zero_seconds", test_028_booking_create_rejects_non_zero_seconds)
    setattr(BookingSchemaMatrixTest, "test_029_reservation_create_accepts_aware_aligned_start", test_029_reservation_create_accepts_aware_aligned_start)
    setattr(BookingSchemaMatrixTest, "test_030_reservation_create_rejects_naive_start", test_030_reservation_create_rejects_naive_start)
    setattr(BookingSchemaMatrixTest, "test_031_reservation_create_rejects_half_hour_start", test_031_reservation_create_rejects_half_hour_start)
    setattr(BookingSchemaMatrixTest, "test_032_reservation_create_rejects_non_zero_seconds", test_032_reservation_create_rejects_non_zero_seconds)
    setattr(BookingSchemaMatrixTest, "test_033_normalize_staff_selection_ids_handles_empty_value", test_033_normalize_staff_selection_ids_handles_empty_value)
    setattr(BookingSchemaMatrixTest, "test_034_normalize_staff_selection_ids_dedupes_strings", test_034_normalize_staff_selection_ids_dedupes_strings)
    setattr(BookingSchemaMatrixTest, "test_035_normalize_staff_selection_ids_supports_dict_ids", test_035_normalize_staff_selection_ids_supports_dict_ids)
    setattr(BookingSchemaMatrixTest, "test_036_normalize_staff_selection_ids_falls_back_to_name", test_036_normalize_staff_selection_ids_falls_back_to_name)
    setattr(BookingSchemaMatrixTest, "test_037_normalize_staff_selection_ids_ignores_blank_entries", test_037_normalize_staff_selection_ids_ignores_blank_entries)
    setattr(BookingSchemaMatrixTest, "test_038_resolve_staff_assignments_matches_by_id", test_038_resolve_staff_assignments_matches_by_id)
    setattr(BookingSchemaMatrixTest, "test_039_resolve_staff_assignments_matches_by_name_case_insensitive", test_039_resolve_staff_assignments_matches_by_name_case_insensitive)
    setattr(BookingSchemaMatrixTest, "test_040_resolve_staff_assignments_dedupes_same_staff", test_040_resolve_staff_assignments_dedupes_same_staff)
    setattr(BookingSchemaMatrixTest, "test_041_resolve_staff_assignments_rejects_missing_staff", test_041_resolve_staff_assignments_rejects_missing_staff)
    setattr(BookingSchemaMatrixTest, "test_042_resolve_staff_assignments_returns_copy_not_source_reference", test_042_resolve_staff_assignments_returns_copy_not_source_reference)


def _add_reservation_hold_tests() -> None:
    def test_101_create_hold_returns_prefixed_token(self) -> None:
        hold = self.reservation_service.create_hold(self._slot_keys("10:00"))
        self.assertTrue(hold.token.startswith("hold_"))

    def test_102_create_hold_validates_single_slot(self) -> None:
        hold = self.reservation_service.create_hold(self._slot_keys("10:00"))
        self.assertTrue(self.reservation_service.validate_hold(self._slot_keys("10:00"), hold.token))

    def test_103_create_hold_validates_multiple_slots(self) -> None:
        slots = self._slot_keys("10:00", "10:30")
        hold = self.reservation_service.create_hold(slots)
        self.assertTrue(self.reservation_service.validate_hold(slots, hold.token))

    def test_104_create_hold_respects_custom_ttl(self) -> None:
        hold = self.reservation_service.create_hold(self._slot_keys("11:00"), ttl_seconds=2)
        self.assertGreaterEqual(hold.expires_at, int(time.time()) + 1)

    def test_105_duplicate_hold_on_same_slot_raises(self) -> None:
        self.reservation_service.create_hold(self._slot_keys("11:00"))
        with self.assertRaises(ValueError):
            self.reservation_service.create_hold(self._slot_keys("11:00"))

    def test_106_overlapping_hold_on_multi_slot_set_raises(self) -> None:
        self.reservation_service.create_hold(self._slot_keys("12:00", "12:30"))
        with self.assertRaises(ValueError):
            self.reservation_service.create_hold(self._slot_keys("12:30", "13:00"))

    def test_107_release_hold_removes_matching_token(self) -> None:
        slots = self._slot_keys("13:00")
        hold = self.reservation_service.create_hold(slots)
        self.reservation_service.release_hold(slots, hold.token)
        self.assertFalse(self.reservation_service.validate_hold(slots, hold.token))

    def test_108_release_hold_with_wrong_token_keeps_hold(self) -> None:
        slots = self._slot_keys("13:30")
        hold = self.reservation_service.create_hold(slots)
        self.reservation_service.release_hold(slots, "hold_wrong")
        self.assertTrue(self.reservation_service.validate_hold(slots, hold.token))

    def test_109_validate_hold_returns_false_for_unknown_slot(self) -> None:
        hold = self.reservation_service.create_hold(self._slot_keys("14:00"))
        self.assertFalse(
            self.reservation_service.validate_hold(self._slot_keys("14:30"), hold.token)
        )

    def test_110_expired_hold_becomes_invalid(self) -> None:
        slots = self._slot_keys("14:30")
        hold = self.reservation_service.create_hold(slots, ttl_seconds=1)
        time.sleep(1.1)
        self.assertFalse(self.reservation_service.validate_hold(slots, hold.token))

    def test_111_expired_hold_allows_new_hold(self) -> None:
        slots = self._slot_keys("15:00")
        self.reservation_service.create_hold(slots, ttl_seconds=1)
        time.sleep(1.1)
        new_hold = self.reservation_service.create_hold(slots, ttl_seconds=1)
        self.assertTrue(self.reservation_service.validate_hold(slots, new_hold.token))

    def test_112_release_hold_does_not_touch_other_active_hold(self) -> None:
        first_slots = self._slot_keys("15:30")
        second_slots = self._slot_keys("16:00")
        first_hold = self.reservation_service.create_hold(first_slots)
        second_hold = self.reservation_service.create_hold(second_slots)
        self.reservation_service.release_hold(first_slots, first_hold.token)
        self.assertFalse(self.reservation_service.validate_hold(first_slots, first_hold.token))
        self.assertTrue(self.reservation_service.validate_hold(second_slots, second_hold.token))

    setattr(ReservationHoldMatrixTest, "test_101_create_hold_returns_prefixed_token", test_101_create_hold_returns_prefixed_token)
    setattr(ReservationHoldMatrixTest, "test_102_create_hold_validates_single_slot", test_102_create_hold_validates_single_slot)
    setattr(ReservationHoldMatrixTest, "test_103_create_hold_validates_multiple_slots", test_103_create_hold_validates_multiple_slots)
    setattr(ReservationHoldMatrixTest, "test_104_create_hold_respects_custom_ttl", test_104_create_hold_respects_custom_ttl)
    setattr(ReservationHoldMatrixTest, "test_105_duplicate_hold_on_same_slot_raises", test_105_duplicate_hold_on_same_slot_raises)
    setattr(ReservationHoldMatrixTest, "test_106_overlapping_hold_on_multi_slot_set_raises", test_106_overlapping_hold_on_multi_slot_set_raises)
    setattr(ReservationHoldMatrixTest, "test_107_release_hold_removes_matching_token", test_107_release_hold_removes_matching_token)
    setattr(ReservationHoldMatrixTest, "test_108_release_hold_with_wrong_token_keeps_hold", test_108_release_hold_with_wrong_token_keeps_hold)
    setattr(ReservationHoldMatrixTest, "test_109_validate_hold_returns_false_for_unknown_slot", test_109_validate_hold_returns_false_for_unknown_slot)
    setattr(ReservationHoldMatrixTest, "test_110_expired_hold_becomes_invalid", test_110_expired_hold_becomes_invalid)
    setattr(ReservationHoldMatrixTest, "test_111_expired_hold_allows_new_hold", test_111_expired_hold_allows_new_hold)
    setattr(ReservationHoldMatrixTest, "test_112_release_hold_does_not_touch_other_active_hold", test_112_release_hold_does_not_touch_other_active_hold)


def _add_booking_service_helper_tests() -> None:
    def test_146_normalize_booking_start_converts_to_utc(self) -> None:
        local_start = self._aware_time(day=1, hour=10)
        normalized = self.normalize_booking_start(local_start)
        self.assertEqual(normalized, local_start.astimezone(timezone.utc))

    def test_147_normalize_booking_start_strips_seconds(self) -> None:
        local_start = self._aware_time(day=1, hour=10, second=45)
        normalized = self.normalize_booking_start(local_start)
        self.assertEqual(normalized.second, 0)
        self.assertEqual(normalized.microsecond, 0)

    def test_148_normalize_booking_start_rejects_naive_datetime(self) -> None:
        with self.assertRaises(ValueError):
            self.normalize_booking_start(datetime(2026, 5, 1, 10, 0))

    def test_149_validate_booking_window_accepts_open_hour(self) -> None:
        start = self._aware_time(day=1, hour=10).astimezone(timezone.utc)
        end = self._aware_time(day=1, hour=11).astimezone(timezone.utc)
        self.validate_booking_window(start, end)

    def test_150_validate_booking_window_rejects_half_hour_increment(self) -> None:
        start = self._aware_time(day=1, hour=10, minute=30).astimezone(timezone.utc)
        end = self._aware_time(day=1, hour=11, minute=30).astimezone(timezone.utc)
        with self.assertRaises(ValueError):
            self.validate_booking_window(start, end)

    def test_151_validate_booking_window_rejects_cross_day_booking(self) -> None:
        start = self._aware_time(day=1, hour=17).astimezone(timezone.utc)
        end = self._aware_time(day=2, hour=10).astimezone(timezone.utc)
        with self.assertRaises(ValueError):
            self.validate_booking_window(start, end)

    def test_152_validate_booking_window_rejects_before_open_hour(self) -> None:
        start = self._aware_time(day=1, hour=9).astimezone(timezone.utc)
        end = self._aware_time(day=1, hour=10).astimezone(timezone.utc)
        with self.assertRaises(ValueError):
            self.validate_booking_window(start, end)

    def test_153_validate_booking_window_rejects_after_close_hour(self) -> None:
        start = self._aware_time(day=1, hour=17).astimezone(timezone.utc)
        end = self._aware_time(day=1, hour=19).astimezone(timezone.utc)
        with self.assertRaises(ValueError):
            self.validate_booking_window(start, end)

    def test_154_build_slot_starts_for_one_hour(self) -> None:
        slots = self.build_slot_starts(self._aware_time(day=1, hour=10).astimezone(timezone.utc), 60)
        self.assertEqual(len(slots), 2)

    def test_155_build_slot_starts_for_five_hours(self) -> None:
        slots = self.build_slot_starts(self._aware_time(day=1, hour=10).astimezone(timezone.utc), 300)
        self.assertEqual(len(slots), 10)

    def test_156_calculate_price_cents_for_one_hour(self) -> None:
        self.assertEqual(self.calculate_price_cents(5000, 60), 5000)

    def test_157_calculate_booking_total_cents_adds_staff_prices(self) -> None:
        self.assertEqual(
            self.calculate_booking_total_cents(
                5000,
                60,
                [{"id": "engineer", "name": "Sound Engineer", "add_on_price_cents": 3500}],
            ),
            # Room time (5000) + one staff at the flat $25/hr add-on (2500).
            7500,
        )

    def test_157b_room_staff_addon_is_flat_25_per_hour_per_staff(self) -> None:
        from app.services.booking_service import staff_room_addon_total_cents

        two_staff = [
            {"id": "a", "name": "A", "add_on_price_cents": 9999},
            {"id": "b", "name": "B", "add_on_price_cents": 1},
        ]
        # 2 staff × $25/hr × 2h = 10000, ignoring each profile's configured price.
        self.assertEqual(staff_room_addon_total_cents(two_staff, 120), 10000)
        # Room (5000/hr × 2h) + staff add-on (10000) = 20000.
        self.assertEqual(self.calculate_booking_total_cents(5000, 120, two_staff), 20000)

    def test_158_get_room_max_booking_duration_clamps_low_values(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db, max_booking_duration_minutes=30)
            self.assertEqual(self.get_room_max_booking_duration_minutes(room), 60)

    def test_159_get_room_max_booking_duration_clamps_high_values(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db, max_booking_duration_minutes=900)
            self.assertEqual(self.get_room_max_booking_duration_minutes(room), 300)

    def test_160_pending_booking_expiry_reason_uses_configured_minutes(self) -> None:
        self.assertIn(
            str(self.get_pending_booking_expiry_minutes()),
            self.get_pending_booking_expiry_reason(),
        )

    def test_161_get_day_bounds_spans_exactly_one_business_day(self) -> None:
        utc_start, utc_end = self.get_day_bounds(self._aware_date(10))
        self.assertEqual(int((utc_end - utc_start).total_seconds()), 86400)

    setattr(BookingServiceMatrixTest, "test_146_normalize_booking_start_converts_to_utc", test_146_normalize_booking_start_converts_to_utc)
    setattr(BookingServiceMatrixTest, "test_147_normalize_booking_start_strips_seconds", test_147_normalize_booking_start_strips_seconds)
    setattr(BookingServiceMatrixTest, "test_148_normalize_booking_start_rejects_naive_datetime", test_148_normalize_booking_start_rejects_naive_datetime)
    setattr(BookingServiceMatrixTest, "test_149_validate_booking_window_accepts_open_hour", test_149_validate_booking_window_accepts_open_hour)
    setattr(BookingServiceMatrixTest, "test_150_validate_booking_window_rejects_half_hour_increment", test_150_validate_booking_window_rejects_half_hour_increment)
    setattr(BookingServiceMatrixTest, "test_151_validate_booking_window_rejects_cross_day_booking", test_151_validate_booking_window_rejects_cross_day_booking)
    setattr(BookingServiceMatrixTest, "test_152_validate_booking_window_rejects_before_open_hour", test_152_validate_booking_window_rejects_before_open_hour)
    setattr(BookingServiceMatrixTest, "test_153_validate_booking_window_rejects_after_close_hour", test_153_validate_booking_window_rejects_after_close_hour)
    setattr(BookingServiceMatrixTest, "test_154_build_slot_starts_for_one_hour", test_154_build_slot_starts_for_one_hour)
    setattr(BookingServiceMatrixTest, "test_155_build_slot_starts_for_five_hours", test_155_build_slot_starts_for_five_hours)
    setattr(BookingServiceMatrixTest, "test_156_calculate_price_cents_for_one_hour", test_156_calculate_price_cents_for_one_hour)
    setattr(BookingServiceMatrixTest, "test_157_calculate_booking_total_cents_adds_staff_prices", test_157_calculate_booking_total_cents_adds_staff_prices)
    setattr(BookingServiceMatrixTest, "test_158_get_room_max_booking_duration_clamps_low_values", test_158_get_room_max_booking_duration_clamps_low_values)
    setattr(BookingServiceMatrixTest, "test_159_get_room_max_booking_duration_clamps_high_values", test_159_get_room_max_booking_duration_clamps_high_values)
    setattr(BookingServiceMatrixTest, "test_160_pending_booking_expiry_reason_uses_configured_minutes", test_160_pending_booking_expiry_reason_uses_configured_minutes)
    setattr(BookingServiceMatrixTest, "test_161_get_day_bounds_spans_exactly_one_business_day", test_161_get_day_bounds_spans_exactly_one_business_day)


_add_booking_schema_duration_tests()
_add_booking_schema_model_tests()
_add_reservation_hold_tests()
_add_booking_service_helper_tests()


def _add_guest_booking_tests() -> None:
    def test_162_create_guest_booking_returns_token_and_snapshots_guest_details(self) -> None:
        with self.SessionLocal() as db:
            room = self._create_room(db, hourly_rate_cents=5000)
            payload = self.GuestBookingCreate(
                room_id=room.id,
                start_time=self._aware_time(day=3, hour=11),
                duration_minutes=60,
                guest_name="Guest Booker",
                guest_phone="4035550102",
                staff_assignments=[],
            )

            result = self.create_guest_booking(db, payload)
            booking = db.query(self.Booking).filter(self.Booking.id == result.booking.id).first()

            self.assertTrue(result.access_token)
            self.assertEqual(result.booking.status, "PendingPayment")
            self.assertIsNotNone(booking)
            self.assertEqual(booking.user_full_name_snapshot, "Guest Booker")
            self.assertEqual(booking.user_phone_snapshot, "4035550102")
            self.assertTrue(booking.user_email_snapshot.startswith("guest+"))

    setattr(
        BookingServiceMatrixTest,
        "test_162_create_guest_booking_returns_token_and_snapshots_guest_details",
        test_162_create_guest_booking_returns_token_and_snapshots_guest_details,
    )


_add_guest_booking_tests()
