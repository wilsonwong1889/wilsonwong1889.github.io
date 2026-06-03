"""
Tests for features added in the May 2026 sprint:
  - GST (5%) calculation and persistence on bookings
  - User "About You" profile fields (emergency_contact, visible_minority, city)
  - Booking intake fields saved to note
  - Room and staff photo uploads accepting PNG, WebP (Pillow conversion)
  - Room creation with photo URL persisted across edits
  - Auth validation error messages
  - Staff carousel and room page HTML contracts
  - BIPOC Foundation email addresses
"""

import io
import os
import struct
import sys
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from math import floor
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

BUSINESS_TIMEZONE = ZoneInfo("America/Edmonton")


def _minimal_png_bytes(width: int = 4, height: int = 4) -> bytes:
    """Build a valid minimal RGB PNG in-memory without Pillow."""
    def pack_chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + b"\xff\x80\x40" * width for _ in range(height))
    idat = pack_chunk(b"IDAT", zlib.compress(raw_rows))
    return sig + pack_chunk(b"IHDR", ihdr_data) + idat + pack_chunk(b"IEND", b"")


def _minimal_jpeg_bytes() -> bytes:
    from PIL import Image as _PILImage
    buf = io.BytesIO()
    _PILImage.new("RGB", (2, 2), color=(64, 128, 64)).save(buf, format="JPEG")
    return buf.getvalue()


class GSTUnitTest(unittest.TestCase):
    """Pure unit tests for GST calculation — no database required."""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("SECRET_KEY", "gst-unit-test-secret")
        os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")
        os.environ.setdefault("PAYMENT_BACKEND", "stub")
        from app.services.booking_service import calculate_tax_cents, calculate_price_cents
        cls.calculate_tax_cents = staticmethod(calculate_tax_cents)
        cls.calculate_price_cents = staticmethod(calculate_price_cents)

    def test_gst_is_5_percent_floor(self) -> None:
        self.assertEqual(self.calculate_tax_cents(1000), 50)

    def test_gst_floors_fractional_cents(self) -> None:
        # 5% of 333 = 16.65 → floor = 16
        self.assertEqual(self.calculate_tax_cents(333), 16)

    def test_gst_zero_subtotal(self) -> None:
        self.assertEqual(self.calculate_tax_cents(0), 0)

    def test_gst_on_hourly_rate(self) -> None:
        # $50/hr for 2 hours = 10000 cents; GST = 500 cents
        subtotal = self.calculate_price_cents(5000, 120)
        self.assertEqual(subtotal, 10000)
        self.assertEqual(self.calculate_tax_cents(subtotal), 500)

    def test_gst_total_equals_subtotal_plus_tax(self) -> None:
        subtotal = self.calculate_price_cents(5000, 60)
        tax = self.calculate_tax_cents(subtotal)
        total = subtotal + tax
        self.assertEqual(total, 5250)  # $50 + $2.50 GST


