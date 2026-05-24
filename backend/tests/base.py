import os
import struct
import sys
import unittest
import zlib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text


def _minimal_png_bytes(width: int = 4, height: int = 4) -> bytes:
    def pack_chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + b"\xff\x80\x40" * width for _ in range(height))
    idat = pack_chunk(b"IDAT", zlib.compress(raw_rows))
    return sig + pack_chunk(b"IHDR", ihdr_data) + idat + pack_chunk(b"IEND", b"")


class BaseAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_database_url = os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres",
        )
        cls.test_database_name = f"studio_week1_{uuid4().hex[:8]}"
        cls.test_database_url = os.environ.get(
            "TEST_DATABASE_URL",
            f"postgresql://postgres:password@localhost:5432/{cls.test_database_name}",
        )
        cls._create_database()

        os.environ["DATABASE_URL"] = cls.test_database_url
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "week1-test-secret")
        os.environ["PAYMENT_BACKEND"] = "stub"

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                sys.modules.pop(module_name)

        from app.database import Base, SessionLocal, engine
        from app.main import app
        from app.models.booking import AuditLog, Booking, BookingSlot, NotificationLog, Refund, Review
        from app.models.promo_code import PromoCode
        from app.models.room import Room
        from app.models.staff_booking import StaffBooking
        from app.models.staff_profile import StaffProfile
        from app.models.user import User
        from app.services.seed_service import ensure_admin_user, ensure_promo_codes, ensure_rooms

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.AuditLog = AuditLog
        cls.Booking = Booking
        cls.BookingSlot = BookingSlot
        cls.NotificationLog = NotificationLog
        cls.Refund = Refund
        cls.Review = Review
        cls.PromoCode = PromoCode
        cls.Room = Room
        cls.StaffBooking = StaffBooking
        cls.StaffProfile = StaffProfile
        cls.User = User
        cls.ensure_admin_user = staticmethod(ensure_admin_user)
        cls.ensure_promo_codes = staticmethod(ensure_promo_codes)
        cls.ensure_rooms = staticmethod(ensure_rooms)

        cls.Base.metadata.create_all(bind=cls.engine)

        from fastapi.testclient import TestClient

        cls.client = TestClient(app)

    def setUp(self) -> None:
        from app.core import rate_limit
        from app.services import reservation_service

        rate_limit._requests.clear()
        reservation_service._memory_holds.clear()

        with self.SessionLocal() as db:
            for model in (
                self.AuditLog,
                self.NotificationLog,
                self.Refund,
                self.Review,
                self.PromoCode,
                self.BookingSlot,
                self.Booking,
                self.StaffBooking,
                self.Room,
                self.StaffProfile,
                self.User,
            ):
                db.query(model).delete()
            db.commit()

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

    def _future_date(self, day: int = 1) -> date:
        business_timezone = ZoneInfo("America/Edmonton")
        base = datetime.now(business_timezone).date() + timedelta(days=30)
        days_until_wed = (2 - base.weekday()) % 7
        wednesday = base + timedelta(days=days_until_wed)
        week_offset = (day - 1) // 4
        day_in_week = (day - 1) % 4
        return wednesday + timedelta(weeks=week_offset, days=day_in_week)

    def _future_time(self, day: int = 1, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
        business_timezone = ZoneInfo("America/Edmonton")
        target_date = self._future_date(day)
        shifted_hour = hour + 2
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            shifted_hour,
            minute,
            second,
            tzinfo=business_timezone,
        )

    @staticmethod
    def _room_price(hourly_rate_cents: int, duration_minutes: int) -> int:
        from math import floor
        subtotal = floor(hourly_rate_cents * duration_minutes / 60)
        return subtotal + floor(subtotal * 0.05)

    @staticmethod
    def _staff_price(booking_rate_cents: int, duration_minutes: int) -> int:
        from math import floor
        return floor(booking_rate_cents * duration_minutes / 60)