class NewFeaturesSmokeTest(unittest.TestCase):
    """Integration tests using a live test database — mirrors AppSmokeTest pattern."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_database_url = os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres",
        )
        cls.test_database_name = f"studio_new_features_{uuid4().hex[:8]}"
        cls.test_database_url = os.environ.get(
            "TEST_DATABASE_URL",
            f"postgresql://postgres:password@localhost:5432/{cls.test_database_name}",
        )
        cls._create_database()

        os.environ["DATABASE_URL"] = cls.test_database_url
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "new-features-test-secret")
        os.environ["PAYMENT_BACKEND"] = "stub"
        os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                sys.modules.pop(module_name)

        from app.database import Base, SessionLocal, engine
        from app.main import app
        from app.models.booking import Booking
        from app.models.room import Room
        from app.models.staff_booking import StaffBooking
        from app.models.staff_profile import StaffProfile
        from app.models.user import User
        from app.services.seed_service import ensure_admin_user, ensure_promo_codes, ensure_rooms

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.Booking = Booking
        cls.Room = Room
        cls.StaffBooking = StaffBooking
        cls.StaffProfile = StaffProfile
        cls.User = User
        cls.ensure_admin_user = staticmethod(ensure_admin_user)
        cls.ensure_rooms = staticmethod(ensure_rooms)
        cls.ensure_promo_codes = staticmethod(ensure_promo_codes)

        Base.metadata.create_all(engine)

        with SessionLocal() as db:
            cls.ensure_admin_user(
                db,
                email="admin@newfeatures.example.com",
                password="AdminPass1!",
                full_name="Feature Admin",
                phone="403-000-0001",
            )
            cls.ensure_promo_codes(db)

        from fastapi.testclient import TestClient
        cls.client = TestClient(app)
        cls._cached_admin_token: str = ""

    def setUp(self) -> None:
        from app.core import rate_limit
        rate_limit._requests.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        try:
            admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
            with admin_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {cls.test_database_name}"))
            admin_engine.dispose()
        except Exception:
            pass

    @classmethod
    def _create_database(cls) -> None:
        admin_engine = create_engine(cls.admin_database_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {cls.test_database_name}"))
        admin_engine.dispose()

    def _register_and_login(self, email: str, password: str = "TestPass1!") -> str:
        """Register a user and return their bearer token."""
        self.client.post("/api/auth/signup", json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "phone": "403-555-0100",
        })
        resp = self.client.post("/api/auth/login", data={"username": email, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["access_token"]

    def _admin_token(self) -> str:
        if not type(self)._cached_admin_token:
            resp = self.client.post("/api/auth/login", data={
                "username": "admin@newfeatures.example.com",
                "password": "AdminPass1!",
            })
            self.assertEqual(resp.status_code, 200, resp.text)
            type(self)._cached_admin_token = resp.json()["access_token"]
        return type(self)._cached_admin_token

    def _create_room(self, token: str, name: str = "Test Room", rate_cents: int = 10000) -> dict:
        resp = self.client.post(
            "/api/rooms",
            json={
                "name": name,
                "description": "A test room",
                "capacity": 4,
                "photos": [],
                "hourly_rate_cents": rate_cents,
                "max_booking_duration_minutes": 300,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def _future_start(self, days_ahead: int = 14, hour: int = 14) -> str:
        target = datetime.now(BUSINESS_TIMEZONE).date() + timedelta(days=days_ahead)
        utc_hour = hour + 6  # MDT offset
        return datetime(
            target.year, target.month, target.day, utc_hour, 0, 0,
            tzinfo=timezone.utc,
        ).isoformat()

    # ── Account creation ─────────────────────────────────────────────────────

    def test_01_signup_creates_account_and_login_works(self) -> None:
        email = f"signup-{uuid4().hex[:6]}@example.com"
        resp = self.client.post("/api/auth/signup", json={
            "email": email,
            "password": "GoodPass1!",
            "full_name": "New User",
            "phone": "403-555-0200",
        })
        self.assertEqual(resp.status_code, 201, resp.text)

        resp = self.client.post("/api/auth/login", data={"username": email, "password": "GoodPass1!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("access_token", resp.json())

    def test_02_login_wrong_password_returns_401(self) -> None:
        email = f"badpass-{uuid4().hex[:6]}@example.com"
        self.client.post("/api/auth/signup", json={
            "email": email, "password": "RightPass1!", "full_name": "Bad Pass User",
        })
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "WrongPass99!"})
        self.assertEqual(resp.status_code, 401, resp.text)
        self.assertEqual(resp.json().get("detail"), "Invalid email or password.")

    def test_03_login_unknown_email_returns_generic_401(self) -> None:
        resp = self.client.post("/api/auth/login", data={
            "username": "nobody-at-all@example.com", "password": "AnyPass1!",
        })
        self.assertEqual(resp.status_code, 401, resp.text)
        self.assertEqual(resp.json().get("detail"), "Invalid email or password.")

    def test_04_duplicate_signup_returns_error(self) -> None:
        email = f"dup-{uuid4().hex[:6]}@example.com"
        self.client.post("/api/auth/signup", json={
            "email": email, "password": "First1Pass!", "full_name": "First",
        })
        resp = self.client.post("/api/auth/signup", json={
            "email": email, "password": "Second1Pass!", "full_name": "Second",
        })
        self.assertIn(resp.status_code, (400, 409, 422), resp.text)

    # ── User profile — About You fields ──────────────────────────────────────

    def test_10_profile_about_you_fields_save_and_load(self) -> None:
        email = f"aboutyou-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.put("/api/users/me", json={
            "emergency_contact": "403-555-9911",
            "visible_minority": "Black",
            "city": "Lethbridge",
        }, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)

        resp = self.client.get("/api/users/me", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["emergency_contact"], "403-555-9911")
        self.assertEqual(data["visible_minority"], "Black")
        self.assertEqual(data["city"], "Lethbridge")

    def test_11_profile_about_you_fields_are_optional(self) -> None:
        email = f"aboutyou-opt-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.get("/api/users/me", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIsNone(data.get("emergency_contact"))
        self.assertIsNone(data.get("visible_minority"))
        self.assertIsNone(data.get("city"))

    def test_12_profile_about_you_visible_minority_prefer_not_to_say(self) -> None:
        email = f"minority-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.put("/api/users/me", json={"visible_minority": "Prefer not to say"}, headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["visible_minority"], "Prefer not to say")

    # ── Room creation ─────────────────────────────────────────────────────────

    def test_20_admin_creates_room_and_it_appears_in_list(self) -> None:
        token = self._admin_token()
        room_name = f"Studio {uuid4().hex[:4]}"
        room = self._create_room(token, name=room_name)
        self.assertIn("id", room)
        self.assertEqual(room["name"], room_name)

        resp = self.client.get("/api/rooms")
        self.assertEqual(resp.status_code, 200)
        names = [r["name"] for r in resp.json()]
        self.assertIn(room_name, names)

    def test_21_room_created_with_photo_url_persists(self) -> None:
        token = self._admin_token()
        photo_url = "/assets/media/rooms/fake-photo.jpg"
        resp = self.client.post(
            "/api/rooms",
            json={
                "name": f"Photo Room {uuid4().hex[:4]}",
                "description": "Has a photo",
                "capacity": 2,
                "photos": [photo_url],
                "hourly_rate_cents": 4000,
                "max_booking_duration_minutes": 180,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        room = resp.json()
        self.assertIn(photo_url, room.get("photos", []))

    def test_22_room_photo_upload_accepts_jpeg(self) -> None:
        token = self._admin_token()
        jpeg = _minimal_jpeg_bytes()
        resp = self.client.post(
            "/api/admin/rooms/photo",
            files={"photo": ("room.jpg", jpeg, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        url = resp.json()["photo_url"]
        self.assertTrue(url.startswith("/assets/media/rooms/"))
        self.assertTrue(url.endswith(".jpg"))

    def test_23_room_photo_upload_accepts_png_and_converts(self) -> None:
        token = self._admin_token()
        png = _minimal_png_bytes()
        resp = self.client.post(
            "/api/admin/rooms/photo",
            files={"photo": ("room.png", png, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        url = resp.json()["photo_url"]
        self.assertTrue(url.startswith("/assets/media/rooms/"))
        self.assertTrue(url.endswith(".jpg"), "PNG should be converted and saved as .jpg")

    def test_24_room_photo_upload_rejects_invalid_file(self) -> None:
        token = self._admin_token()
        resp = self.client.post(
            "/api/admin/rooms/photo",
            files={"photo": ("malware.exe", b"MZ\x90\x00this-is-not-an-image", "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertIn(resp.status_code, (400, 422), resp.text)

    def test_25_room_photo_upload_requires_admin(self) -> None:
        email = f"regular-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        png = _minimal_png_bytes()
        resp = self.client.post(
            "/api/admin/rooms/photo",
            files={"photo": ("room.png", png, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    # ── Staff profile creation ────────────────────────────────────────────────

    def test_30_admin_creates_staff_profile(self) -> None:
        token = self._admin_token()
        resp = self.client.post(
            "/api/admin/staff",
            json={
                "name": f"Staff {uuid4().hex[:4]}",
                "description": "A skilled technician",
                "add_on_price_cents": 2500,
                "active": True,
                "skills": ["Audio", "Lighting"],
                "talents": [],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        profile = resp.json()
        self.assertIn("id", profile)
        self.assertEqual(profile["add_on_price_cents"], 2500)

    def test_31_staff_photo_upload_accepts_jpeg(self) -> None:
        token = self._admin_token()
        jpeg = _minimal_jpeg_bytes()
        resp = self.client.post(
            "/api/admin/staff/photo",
            files={"photo": ("staff.jpg", jpeg, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        url = resp.json()["photo_url"]
        self.assertTrue(url.startswith("/assets/media/staff/"))

    def test_32_staff_photo_upload_accepts_png(self) -> None:
        token = self._admin_token()
        png = _minimal_png_bytes()
        resp = self.client.post(
            "/api/admin/staff/photo",
            files={"photo": ("staff.png", png, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        url = resp.json()["photo_url"]
        self.assertTrue(url.startswith("/assets/media/staff/"))
        self.assertTrue(url.endswith(".jpg"), "PNG should be saved as .jpg")

    def test_33_staff_photo_upload_rejects_invalid_extension(self) -> None:
        token = self._admin_token()
        resp = self.client.post(
            "/api/admin/staff/photo",
            files={"photo": ("hack.txt", b"not an image at all", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertIn(resp.status_code, (400, 422), resp.text)

    # ── Room booking with GST ─────────────────────────────────────────────────

    def test_40_booking_room_stores_tax_cents(self) -> None:
        admin_token = self._admin_token()
        room = self._create_room(admin_token, name=f"GST Room {uuid4().hex[:4]}", rate_cents=10000)
        room_id = room["id"]

        email = f"gst-booker-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)

        start = self._future_start(days_ahead=20, hour=14)
        resp = self.client.post(
            "/api/bookings",
            json={
                "room_id": room_id,
                "start_time": start,
                "duration_minutes": 60,
                "name": "GST Test User",
                "email": email,
                "phone": "403-555-0300",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        booking = resp.json()

        subtotal = floor(10000 * (60 / 60))  # $100.00
        expected_tax = floor(subtotal * 0.05)   # $5.00
        expected_total = subtotal + expected_tax  # $105.00

        self.assertEqual(booking.get("tax_cents"), expected_tax,
                         f"Expected tax_cents={expected_tax}, got {booking.get('tax_cents')}")
        self.assertEqual(booking.get("price_cents"), expected_total,
                         f"Expected price_cents={expected_total}, got {booking.get('price_cents')}")

    def test_41_booking_price_cents_equals_subtotal_plus_tax(self) -> None:
        admin_token = self._admin_token()
        room = self._create_room(admin_token, name=f"Tax Check Room {uuid4().hex[:4]}", rate_cents=10000)

        email = f"tax-check-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)

        start = self._future_start(days_ahead=21, hour=15)
        resp = self.client.post(
            "/api/bookings",
            json={
                "room_id": room["id"],
                "start_time": start,
                "duration_minutes": 120,
                "name": "Tax Check User",
                "email": email,
                "phone": "403-555-0301",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        b = resp.json()
        self.assertEqual(b["price_cents"], b["tax_cents"] + floor(10000 * 2))

    # ── Booking with staff ────────────────────────────────────────────────────

    def test_50_booking_with_staff_includes_staff_price_in_subtotal(self) -> None:
        admin_token = self._admin_token()

        staff_resp = self.client.post(
            "/api/admin/staff",
            json={
                "name": f"Staff GST {uuid4().hex[:4]}",
                "description": "Test staff for GST",
                "add_on_price_cents": 3000,
                "active": True,
                "skills": [],
                "talents": [],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(staff_resp.status_code, 201, staff_resp.text)
        staff_id = staff_resp.json()["id"]

        room_resp = self.client.post(
            "/api/rooms",
            json={
                "name": f"Staff GST Room {uuid4().hex[:4]}",
                "description": "Room with staff",
                "capacity": 3,
                "photos": [],
                "hourly_rate_cents": 10000,
                "max_booking_duration_minutes": 300,
                "staff_roles": [{"id": staff_id, "name": "Staff GST", "add_on_price_cents": 3000}],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(room_resp.status_code, 201, room_resp.text)
        room_id = room_resp.json()["id"]

        email = f"staff-booker-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        start = self._future_start(days_ahead=22, hour=14)

        resp = self.client.post(
            "/api/bookings",
            json={
                "room_id": room_id,
                "start_time": start,
                "duration_minutes": 60,
                "name": "Staff Booker",
                "email": email,
                "phone": "403-555-0400",
                "staff_assignments": [staff_id],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        b = resp.json()
        # subtotal = room (10000) + staff (3000) = 13000; tax = floor(13000*0.05) = 650
        self.assertEqual(b.get("tax_cents"), floor(13000 * 0.05))
        self.assertEqual(b.get("price_cents"), 13000 + floor(13000 * 0.05))

    # ── Booking intake note ───────────────────────────────────────────────────

    def test_60_booking_contact_note_can_store_intake_data(self) -> None:
        admin_token = self._admin_token()
        room = self._create_room(admin_token, name=f"Intake Room {uuid4().hex[:4]}")

        email = f"intake-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        start = self._future_start(days_ahead=23, hour=13)

        create_resp = self.client.post(
            "/api/bookings",
            json={
                "room_id": room["id"],
                "start_time": start,
                "duration_minutes": 60,
                "name": "Intake User",
                "email": email,
                "phone": "403-555-0500",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)
        booking_id = create_resp.json()["id"]

        intake_note = "Emergency contact: 403-555-9911\nVisible minority: Black\nCity: Lethbridge"
        update_resp = self.client.put(
            f"/api/bookings/{booking_id}/contact",
            json={"note": intake_note},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(update_resp.status_code, 200, update_resp.text)

        get_resp = self.client.get(
            f"/api/bookings/{booking_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        self.assertEqual(get_resp.json()["note"], intake_note)

    # ── HTML contracts — new UI elements ─────────────────────────────────────

    def test_70_booking_page_has_intake_fields(self) -> None:
        resp = self.client.get("/booking")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("booking-emergency-contact", resp.text)
        self.assertIn("booking-visible-minority", resp.text)
        self.assertIn("booking-city", resp.text)
        self.assertIn("About you", resp.text)

    def test_71_booking_page_intake_in_contact_section_not_payment(self) -> None:
        resp = self.client.get("/booking")
        html = resp.text
        contact_idx = html.index("booking-checkout-contact")
        payment_idx = html.index("booking-payment-panel")
        intake_idx = html.index("booking-emergency-contact")
        # intake should appear between contact section and payment section
        self.assertLess(contact_idx, intake_idx)
        self.assertLess(intake_idx, payment_idx)

    def test_72_account_page_has_about_you_fieldset(self) -> None:
        resp = self.client.get("/account")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("About you", resp.text)
        self.assertIn("emergency_contact", resp.text)
        self.assertIn("visible_minority", resp.text)
        self.assertIn('name="city"', resp.text)

    def test_73_account_page_file_inputs_accept_png(self) -> None:
        resp = self.client.get("/account")
        self.assertIn(".png", resp.text)
        self.assertIn(".webp", resp.text)

    def test_74_admin_page_file_inputs_accept_png(self) -> None:
        resp = self.client.get("/admin")
        self.assertIn(".png", resp.text)
        self.assertIn(".webp", resp.text)

    def test_75_bipoc_foundation_email_on_home_page(self) -> None:
        resp = self.client.get("/")
        self.assertIn("lethsmakeithappen@bipocfoundation.org", resp.text)
        self.assertNotIn("ujuperpetua05@gmail.com", resp.text)

    def test_76_faq_page_has_both_bipoc_emails(self) -> None:
        resp = self.client.get("/faq")
        self.assertIn("lethsmakeithappen@bipocfoundation.org", resp.text)
        self.assertIn("lethscoordinator@bipocfoundation.org", resp.text)

    def test_77_rooms_page_has_catalog(self) -> None:
        resp = self.client.get("/rooms")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("rooms-catalog-shell", resp.text)
        self.assertIn("rooms-grid", resp.text)

    def test_78_staff_page_has_catalog(self) -> None:
        resp = self.client.get("/staff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("staff-catalog-section", resp.text)
        self.assertIn("staff-team-grid", resp.text)

    def test_79_rooms_js_has_gst_rendering(self) -> None:
        resp = self.client.get("/assets/js/views/room-booking.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("GST", resp.text)

    def test_80_booking_detail_js_has_tax_rendering(self) -> None:
        resp = self.client.get("/assets/js/views/booking-detail.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tax_cents", resp.text)
        self.assertIn("GST", resp.text)

    def test_81_auth_js_has_field_level_error_functions(self) -> None:
        resp = self.client.get("/assets/js/views/auth.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("applyLoginError", resp.text)
        self.assertIn("applySignupError", resp.text)
        self.assertIn("invalid email or password", resp.text.lower())
        self.assertIn("forgot password", resp.text.lower())

    def test_82_profile_js_has_about_you_fields(self) -> None:
        resp = self.client.get("/assets/js/views/profile.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("emergency_contact", resp.text)
        self.assertIn("visible_minority", resp.text)
        self.assertIn("city", resp.text)

    # ── GST serialization ─────────────────────────────────────────────────────

    def test_90_admin_booking_lookup_includes_tax_cents(self) -> None:
        admin_token = self._admin_token()
        room = self._create_room(admin_token, name=f"Admin Tax Room {uuid4().hex[:4]}")

        email = f"admin-tax-{uuid4().hex[:6]}@example.com"
        token = self._register_and_login(email)
        start = self._future_start(days_ahead=25, hour=16)

        create_resp = self.client.post(
            "/api/bookings",
            json={
                "room_id": room["id"],
                "start_time": start,
                "duration_minutes": 60,
                "name": "Admin Tax User",
                "email": email,
                "phone": "403-555-0600",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.text)

        lookup_resp = self.client.get(
            f"/api/admin/bookings?email={email}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(lookup_resp.status_code, 200, lookup_resp.text)
        bookings = lookup_resp.json()
        self.assertTrue(len(bookings) > 0)
        b = bookings[0]
        self.assertIn("tax_cents", b, "admin booking lookup must expose tax_cents")
        self.assertGreater(b["tax_cents"], 0)
