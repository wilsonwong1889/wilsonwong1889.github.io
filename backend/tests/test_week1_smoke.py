import os
import struct
import sys
import unittest
import hashlib
import hmac
import json
import re
import time
import zlib
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text


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


class AppSmokeTest(unittest.TestCase):
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

    def test_00_seed_helpers(self) -> None:
        with self.SessionLocal() as db:
            admin = type(self).ensure_admin_user(
                db,
                email="seed-admin@example.com",
                password="SeedAdmin123!",
                full_name="Seed Admin",
                phone="403-393-8857",
                role="AdminManager",
            )
            rooms = type(self).ensure_rooms(
                db,
                rooms=[
                    {
                        "name": "Seed Room",
                        "description": "Seeded room",
                        "capacity": 2,
                        "photos": [],
                        "hourly_rate_cents": 5000,
                    }
                ],
            )
            admin_email = admin.email
            admin_is_admin = admin.is_admin
            admin_phone = admin.phone
            admin_role = admin.role
            room_name = rooms[0].name
            room_count = len(rooms)
            default_seeded_rooms = type(self).ensure_rooms(db)
            promo_codes = type(self).ensure_promo_codes(db)
            seeded_promo = db.query(self.PromoCode).filter(self.PromoCode.code == "SUMMER60").one()
            seeded_promo_percent = seeded_promo.percent_off
            seeded_promo_active = seeded_promo.active

        self.assertEqual(admin_email, "seed-admin@example.com")
        self.assertTrue(admin_is_admin)
        self.assertEqual(admin_phone, "403-393-8857")
        self.assertEqual(admin_role, "AdminManager")
        self.assertEqual(room_count, 1)
        self.assertEqual(room_name, "Seed Room")
        self.assertIsInstance(default_seeded_rooms, list)
        self.assertEqual(len(promo_codes), 1)
        self.assertEqual(seeded_promo_percent, 60)
        self.assertTrue(seeded_promo_active)

    def test_10_week_two_smoke_flow(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["checks"]["database"])

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Creative Innovation Hub", response.text)
        self.assertIn("2525 36 St N, Lethbridge, AB T1H 5L1", response.text)
        self.assertIn("403-393-8857", response.text)
        self.assertIn("lethsmakeithappen@bipocfoundation.org", response.text)
        self.assertIn("Wednesday to Saturday 12:00 PM &ndash; 8:00 PM", response.text)
        self.assertIn("home-booking-search", response.text)
        self.assertIn("Book now", response.text)
        self.assertNotIn("home-stats-band", response.text)
        self.assertIn("BIPOC Digital Media &amp; Creative Innovation Hub", response.text)
        self.assertIn("home-carousel-button-prev", response.text)
        self.assertIn("home-carousel-dots", response.text)
        self.assertIn("Studio location on Google Maps", response.text)
        self.assertIn("header-user-menu-shell", response.text)
        self.assertIn("header-user-trigger", response.text)
        self.assertIn("header-profile-link", response.text)
        self.assertIn("header-bookings-link", response.text)
        self.assertNotIn('id="rooms-grid"', response.text)
        self.assertIn('/assets/styles/app.css?v=', response.text)

        for path in ("/account", "/pricing", "/rooms", "/room", "/reserve", "/bookings", "/booking", "/payment-success", "/admin"):
            page_response = self.client.get(path)
            self.assertEqual(page_response.status_code, 200, page_response.text)

        pricing_page = self.client.get("/pricing")
        self.assertIn("Pricing & membership", pricing_page.text)
        self.assertIn("$50/hr", pricing_page.text)
        self.assertIn("$15", pricing_page.text)
        self.assertIn("Open Studio Night: May 9, 2026", pricing_page.text)
        self.assertNotIn("60% beta", pricing_page.text)

        account_page = self.client.get("/account")
        self.assertIn("Delete profile", account_page.text)
        self.assertIn("Require two-factor verification at login", account_page.text)
        self.assertIn("login-2fa-form", account_page.text)
        self.assertIn("forgot-password-form", account_page.text)
        self.assertIn("reset-password-form", account_page.text)
        self.assertIn("Forgot password?", account_page.text)
        self.assertIn("Confirm password", account_page.text)
        self.assertIn("signup-password-match-feedback", account_page.text)
        self.assertIn("reset-password-match-feedback", account_page.text)
        self.assertIn("profile-password-match-feedback", account_page.text)
        self.assertIn("profile-avatar-file", account_page.text)
        self.assertIn("profile-avatar-preview", account_page.text)
        self.assertIn("account-danger-zone", account_page.text)
        self.assertIn('/assets/styles/app.css?v=', account_page.text)

        bookings_page = self.client.get("/bookings")
        self.assertIn("My Bookings", bookings_page.text)
        self.assertIn("Manage room and staff bookings in one place without switching flows.", bookings_page.text)
        self.assertIn("Book room", bookings_page.text)
        self.assertIn("Book staff", bookings_page.text)
        self.assertIn("Upcoming reservations", bookings_page.text)
        self.assertIn("Past &amp; cancelled", bookings_page.text)
        self.assertIn("booking-history-upcoming-tab", bookings_page.text)
        self.assertIn("booking-history-history-tab", bookings_page.text)
        self.assertIn("booking-history-upcoming-count", bookings_page.text)
        self.assertIn("booking-history-history-count", bookings_page.text)
        self.assertIn("recent-bookings-shell", bookings_page.text)
        self.assertIn("pending-bookings-list", bookings_page.text)
        self.assertIn("recent-bookings-list", bookings_page.text)
        self.assertIn('/assets/styles/app.css?v=', bookings_page.text)

        booking_page = self.client.get("/booking")
        self.assertIn("Ready to book a studio?", booking_page.text)
        self.assertIn("booking-detail-empty", booking_page.text)
        self.assertIn("booking-detail-card", booking_page.text)
        self.assertIn("Booking summary", booking_page.text)
        self.assertIn("Payment details", booking_page.text)
        self.assertIn("Back to bookings", booking_page.text)
        self.assertIn('/assets/styles/app.css?v=', booking_page.text)

        reserve_page = self.client.get("/reserve")
        self.assertIn("continue as a guest", reserve_page.text)
        self.assertIn("reserve-promo-code-input", reserve_page.text)
        self.assertIn("reserve-promo-preview-button", reserve_page.text)
        self.assertIn("reserve-promo-feedback", reserve_page.text)

        admin_page = self.client.get("/admin")
        self.assertIn("Accounts", admin_page.text)
        self.assertIn("Backend test cases", admin_page.text)
        self.assertIn("admin-panel-accounts", admin_page.text)
        self.assertIn("admin-panel-qa", admin_page.text)
        self.assertIn("admin-booking-quick-summary", admin_page.text)
        self.assertIn("admin-booking-quick-filters", admin_page.text)
        self.assertIn('data-admin-subpage-group="bookings"', admin_page.text)
        self.assertIn('data-admin-subpage-group="staff"', admin_page.text)
        self.assertIn('data-admin-subpage-group="rooms"', admin_page.text)
        self.assertIn("Room calendar", admin_page.text)
        self.assertIn("admin-calendar-month", admin_page.text)
        self.assertIn("admin-room-calendar-grid", admin_page.text)
        self.assertIn("Promos", admin_page.text)
        self.assertIn("admin-promo-form", admin_page.text)
        self.assertIn("admin-promo-codes-list", admin_page.text)
        self.assertIn("admin-accounts-list", admin_page.text)
        self.assertIn("admin-test-case-summary", admin_page.text)
        self.assertIn("admin-test-cases-list", admin_page.text)
        self.assertIn('/assets/styles/app.css?v=', admin_page.text)
        self.assertLess(admin_page.text.index("Room management"), admin_page.text.index("Backend test cases"))

        response = self.client.get("/assets/styles/app.css")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("--bg:", response.text)

        response = self.client.get("/assets/media/recording-studio.svg")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("<svg", response.text)

        response = self.client.get("/assets/js/main.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("refreshSession", response.text)
        self.assertIn('./api.js"', response.text)
        self.assertIn('./state.js"', response.text)
        self.assertIn('views/admin.js"', response.text)
        self.assertIn('views/booking-detail.js"', response.text)
        self.assertIn('views/payment-success.js"', response.text)
        self.assertIn('views/bookings.js"', response.text)
        self.assertIn('views/room-booking.js"', response.text)
        self.assertIn('views/rooms.js"', response.text)
        self.assertIn('views/room-detail.js"', response.text)
        self.assertIn('views/info.js"', response.text)
        self.assertIn('views/auth.js"', response.text)
        self.assertIn('views/profile.js"', response.text)
        self.assertNotIn("?v=", response.text)

        response = self.client.get("/assets/js/views/bookings.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('../state.js"', response.text)
        self.assertIn('let bookingHistoryTab = "upcoming";', response.text)
        self.assertIn("Pending payment", response.text)
        self.assertIn("No upcoming bookings yet. New room and staff reservations will appear here.", response.text)
        self.assertIn('bookingHistoryTab = "history";', response.text)
        self.assertIn('window.confirm("Are you sure you want to cancel this booking?")', response.text)
        self.assertNotIn("api.previewPromoCode", response.text)
        self.assertNotIn("booking-room-select", response.text)

        response = self.client.get("/assets/js/views/room-booking.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('api.previewPromoCode(code, context.amountCents)', response.text)
        self.assertIn("reserve-promo-preview-button", response.text)
        self.assertIn("promo_code: getReservePromoInputValue() || null", response.text)

        response = self.client.get("/assets/js/views/booking-detail.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("stripeElements.submit()", response.text)
        self.assertIn('new URL("/payment-success"', response.text)
        self.assertIn("bookingReschedulePanel", response.text)
        self.assertIn("bookingReviewForm", response.text)
        self.assertIn("api.rescheduleBooking(state.selectedBooking.id", response.text)
        self.assertIn("api.saveBookingReview(state.selectedBooking.id", response.text)
        self.assertIn("Skip Stripe as admin", response.text)
        self.assertIn('api.adminWaiveBookingPayment(button.dataset.bookingId)', response.text)
        self.assertIn("Mark paid manually as admin", response.text)
        self.assertIn('api.adminMarkBookingPaid(button.dataset.bookingId)', response.text)
        self.assertIn('window.confirm("Are you sure you want to cancel this booking?")', response.text)
        self.assertIn("Add to calendar", response.text)
        self.assertIn("downloadBookingCalendarFile(booking)", response.text)
        self.assertIn("Download receipt PDF", response.text)
        self.assertIn("downloadBookingReceiptPdf(booking.id, booking.booking_code)", response.text)

        response = self.client.get("/assets/js/views/payment-success.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Booking confirmed", response.text)
        self.assertIn("You're all booked", response.text)
        self.assertIn("Payment received — confirming your booking", response.text)
        self.assertIn("Refresh status", response.text)
        self.assertIn("Add to calendar", response.text)
        self.assertIn("downloadBookingCalendarFile(currentPaymentSuccessBooking)", response.text)
        self.assertIn("Download receipt PDF", response.text)
        self.assertIn("downloadBookingReceiptPdf(currentPaymentSuccessBooking.id, currentPaymentSuccessBooking.booking_code)", response.text)

        response = self.client.get("/assets/js/views/profile.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('window.prompt("Enter your password to delete this account.")', response.text)
        self.assertIn("api.uploadProfileAvatar(avatarFile)", response.text)
        self.assertIn('api.deleteProfile({ password: deletePassword })', response.text)

        response = self.client.get("/assets/js/views/admin.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("setActiveAdminSubpage", response.text)
        self.assertIn('document.querySelectorAll("[data-admin-subpage-button]")', response.text)
        self.assertIn('setActiveAdminSubpage("bookings", "queue")', response.text)
        self.assertIn('setActiveAdminSubpage("accounts", "detail")', response.text)
        self.assertIn('data-admin-calendar-date', response.text)
        self.assertIn('Showing day board for ${selectedAdminScheduleDate}.', response.text)
        self.assertIn("formatMonthHeading(selectedAdminCalendarMonth)", response.text)
        self.assertIn("Showing ${filteredBookings.length} of ${baseBookings.length}", response.text)
        self.assertIn("Live booking queue", admin_page.text)
        self.assertIn("Needs attention", response.text)
        self.assertIn("admin-promo-form", response.text)
        self.assertIn("renderAdminPromoCodes(currentState)", response.text)
        self.assertIn("api.adminCreatePromoCode(payload)", response.text)
        self.assertIn('setActiveAdminSubpage("bookings", "promos")', response.text)
        self.assertIn('window.prompt("Enter your admin password to delete this account.")', response.text)
        self.assertIn("api.adminDeleteUser(button.dataset.userId, { admin_password: adminPassword })", response.text)

        response = self.client.get("/assets/js/views/rooms.js")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('detail: { group: "rooms", subpage: "editor" }', response.text)
        self.assertIn("elements.roomsSearchButton?.addEventListener", response.text)
        self.assertIn("searchRoomsByAvailability", response.text)
        self.assertIn("function escapeHtml(value)", response.text)
        self.assertIn('href="/reserve?id=${safeRoomId}"', response.text)

        signup_payload = {
            "email": "user@example.com",
            "password": "Password123!",
            "full_name": "Week One User",
            "phone": "1234567890",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)
        user_id = response.json()["id"]

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        access_token = response.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {access_token}"}

        response = self.client.get("/api/auth/me", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email"], "user@example.com")

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "full_name": "Updated User",
                "birthday": "1995-07-14",
                "billing_address": {
                    "line1": "123 Booking St",
                    "line2": "Unit 4",
                    "city": "Edmonton",
                    "state": "AB",
                    "postal_code": "T5J0N3",
                    "country": "Canada",
                },
                "opt_in_sms": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["full_name"], "Updated User")
        self.assertEqual(response.json()["birthday"], "1995-07-14")
        self.assertEqual(response.json()["billing_address"]["city"], "Edmonton")
        self.assertNotIn("saved_payment_method", response.json())
        self.assertTrue(response.json()["opt_in_sms"])

        response = self.client.put(
            "/api/users/me/password",
            headers=user_headers,
            json={
                "current_password": "Password123!",
                "new_password": "NewPassword456!",
            },
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "NewPassword456!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/rooms")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsInstance(response.json(), list)

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.id == user_id).first()
            user.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "NewPassword456!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/rooms?include_inactive=true")
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.post(
            "/api/admin/promo-codes",
            headers=admin_headers,
            json={
                "code": "FOUNDATION10",
                "description": "10% off first booking",
                "percent_off": 10,
                "active": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["code"], "FOUNDATION10")
        self.assertEqual(response.json()["percent_off"], 10)

        response = self.client.get("/api/admin/promo-codes", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["code"], "FOUNDATION10")

        response = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": "FOUNDATION10", "amount_cents": 5000},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["discount_cents"], 500)
        self.assertEqual(response.json()["final_amount_cents"], 4500)

        response = self.client.post(
            "/api/admin/rooms/photo",
            headers=admin_headers,
            files={"photo": ("room.png", _minimal_png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        room_photo_url = response.json()["photo_url"]
        self.assertTrue(room_photo_url.startswith("/assets/media/rooms/"))

        response = self.client.post(
            "/api/rooms",
            headers=admin_headers,
            json={
                "name": "Studio A",
                "description": "Main room",
                "capacity": 4,
                "photos": [room_photo_url],
                "hourly_rate_cents": 5000,
                "max_booking_duration_minutes": 180,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        room_id = response.json()["id"]
        self.assertEqual(response.json()["max_booking_duration_minutes"], 180)

        response = self.client.get(f"/api/rooms/{room_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Studio A")
        self.assertEqual(response.json()["max_booking_duration_minutes"], 180)

        response = self.client.put(
            f"/api/admin/rooms/{room_id}",
            headers=admin_headers,
            json={
                "name": "Studio A Edited",
                "description": "Updated main room",
                "capacity": 6,
                "hourly_rate_cents": 6500,
                "max_booking_duration_minutes": 240,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Studio A Edited")
        self.assertEqual(response.json()["capacity"], 6)
        self.assertEqual(response.json()["hourly_rate_cents"], 6500)
        self.assertEqual(response.json()["max_booking_duration_minutes"], 240)

        response = self.client.get("/api/rooms?include_inactive=true", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)

        response = self.client.delete(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get(f"/api/rooms/{room_id}")
        self.assertEqual(response.status_code, 404, response.text)

        response = self.client.get(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["active"])

        response = self.client.get("/api/rooms?include_inactive=true", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        archived_room = next(room for room in response.json() if room["id"] == room_id)
        self.assertFalse(archived_room["active"])

        response = self.client.post(f"/api/rooms/{room_id}/restore", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["active"])

        response = self.client.get("/api/rooms")
        self.assertEqual(response.status_code, 200, response.text)
        room_names = [room["name"] for room in response.json()]
        self.assertIn("Studio A Edited", room_names)

        response = self.client.delete(f"/api/rooms/{room_id}/permanent", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get(f"/api/rooms/{room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 404, response.text)

    def test_15_two_factor_login_flow(self) -> None:
        signup_payload = {
            "email": "twofactor@example.com",
            "password": "Password123!",
            "full_name": "Two Factor User",
            "phone": "5552223333",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "two_factor_enabled": True,
                "two_factor_method": "email",
                "opt_in_email": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["two_factor_enabled"])
        self.assertEqual(response.json()["two_factor_method"], "email")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        login_payload = response.json()
        self.assertTrue(login_payload["two_factor_required"])
        self.assertEqual(login_payload["two_factor_method"], "email")
        self.assertIsNotNone(login_payload["two_factor_token"])
        self.assertIsNone(login_payload["access_token"])

        with self.SessionLocal() as db:
            notification = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.type == "login_verification_email_worker")
                .order_by(self.NotificationLog.created_at.desc())
                .first()
            )

        self.assertIsNotNone(notification)
        delivery_message = json.loads(notification.details["delivery"]["message"])
        code_search = re.search(r"\b(\d{6})\b", delivery_message["body"])
        code_match = code_search.group(1) if code_search else None
        self.assertIsNotNone(code_match)

        response = self.client.post(
            "/api/auth/verify-2fa",
            json={
                "two_factor_token": login_payload["two_factor_token"],
                "code": "000000",
            },
        )
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.post(
            "/api/auth/verify-2fa",
            json={
                "two_factor_token": login_payload["two_factor_token"],
                "code": code_match,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_16_login_feedback_and_password_reset_flow(self) -> None:
        signup_payload = {
            "email": "reset-user@example.com",
            "password": "Password123!",
            "full_name": "Reset User",
            "phone": "5554443333",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "not-an-email", "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Enter a valid email address.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": "missing@example.com", "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "We couldn't find an account with that email.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "WrongPassword123!"},
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Wrong password. Try again or reset it.")

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": signup_payload["email"]},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            response.json()["message"],
            "If we found an account with that email, we sent a password reset link.",
        )

        with self.SessionLocal() as db:
            notification = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.type == "password_reset_email_worker")
                .order_by(self.NotificationLog.created_at.desc())
                .first()
            )

        self.assertIsNotNone(notification)
        delivery_message = json.loads(notification.details["delivery"]["message"])
        token_search = re.search(r"reset_token=([A-Za-z0-9._-]+)", delivery_message["body"])
        token = token_search.group(1) if token_search else None
        self.assertIsNotNone(token)

        response = self.client.post(
            "/api/auth/reset-password",
            json={"reset_token": token, "new_password": "NewPassword123!"},
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["detail"], "Wrong password. Try again or reset it.")

        response = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "NewPassword123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_20_week_three_booking_flow(self) -> None:
        from app.config import settings
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

        signup_payload = {
            "email": "booker@example.com",
            "password": "Password123!",
            "full_name": "Booking User",
            "phone": "5551112222",
        }
        response = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "booker@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        booking_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=2, hour=10, minute=0)
        target_date = self._future_date(2)

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        availability = response.json()
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
            past_date.year,
            past_date.month,
            past_date.day,
            10,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.get(f"/api/rooms/{room_id}/availability?date={past_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["available_start_times"], [])

        response = self.client.post(
            "/api/bookings/reservations",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": past_start.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Bookings cannot be created for past dates or times")

        response = self.client.post(
            "/api/bookings/guest",
            json={
                "room_id": room_id,
                "start_time": past_start.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Past Guest",
                "guest_phone": "4035550101",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Bookings cannot be created for past dates or times")
        response = self.client.post(
            "/api/bookings/reservations",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        reservation = response.json()
        self.assertTrue(reservation["token"].startswith("hold_"))
        self.assertEqual(len(reservation["slot_keys"]), 2)

        response = self.client.post(
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
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], self._room_price(10000, 60))
        self.assertTrue(booking["payment_intent_id"].startswith("pi_"))
        self.assertTrue(booking["payment_client_secret"])
        if settings.PAYMENT_BACKEND == "stub":
            self.assertTrue(booking["payment_client_secret"].startswith("pi_client_secret_stub_"))
        else:
            self.assertIn("_secret_", booking["payment_client_secret"])
        self.assertTrue(booking["booking_code"])
        self.assertEqual(booking["note"], "Podcast intro and guest setup")
        self.assertIsNotNone(booking["payment_expires_at"])
        self.assertGreater(booking["payment_seconds_remaining"], 0)
        self.assertLessEqual(booking["payment_seconds_remaining"], 300)

        response = self.client.get("/api/bookings", headers=booking_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=booking_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], booking["id"])

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        updated_availability = response.json()
        self.assertNotIn(start_time.isoformat(), updated_availability["available_start_times"])

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "conflict@example.com",
                "password": "Password123!",
                "full_name": "Conflict User",
                "phone": "5550001111",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "conflict@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        conflict_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=booking_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=5, hour=13, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=2, hour=10, minute=30).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=2, hour=11, minute=0).isoformat(),
                "duration_minutes": 120,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["duration_minutes"], 120)
        self.assertEqual(response.json()["price_cents"], self._room_price(10000, 120))

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=3, hour=11, minute=0).isoformat(),
                "duration_minutes": 360,
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=conflict_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=3, hour=9, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            response.json()["detail"],
            "Bookings are only available between 12:00 and 20:00",
        )

    def test_21_guest_booking_endpoint_requires_only_name_and_phone(self) -> None:
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

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=4, hour=11, minute=0)

        response = self.client.post(
            "/api/bookings/guest",
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "guest_name": "Guest Booker",
                "guest_phone": "4035550102",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertTrue(payload["access_token"])
        self.assertEqual(payload["booking"]["status"], "PendingPayment")
        self.assertEqual(payload["booking"]["price_cents"], self._room_price(10000, 60))

        guest_headers = {"Authorization": f"Bearer {payload['access_token']}"}
        response = self.client.get(f"/api/bookings/{payload['booking']['id']}", headers=guest_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], payload["booking"]["id"])
        self.assertEqual(response.json()["user_full_name"], "Guest Booker")
        self.assertEqual(response.json()["user_phone"], "4035550102")
        self.assertIsNone(response.json()["user_email"])

        response = self.client.put(
            f"/api/bookings/{payload['booking']['id']}/contact",
            headers=guest_headers,
            json={
                "full_name": "Checkout Guest",
                "email": "checkout-guest@example.com",
                "phone": "4035550199",
                "note": "Use the east entrance.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user_full_name"], "Checkout Guest")
        self.assertEqual(response.json()["user_email"], "checkout-guest@example.com")
        self.assertEqual(response.json()["user_phone"], "4035550199")
        self.assertEqual(response.json()["note"], "Use the east entrance.")

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
            past_date.year,
            past_date.month,
            past_date.day,
            11,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.get(f"/api/staff/{profile_id}/availability?date={past_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["available_start_times"], [])

        response = self.client.post(
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
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Bookings cannot be created for past dates or times")

        response = self.client.post(
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
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
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
        response = self.client.get(
            f"/api/staff-bookings/{payload['booking']['id']}",
            headers=guest_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["staff_profile"]["name"], "Podcast Engineer")

        response = self.client.get("/api/bookings/feed", headers=guest_headers)
        self.assertEqual(response.status_code, 200, response.text)
        feed = response.json()
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]["booking_kind"], "staff")
        self.assertEqual(feed[0]["staff_profile_name"], "Podcast Engineer")
        self.assertEqual(feed[0]["can_pay"], True)

        response = self.client.post(
            f"/api/staff-bookings/{payload['booking']['id']}/payment-session",
            headers=guest_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["payment_intent_id"])
        self.assertTrue(response.json()["payment_client_secret"])

        response = self.client.put(
            f"/api/staff-bookings/{payload['booking']['id']}/contact",
            headers=guest_headers,
            json={
                "full_name": "Staff Checkout Guest",
                "email": "staff-checkout@example.com",
                "phone": "4035550144",
                "note": "Bring two microphones.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user_full_name"], "Staff Checkout Guest")
        self.assertEqual(response.json()["user_email"], "staff-checkout@example.com")
        self.assertEqual(response.json()["user_phone"], "4035550144")
        self.assertEqual(response.json()["note"], "Bring two microphones.")

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

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=6, hour=12, minute=0)

        response = self.client.post(
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
        self.assertEqual(response.status_code, 201, response.text)
        staff_booking = response.json()["booking"]

        response = self.client.post(
            "/api/auth/login",
            data={"username": "staff-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get(
            f"/api/admin/bookings?booking_code={staff_booking['booking_code']}",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        lookup_rows = response.json()
        self.assertEqual(len(lookup_rows), 1)
        self.assertEqual(lookup_rows[0]["booking_kind"], "staff")
        self.assertEqual(lookup_rows[0]["staff_name"], "Independent Producer")
        self.assertEqual(lookup_rows[0]["status"], "PendingPayment")

        response = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking['id']}/mark-paid",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")

        response = self.client.get(
            f"/api/admin/bookings?booking_code={staff_booking['booking_code']}",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        refreshed_rows = response.json()
        self.assertEqual(refreshed_rows[0]["booking_kind"], "staff")
        self.assertEqual(refreshed_rows[0]["status"], "Paid")

    def test_25_pending_payment_window_expires_and_reopens_slot(self) -> None:
        from app.models.booking import Booking
        from app.models.room import Room

        business_timezone = ZoneInfo("America/Edmonton")
        target_date = self._future_date(4)
        start_time = self._future_time(day=4, hour=10, minute=0)

        with self.SessionLocal() as db:
            room = Room(
                name="Expiry Room",
                description="Room used for pending payment expiry coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
                max_booking_duration_minutes=180,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "expiry@example.com",
                "password": "Password123!",
                "full_name": "Expiry User",
                "phone": "5551112222",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "expiry@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertIsNotNone(booking["payment_expires_at"])

        with self.SessionLocal() as db:
            db_booking = db.query(Booking).filter(Booking.id == UUID(booking["id"])).first()
            db_booking.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
            db.commit()

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Cancelled")
        self.assertEqual(
            response.json()["cancellation_reason"],
            "Payment window expired after 5 minutes",
        )

        response = self.client.post(
            f"/api/bookings/{booking['id']}/payment-session",
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["detail"],
            "Payment is only available for pending bookings",
        )

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(start_time.isoformat(), response.json()["available_start_times"])

    def test_32_admin_backend_test_case_catalog(self) -> None:
        with self.SessionLocal() as db:
            type(self).ensure_admin_user(
                db,
                email="catalog-admin@example.com",
                password="Password123!",
                full_name="Catalog Admin",
            )

        response = self.client.post(
            "/api/auth/login",
            data={"username": "catalog-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()

        self.assertGreaterEqual(len(payload), 12)
        self.assertTrue(all("health" in item for item in payload))
        self.assertTrue(all(item["health"] in {"working", "needs_fix", "not_working"} for item in payload))
        self.assertTrue(any(item["health"] == "working" for item in payload))
        # `not_working` covers the live SendGrid/Twilio verification gap that
        # can't be automated without external sandboxes.
        self.assertTrue(any(item["health"] == "not_working" for item in payload))
        self.assertTrue(any(item["title"] == "Payment confirmation end-to-end" for item in payload))
        self.assertTrue(any(item["title"] == "Runtime config rejects placeholder production secrets" for item in payload))

        response = self.client.get("/api/admin/integrations/suitedash/status", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(response.json()["configured"])
        self.assertEqual(response.json()["contact_meta_path"], "/contact/meta")

        response = self.client.get("/api/admin/integrations/suitedash/contact-meta", headers=admin_headers)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("SuiteDash integration is disabled", response.text)

    def test_33_admin_can_skip_stripe_and_mark_booking_free(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Admin Free Room",
                description="Room used for admin free payment tests",
                capacity=4,
                photos=[],
                hourly_rate_cents=10000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-admin@example.com",
                "password": "Password123!",
                "full_name": "Free Admin",
                "phone": "5551231111",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        admin_id = response.json()["id"]

        with self.SessionLocal() as db:
            admin = db.query(self.User).filter(self.User.id == admin_id).first()
            admin.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "free-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-guest@example.com",
                "password": "Password123!",
                "full_name": "Free Guest",
                "phone": "5551232222",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "free-guest@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        guest_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        free_booking_date = datetime.now(business_timezone).date() + timedelta(days=4)
        start_time = datetime(
            free_booking_date.year,
            free_booking_date.month,
            free_booking_date.day,
            16,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], self._room_price(10000, 60))

        response = self.client.post(
            f"/api/admin/bookings/{booking['id']}/waive-payment",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        waived_booking = response.json()
        self.assertEqual(waived_booking["status"], "Paid")
        self.assertEqual(waived_booking["price_cents"], 0)
        self.assertTrue(waived_booking["payment_intent_id"].startswith("admin_waived_"))

        response = self.client.get(f"/api/bookings/{booking['id']}", headers=guest_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["price_cents"], 0)

        response = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        paid_booking = next(item for item in response.json() if item["id"] == booking["id"])
        self.assertEqual(paid_booking["price_cents"], 0)

        response = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        activity_actions = [item["action"] for item in response.json()]
        self.assertIn("payment_waived_by_admin", activity_actions)

    def test_34_admin_booking_action_suite(self) -> None:
        """Covers mark-paid, check-in, refund, staff waive/mark-paid, and error paths."""
        from app.models.room import Room
        from app.models.staff_profile import StaffProfile

        # ── setup ─────────────────────────────────────────────────────────────
        with self.SessionLocal() as db:
            room = Room(
                name="Admin Action Room",
                description="Room for admin action tests",
                capacity=4,
                photos=[],
                hourly_rate_cents=6000,
            )
            db.add(room)
            profile = StaffProfile(
                name="Action Staff",
                description="Test staff for admin action suite",
                skills=[],
                talents=[],
                booking_rate_cents=5000,
                add_on_price_cents=0,
                service_types=["Recording"],
                booking_enabled=True,
                active=True,
            )
            db.add(profile)
            db.commit()
            db.refresh(room)
            db.refresh(profile)
            room_id = str(room.id)
            profile_id = str(profile.id)

        # create admin
        resp = self.client.post(
            "/api/auth/signup",
            json={"email": "suite-admin@example.com", "password": "Password123!", "full_name": "Suite Admin", "phone": "4031110001"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        admin_user_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == admin_user_id).first()
            u.is_admin = True
            db.commit()
        resp = self.client.post("/api/auth/login", data={"username": "suite-admin@example.com", "password": "Password123!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        # create guest
        resp = self.client.post(
            "/api/auth/signup",
            json={"email": "suite-guest@example.com", "password": "Password123!", "full_name": "Suite Guest", "phone": "4031110002"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        resp = self.client.post("/api/auth/login", data={"username": "suite-guest@example.com", "password": "Password123!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        guest_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        from zoneinfo import ZoneInfo
        biz_tz = ZoneInfo("America/Edmonton")
        base = datetime.now(biz_tz).date() + timedelta(days=10)

        def make_start(day_offset, hour):
            d = base + timedelta(days=day_offset)
            return datetime(d.year, d.month, d.day, hour + 2, 0, tzinfo=biz_tz).isoformat()

        # ── 1. admin mark-paid (room booking) ─────────────────────────────────
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(0, 10), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        booking = resp.json()
        self.assertEqual(booking["status"], "PendingPayment")
        price = booking["price_cents"]
        self.assertGreater(price, 0)

        resp = self.client.post(f"/api/admin/bookings/{booking['id']}/mark-paid", headers=admin_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        paid = resp.json()
        self.assertEqual(paid["status"], "Paid")
        self.assertTrue(paid["payment_intent_id"].startswith("admin_manual_paid_"))
        self.assertEqual(paid["price_cents"], price)

        # ── 2. check-in (room booking already paid) ───────────────────────────
        resp = self.client.post(f"/api/admin/bookings/{booking['id']}/check-in", headers=admin_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        checked_in = resp.json()
        self.assertEqual(checked_in["status"], "Completed")
        self.assertIsNotNone(checked_in["checked_in_at"])

        # ── 3. refund (completed booking) ─────────────────────────────────────
        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/refund",
            headers=admin_headers,
            json={"amount_cents": price, "reason": "Test refund"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        refund = resp.json()
        self.assertIn("id", refund)
        self.assertEqual(refund["amount_cents"], price)

        # ── 4. admin waive-payment (second room booking) ──────────────────────
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(1, 14), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        booking2 = resp.json()
        self.assertEqual(booking2["status"], "PendingPayment")

        resp = self.client.post(f"/api/admin/bookings/{booking2['id']}/waive-payment", headers=admin_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        waived = resp.json()
        self.assertEqual(waived["status"], "Paid")
        self.assertEqual(waived["price_cents"], 0)
        self.assertTrue(waived["payment_intent_id"].startswith("admin_waived_"))

        # ── 5. staff booking: waive-payment ───────────────────────────────────
        resp = self.client.post(
            "/api/staff-bookings",
            headers=guest_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": make_start(2, 10),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        staff_booking = resp.json()
        self.assertEqual(staff_booking["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking['id']}/waive-payment",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertEqual(resp.json()["price_cents"], 0)

        # ── 6. staff booking: mark-paid ────────────────────────────────────────
        resp = self.client.post(
            "/api/staff-bookings",
            headers=guest_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": make_start(3, 10),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        staff_booking2 = resp.json()
        self.assertEqual(staff_booking2["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking2['id']}/mark-paid",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertTrue(resp.json()["payment_intent_id"].startswith("admin_staff_manual_paid_"))

        # ── 7. error: mark-paid on already-Paid booking ────────────────────────
        resp = self.client.post(f"/api/admin/bookings/{booking['id']}/mark-paid", headers=admin_headers)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("pending", resp.json()["detail"].lower())

        # ── 8. error: waive-payment on already-Paid booking ───────────────────
        resp = self.client.post(f"/api/admin/bookings/{booking2['id']}/waive-payment", headers=admin_headers)
        self.assertEqual(resp.status_code, 400, resp.text)

        # ── 9. error: check-in on PendingPayment booking ──────────────────────
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(4, 10), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        pending_id = resp.json()["id"]

        resp = self.client.post(f"/api/admin/bookings/{pending_id}/check-in", headers=admin_headers)
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("paid", resp.json()["detail"].lower())

        # ── 10. error: check-in on already-completed/refunded booking ─────────
        resp = self.client.post(f"/api/admin/bookings/{booking['id']}/check-in", headers=admin_headers)
        self.assertEqual(resp.status_code, 400, resp.text)

        # ── 11. non-admin is rejected ─────────────────────────────────────────
        resp = self.client.post(f"/api/admin/bookings/{pending_id}/mark-paid", headers=guest_headers)
        self.assertEqual(resp.status_code, 403, resp.text)

        # ── 12. admin lookup returns both room and staff bookings ─────────────
        resp = self.client.get("/api/admin/bookings", headers=admin_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        all_bookings = resp.json()
        kinds = {b["booking_kind"] for b in all_bookings}
        self.assertIn("room", kinds)
        self.assertIn("staff", kinds)

        # ── 13. audit log records admin actions ───────────────────────────────
        resp = self.client.get("/api/admin/activity?limit=50", headers=admin_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        actions = {item["action"] for item in resp.json()}
        self.assertIn("payment_marked_paid_by_admin", actions)
        self.assertIn("payment_waived_by_admin", actions)
        self.assertIn("booking_checked_in", actions)

    def test_30_week_five_six_flow(self) -> None:
        from app.config import settings
        from app.models.booking import Booking
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Webhook Room",
                description="Room used for webhook and admin tests",
                capacity=5,
                photos=[],
                hourly_rate_cents=10000,
            )
            admin_room = Room(
                name="Admin Unlimited Room",
                description="Room used to verify admins can self-book multiple times in one day",
                capacity=2,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.add(admin_room)
            db.commit()
            db.refresh(room)
            db.refresh(admin_room)
            room_id = str(room.id)
            admin_room_id = str(admin_room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "ops-user@example.com",
                "password": "Password123!",
                "full_name": "Ops User",
                "phone": "5551230000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        user_id = response.json()["id"]

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.id == user_id).first()
            user.is_admin = True
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "ops-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        pending_booking_date = datetime.now(business_timezone).date() + timedelta(days=3)
        while pending_booking_date.weekday() not in {2, 3, 4, 5}:
            pending_booking_date += timedelta(days=1)
        manual_booking_date = pending_booking_date + timedelta(days=1)
        while manual_booking_date.weekday() not in {2, 3, 4, 5}:
            manual_booking_date += timedelta(days=1)
        admin_self_booking_date = manual_booking_date + timedelta(days=1)
        while admin_self_booking_date.weekday() not in {2, 3, 4, 5}:
            admin_self_booking_date += timedelta(days=1)
        response = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year,
                    admin_self_booking_date.month,
                    admin_self_booking_date.day,
                    12,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year,
                    admin_self_booking_date.month,
                    admin_self_booking_date.day,
                    13,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "paying-user@example.com",
                "password": "Password123!",
                "full_name": "Paying User",
                "phone": "5551239999",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "paying-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "phone": "5551239999",
                "opt_in_sms": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["opt_in_sms"])

        start_time = datetime(
            pending_booking_date.year,
            pending_booking_date.month,
            pending_booking_date.day,
            12,
            0,
            tzinfo=business_timezone,
        )
        target_date = pending_booking_date

        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        pending_booking = response.json()
        self.assertEqual(pending_booking["status"], "PendingPayment")
        self.assertTrue(pending_booking["payment_intent_id"].startswith("pi_"))

        event = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": pending_booking["payment_intent_id"],
                    "metadata": {"booking_id": pending_booking["id"]},
                }
            },
        }
        payload = json.dumps(event)
        timestamp = str(int(time.time()))
        signature = hmac.new(
            settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
            f"{timestamp}.{payload}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        response = self.client.post(
            "/api/webhooks/stripe",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={timestamp},v1={signature}",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")

        response = self.client.get(f"/api/bookings/{pending_booking['id']}", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertIsNotNone(response.json()["confirmed_at"])
        paid_booking = response.json()

        response = self.client.get(f"/api/bookings/{pending_booking['id']}/receipt", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn(
            f'studio-booking-receipt-{paid_booking["booking_code"]}.pdf',
            response.headers["content-disposition"],
        )
        self.assertTrue(response.content.startswith(b"%PDF-1."))

        response = self.client.get("/api/admin/bookings?email=paying-user@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["status"], "Paid")

        response = self.client.post(
            f"/api/bookings/{pending_booking['id']}/cancel",
            headers=user_headers,
            json={"reason": "Plans changed"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Cancelled")
        self.assertEqual(response.json()["cancellation_reason"], "Plans changed")

        response = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(response.status_code, 200, response.text)
        availability = response.json()
        self.assertIn(start_time.isoformat(), availability["available_start_times"])

        refund_context = (
            patch("app.services.booking_service.create_refund", return_value="re_smoke_stripe")
            if settings.PAYMENT_BACKEND == "stripe"
            else nullcontext()
        )

        with refund_context:
            response = self.client.post(
                f"/api/admin/bookings/{pending_booking['id']}/refund",
                headers=admin_headers,
                json={"amount_cents": 5000, "reason": "Admin approved refund"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        refund = response.json()
        self.assertEqual(refund["status"], "Processed")
        self.assertEqual(refund["amount_cents"], 5000)

        response = self.client.get("/api/bookings", headers=user_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["status"], "Refunded")

        manual_start_time = datetime(
            manual_booking_date.year,
            manual_booking_date.month,
            manual_booking_date.day,
            14,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin@example.com",
                "full_name": "Walk In",
                "room_id": room_id,
                "start_time": manual_start_time.isoformat(),
                "duration_minutes": 60,
                "note": "Front desk override",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["user_email"], "walkin@example.com")
        self.assertEqual(response.json()["note"], "Front desk override")

        response = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin@example.com",
                "full_name": "Walk In",
                "room_id": room_id,
                "start_time": datetime(
                    manual_booking_date.year,
                    manual_booking_date.month,
                    manual_booking_date.day,
                    15,
                    0,
                    tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
                "note": "Same day admin override",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "Paid")
        self.assertEqual(response.json()["user_email"], "walkin@example.com")

        response = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        paid_bookings = response.json()
        self.assertGreaterEqual(
            sum(1 for booking in paid_bookings if booking["user_email"] == "walkin@example.com"),
            2,
        )
        walk_in_booking_id = next(
            booking["id"] for booking in paid_bookings if booking["user_email"] == "walkin@example.com"
        )

        response = self.client.post(
            f"/api/admin/bookings/{walk_in_booking_id}/check-in",
            headers=admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "Completed")
        self.assertIsNotNone(response.json()["checked_in_at"])

        response = self.client.get("/api/admin/bookings?status=Completed", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(booking["user_email"] == "walkin@example.com" for booking in response.json()))

        response = self.client.get("/api/admin/analytics/summary", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        analytics = response.json()
        self.assertEqual(analytics["currency"], "CAD")
        self.assertGreaterEqual(analytics["total_bookings"], 2)
        self.assertGreaterEqual(analytics["paid_bookings"], 1)
        self.assertGreaterEqual(analytics["refunded_bookings"], 1)
        self.assertGreaterEqual(analytics["gross_revenue_cents"], 10000)
        self.assertGreaterEqual(analytics["refunded_revenue_cents"], 5000)
        self.assertGreaterEqual(analytics["net_revenue_cents"], 5000)
        room_summary = next(
            summary for summary in analytics["room_summaries"] if summary["room_id"] == room_id
        )
        self.assertEqual(room_summary["total_bookings"], 3)
        self.assertGreaterEqual(room_summary["paid_bookings"], 2)
        self.assertEqual(room_summary["revenue_cents"], 3 * self._room_price(10000, 60))

        response = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        activity = response.json()
        activity_actions = [item["action"] for item in activity]
        self.assertIn("manual_booking_created", activity_actions)
        self.assertIn("refund_processed", activity_actions)
        self.assertIn("booking_checked_in", activity_actions)

        response = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        test_cases = response.json()
        self.assertTrue(any(item["id"] == "booking-service-regression-matrix" for item in test_cases))
        self.assertTrue(any("/bookings" in item["covered_paths"] for item in test_cases))

        response = self.client.post(
            "/api/admin/bookings/clear-day",
            headers=admin_headers,
            json={"date": manual_booking_date.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "day")
        self.assertEqual(response.json()["target_date"], manual_booking_date.isoformat())
        self.assertGreaterEqual(response.json()["deleted_count"], 1)

        response = self.client.get("/api/admin/bookings?email=walkin@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(booking["user_email"] == "walkin@example.com" for booking in response.json()))

        with self.SessionLocal() as db:
            from app.models.booking import Booking

            past_booking = Booking(
                user_id=None,
                room_id=UUID(room_id),
                start_time=datetime.now(timezone.utc) - timedelta(days=2),
                end_time=datetime.now(timezone.utc) - timedelta(days=2) + timedelta(hours=1),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Completed",
                booking_code="PASTCLR1",
                user_email_snapshot="past@example.com",
                user_full_name_snapshot="Past Booking",
                user_phone_snapshot="5552224444",
            )
            db.add(past_booking)
            db.commit()

        response = self.client.post("/api/admin/bookings/clear-past", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], "past")
        self.assertGreaterEqual(response.json()["deleted_count"], 1)

        response = self.client.get("/api/admin/bookings?booking_code=PASTCLR1", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

        with self.SessionLocal() as db:
            audit_count = db.query(self.AuditLog).count()
            notification_count = db.query(self.NotificationLog).count()
            refund_count = db.query(self.Refund).count()
            webhook_booking = db.query(Booking).filter(Booking.id == pending_booking["id"]).first()
            webhook_notification_types = {
                notification.type
                for notification in db.query(self.NotificationLog)
                .filter(self.NotificationLog.booking_id == pending_booking["id"])
                .all()
            }

        self.assertGreaterEqual(audit_count, 3)
        self.assertGreaterEqual(notification_count, 4)
        self.assertEqual(refund_count, 1)
        self.assertEqual(webhook_booking.status, "Refunded")
        self.assertIn("booking_confirmation_sms_worker", webhook_notification_types)
        self.assertIn("booking_cancellation_sms_worker", webhook_notification_types)
        self.assertIn("refund_processed_sms_worker", webhook_notification_types)

    def test_35_account_management_and_deleted_user_history(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Account Ops Room",
                description="Room for account management coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "accounts-admin@example.com",
                "password": "Password123!",
                "full_name": "Accounts Admin",
                "phone": "5555551000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        admin_id = response.json()["id"]

        with self.SessionLocal() as db:
            admin_user = db.query(self.User).filter(self.User.id == admin_id).first()
            admin_user.is_admin = True
            admin_user.role = "AdminManager"
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            data={"username": "accounts-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "history-user@example.com",
                "password": "Password123!",
                "full_name": "History User",
                "phone": "5555552000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "history-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        history_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=history_headers,
            json={
                "billing_address": {
                    "line1": "500 Studio Way",
                    "city": "Calgary",
                    "state": "AB",
                    "postal_code": "T2P1J9",
                    "country": "Canada",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("saved_payment_method", response.json())

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        history_account = next(
            account for account in response.json() if account["email"] == "history-user@example.com"
        )
        self.assertNotIn("saved_payment_method", history_account)
        self.assertEqual(history_account["billing_address"]["city"], "Calgary")

        business_timezone = ZoneInfo("America/Edmonton")
        start_time = self._future_time(day=5, hour=11, minute=0)
        response = self.client.post(
            "/api/bookings",
            headers=history_headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()

        response = self.client.request(
            "DELETE",
            "/api/users/me",
            headers=history_headers,
            json={"password": "WrongPassword123!"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Password is incorrect")

        response = self.client.request(
            "DELETE",
            "/api/users/me",
            headers=history_headers,
            json={"password": "Password123!"},
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get("/api/auth/me", headers=history_headers)
        self.assertEqual(response.status_code, 401, response.text)

        response = self.client.get("/api/admin/bookings?email=history-user@example.com", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(item["booking_code"] == booking["booking_code"] for item in response.json()))
        deleted_user_booking = next(
            item for item in response.json() if item["booking_code"] == booking["booking_code"]
        )
        self.assertEqual(deleted_user_booking["user_email"], "history-user@example.com")
        self.assertEqual(deleted_user_booking["user_full_name"], "History User")
        self.assertEqual(deleted_user_booking["user_phone"], "5555552000")

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(account["email"] == "history-user@example.com" for account in response.json()))

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "delete-by-admin@example.com",
                "password": "Password123!",
                "full_name": "Delete By Admin",
                "phone": "5555553000",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        removable_user_id = response.json()["id"]

        response = self.client.request(
            "DELETE",
            f"/api/admin/users/{removable_user_id}",
            headers=admin_headers,
            json={"admin_password": "WrongPassword123!"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "Admin password is incorrect")

        response = self.client.request(
            "DELETE",
            f"/api/admin/users/{removable_user_id}",
            headers=admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(response.status_code, 204, response.text)

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(account["email"] == "delete-by-admin@example.com" for account in response.json()))

    def test_36_profile_avatar_reschedule_and_review_flow(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Review Flow Room",
                description="Room for avatar, reschedule, and review coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "reviewer@example.com",
                "password": "Password123!",
                "full_name": "Review User",
                "phone": "5555554100",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        response = self.client.post(
            "/api/auth/login",
            data={"username": "reviewer@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        user_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "full_name": "Review User",
                "avatar_url": "/assets/media/avatars/example-avatar.jpg",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["avatar_url"], "/assets/media/avatars/example-avatar.jpg")

        business_timezone = ZoneInfo("America/Edmonton")
        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=20, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        booking = response.json()

        # Customers can no longer reschedule — admin-only now.
        response = self.client.post(
            f"/api/bookings/{booking['id']}/reschedule",
            headers=user_headers,
            json={
                "start_time": self._future_time(day=20, hour=12, minute=0).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.post(
            "/api/auth/signup",
            json={
                "email": "reschedule-admin-smoke@example.com",
                "password": "Password123!",
                "full_name": "Reschedule Admin",
                "phone": "5555554199",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        reschedule_admin_id = response.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == reschedule_admin_id).first()
            u.is_admin = True
            db.commit()
        response = self.client.post(
            "/api/auth/login",
            data={"username": "reschedule-admin-smoke@example.com", "password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        response = self.client.post(
            f"/api/bookings/{booking['id']}/reschedule",
            headers=admin_headers,
            json={
                "start_time": self._future_time(day=20, hour=12, minute=0).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        rescheduled_booking = response.json()
        self.assertEqual(
            datetime.fromisoformat(rescheduled_booking["start_time"].replace("Z", "+00:00")),
            self._future_time(day=20, hour=12).astimezone(timezone.utc),
        )

        with self.SessionLocal() as db:
            booking_row = db.query(self.Booking).filter(self.Booking.id == rescheduled_booking["id"]).first()
            booking_row.status = "Completed"
            booking_row.confirmed_at = datetime.now(timezone.utc)
            booking_row.checked_in_at = datetime.now(timezone.utc)
            db.commit()

        response = self.client.put(
            f"/api/bookings/{rescheduled_booking['id']}/review",
            headers=user_headers,
            json={"rating": 5, "comment": "Great room and smooth session."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rating"], 5)

        response = self.client.get(
            f"/api/bookings/{rescheduled_booking['id']}/review",
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["comment"], "Great room and smooth session.")

        response = self.client.get(f"/api/rooms/{room_id}/reviews")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["summary"]["review_count"], 1)
        self.assertEqual(response.json()["reviews"][0]["rating"], 5)

    def test_40_week_seven_eight_ops(self) -> None:
        from app.celery_app import celery_app
        from app.models.booking import Booking, BookingSlot, NotificationLog
        from app.models.room import Room
        from app.schemas.booking import BookingCreate
        from app.services.booking_service import BookingConflictError, create_booking
        from app.tasks import cleanup_expired_pending_bookings_task, dispatch_due_reminders_task

        beat_schedule = getattr(celery_app.conf, "beat_schedule", {})
        self.assertIn("dispatch-reminders-24h", beat_schedule)
        self.assertIn("dispatch-reminders-5h", beat_schedule)
        self.assertIn("dispatch-reminders-1h", beat_schedule)
        self.assertIn("cleanup-expired-pending-bookings", beat_schedule)

        with self.SessionLocal() as db:
            room = Room(
                name="Ops Room",
                description="Room used for Week 7 and 8 tests",
                capacity=6,
                photos=[],
                hourly_rate_cents=10000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = room.id

        for email in ("ops-1@example.com", "ops-2@example.com", "ops-3@example.com"):
            response = self.client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "Password123!",
                    "full_name": email.split("@")[0],
                    "phone": "5557778888",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)

        with self.SessionLocal() as db:
            users = {
                user.email: user
                for user in db.query(self.User)
                .filter(self.User.email.in_(["ops-1@example.com", "ops-2@example.com", "ops-3@example.com"]))
                .all()
            }
            user_one_id = users["ops-1@example.com"].id
            user_two_id = users["ops-2@example.com"].id
            reminder_user = users["ops-3@example.com"]
            reminder_user.opt_in_sms = True

            reminder_booking = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(hours=24),
                end_time=datetime.now(timezone.utc) + timedelta(hours=25),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code="REMIND24",
                payment_intent_id="pi_stub_reminder",
                confirmed_at=datetime.now(timezone.utc),
            )
            db.add(reminder_booking)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=reminder_booking.id,
                        room_id=room_id,
                        slot_start=reminder_booking.start_time,
                    ),
                    BookingSlot(
                        booking_id=reminder_booking.id,
                        room_id=room_id,
                        slot_start=reminder_booking.start_time + timedelta(minutes=30),
                    ),
                ]
            )

            reminder_booking_5h = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(hours=5),
                end_time=datetime.now(timezone.utc) + timedelta(hours=6),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="Paid",
                booking_code="REMIND05",
                payment_intent_id="pi_stub_reminder_5h",
                confirmed_at=datetime.now(timezone.utc),
            )
            db.add(reminder_booking_5h)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=reminder_booking_5h.id,
                        room_id=room_id,
                        slot_start=reminder_booking_5h.start_time,
                    ),
                    BookingSlot(
                        booking_id=reminder_booking_5h.id,
                        room_id=room_id,
                        slot_start=reminder_booking_5h.start_time + timedelta(minutes=30),
                    ),
                ]
            )

            expired_booking = Booking(
                user_id=reminder_user.id,
                room_id=room_id,
                start_time=datetime.now(timezone.utc) + timedelta(days=2),
                end_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
                duration_minutes=60,
                price_cents=5000,
                currency="CAD",
                status="PendingPayment",
                booking_code="EXPIRED24",
                payment_intent_id="pi_stub_expired",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
            db.add(expired_booking)
            db.flush()
            db.add_all(
                [
                    BookingSlot(
                        booking_id=expired_booking.id,
                        room_id=room_id,
                        slot_start=expired_booking.start_time,
                    ),
                    BookingSlot(
                        booking_id=expired_booking.id,
                        room_id=room_id,
                        slot_start=expired_booking.start_time + timedelta(minutes=30),
                    ),
                ]
            )
            expired_booking_id = expired_booking.id
            db.commit()

        reminder_result = dispatch_due_reminders_task(24)
        self.assertEqual(reminder_result["sent"], 2)
        reminder_result_5h = dispatch_due_reminders_task(5)
        self.assertEqual(reminder_result_5h["sent"], 2)

        cleanup_result = cleanup_expired_pending_bookings_task(5)
        self.assertEqual(cleanup_result["cleaned"], 1)

        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("studio_http_requests_total", response.text)
        self.assertIn("studio_http_request_duration_seconds_total", response.text)
        self.assertIn('studio_task_runs_total{task="dispatch_due_reminders"}', response.text)
        self.assertIn('studio_task_runs_total{task="cleanup_expired_pending_bookings"}', response.text)
        self.assertIn('studio_task_items_total{task="dispatch_due_reminders",result="sent"}', response.text)
        self.assertIn('studio_task_items_total{task="cleanup_expired_pending_bookings",result="cleaned"}', response.text)

        with self.SessionLocal() as db:
            reminder_notifications = (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.type.in_(
                        (
                            "reminder_24h_email",
                            "reminder_24h_sms",
                            "reminder_5h_email",
                            "reminder_5h_sms",
                        )
                    )
                )
                .all()
            )
            expired_booking = db.query(Booking).filter(Booking.id == expired_booking_id).first()
            expired_slots_remaining = (
                db.query(BookingSlot)
                .filter(BookingSlot.booking_id == expired_booking_id)
                .count()
            )

        reminder_notification_types = {notification.type for notification in reminder_notifications}
        self.assertEqual(len(reminder_notifications), 4)
        self.assertIn("reminder_24h_email", reminder_notification_types)
        self.assertIn("reminder_24h_sms", reminder_notification_types)
        self.assertIn("reminder_5h_email", reminder_notification_types)
        self.assertIn("reminder_5h_sms", reminder_notification_types)
        self.assertEqual(expired_booking.status, "Cancelled")
        self.assertEqual(expired_booking.cancellation_reason, "Payment window expired after 5 minutes")
        self.assertEqual(expired_slots_remaining, 0)

        start_time = self._future_time(day=5, hour=10, minute=0)
        barrier = Barrier(3)

        def attempt_booking(user_id):
            barrier.wait()
            db = self.SessionLocal()
            try:
                user = db.query(self.User).filter(self.User.id == user_id).first()
                booking = create_booking(
                    db,
                    user,
                    BookingCreate(
                        room_id=room_id,
                        start_time=start_time,
                        duration_minutes=60,
                    ),
                )
                return ("success", str(booking.id))
            except BookingConflictError:
                return ("conflict", None)
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_one = executor.submit(attempt_booking, user_one_id)
            future_two = executor.submit(attempt_booking, user_two_id)
            barrier.wait()
            outcomes = [future_one.result(), future_two.result()]

        statuses = sorted(status for status, _ in outcomes)
        self.assertEqual(statuses, ["conflict", "success"])

    def test_41_admin_launch_readiness_access_workflows_and_ui_contract(self) -> None:
        def create_user(email: str, full_name: str, phone: str, *, is_admin: bool = False, role: str = "Admin"):
            response = self.client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "Password123!",
                    "full_name": full_name,
                    "phone": phone,
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            user_id = response.json()["id"]
            if is_admin:
                with self.SessionLocal() as db:
                    user = db.query(self.User).filter(self.User.id == user_id).first()
                    user.is_admin = True
                    user.role = role
                    db.commit()

            response = self.client.post(
                "/api/auth/login",
                data={"username": email, "password": "Password123!"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            return {"Authorization": f"Bearer {response.json()['access_token']}"}, user_id

        admin_headers, admin_id = create_user(
            "launch-admin@example.com",
            "Launch Admin",
            "5551000000",
            is_admin=True,
            role="AdminManager",
        )
        regular_admin_headers, _ = create_user(
            "launch-regular-admin@example.com",
            "Launch Regular Admin",
            "5551000003",
            is_admin=True,
        )
        user_headers, _ = create_user("launch-user@example.com", "Launch User", "5551000001")
        outsider_headers, outsider_id = create_user("launch-outsider@example.com", "Launch Outsider", "5551000002")

        for path in (
            "/api/admin/bookings",
            "/api/admin/analytics/summary",
            "/api/admin/staff",
            "/api/admin/users",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            response = self.client.get(path, headers=user_headers)
            self.assertEqual(response.status_code, 403, path)

        response = self.client.get("/api/rooms?include_inactive=true", headers=user_headers)
        self.assertEqual(response.status_code, 403, response.text)

        booking_room_payload = {
            "name": "Launch Booking Room",
            "description": "Room used for admin launch readiness checks",
            "capacity": 4,
            "photos": [],
            "hourly_rate_cents": 10000,
            "max_booking_duration_minutes": 300,
        }
        response = self.client.post("/api/rooms", headers=user_headers, json=booking_room_payload)
        self.assertEqual(response.status_code, 403, response.text)
        response = self.client.post("/api/rooms", headers=admin_headers, json=booking_room_payload)
        self.assertEqual(response.status_code, 201, response.text)
        booking_room_id = response.json()["id"]

        response = self.client.put(
            f"/api/admin/rooms/{booking_room_id}",
            headers=admin_headers,
            json={"name": "Launch Booking Room Updated", "capacity": 6},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Launch Booking Room Updated")
        self.assertEqual(response.json()["capacity"], 6)

        staff_payload = {
            "name": "Launch Service Engineer",
            "description": "Technical and creative support for launch checks",
            "skills": ["Podcast", "Sound"],
            "talents": ["Engineering"],
            "service_types": ["Audio"],
            "add_on_price_cents": 2500,
            "booking_rate_cents": 5000,
            "booking_enabled": True,
            "active": True,
        }
        response = self.client.post("/api/admin/staff", headers=user_headers, json=staff_payload)
        self.assertEqual(response.status_code, 403, response.text)
        response = self.client.post("/api/admin/staff", headers=admin_headers, json=staff_payload)
        self.assertEqual(response.status_code, 201, response.text)
        staff_id = response.json()["id"]
        response = self.client.get("/api/admin/staff", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(profile["id"] == staff_id for profile in response.json()))
        response = self.client.put(
            f"/api/admin/staff/{staff_id}",
            headers=admin_headers,
            json={"booking_enabled": False, "skills": ["Podcast", "Mixing"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["booking_enabled"])
        self.assertIn("Mixing", response.json()["skills"])

        manage_room_payload = {
            "name": "Launch Archive Room",
            "description": "Room used to verify destructive room actions",
            "capacity": 2,
            "photos": [],
            "hourly_rate_cents": 5000,
            "max_booking_duration_minutes": 300,
        }
        response = self.client.post("/api/rooms", headers=admin_headers, json=manage_room_payload)
        self.assertEqual(response.status_code, 201, response.text)
        manage_room_id = response.json()["id"]
        response = self.client.delete(f"/api/rooms/{manage_room_id}", headers=user_headers)
        self.assertEqual(response.status_code, 403, response.text)
        response = self.client.delete(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)
        response = self.client.get(f"/api/rooms/{manage_room_id}")
        self.assertEqual(response.status_code, 404, response.text)
        response = self.client.get(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["active"])
        response = self.client.post(f"/api/rooms/{manage_room_id}/restore", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["active"])
        response = self.client.delete(f"/api/rooms/{manage_room_id}/permanent", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)
        response = self.client.get(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 404, response.text)

        business_timezone = ZoneInfo("America/Edmonton")
        booking_date = datetime.now(business_timezone).date() + timedelta(days=8)
        booking_start = datetime(
            booking_date.year,
            booking_date.month,
            booking_date.day,
            13,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": booking_room_id,
                "start_time": booking_start.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        user_booking = response.json()

        response = self.client.get(f"/api/bookings/{user_booking['id']}", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], user_booking["id"])
        response = self.client.get(f"/api/bookings/{user_booking['id']}", headers=outsider_headers)
        self.assertEqual(response.status_code, 404, response.text)

        manual_start = datetime(
            booking_date.year,
            booking_date.month,
            booking_date.day,
            12,
            0,
            tzinfo=business_timezone,
        )
        response = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin-launch@example.com",
                "full_name": "Walk In Launch",
                "room_id": booking_room_id,
                "start_time": manual_start.isoformat(),
                "duration_minutes": 60,
                "note": "Launch readiness manual booking",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        manual_booking = response.json()
        self.assertEqual(manual_booking["status"], "Paid")
        self.assertEqual(manual_booking["user_email"], "walkin-launch@example.com")

        response = self.client.get("/api/admin/bookings", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        admin_bookings = response.json()
        self.assertEqual(len(admin_bookings), 2)
        self.assertTrue(any(booking["id"] == user_booking["id"] for booking in admin_bookings))
        self.assertTrue(any(booking["id"] == manual_booking["id"] for booking in admin_bookings))

        response = self.client.get("/api/admin/analytics/summary", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        analytics = response.json()
        self.assertEqual(analytics["total_bookings"], 2)
        self.assertEqual(analytics["paid_bookings"], 1)
        self.assertEqual(analytics["net_revenue_cents"], self._room_price(10000, 60))
        self.assertEqual(analytics["refunded_revenue_cents"], 0)
        self.assertGreaterEqual(analytics["active_rooms"], 1)

        response = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        users = response.json()
        self.assertTrue(any(user["id"] == admin_id and user["is_admin"] for user in users))
        self.assertTrue(any(user["id"] == admin_id and user["role"] == "AdminManager" for user in users))
        self.assertTrue(any(user["email"] == "launch-user@example.com" for user in users))

        response = self.client.request(
            "DELETE",
            f"/api/admin/users/{outsider_id}",
            headers=regular_admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.request(
            "DELETE",
            f"/api/admin/users/{admin_id}",
            headers=regular_admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=regular_admin_headers,
            json={"role": "Admin", "admin_password": "Password123!"},
        )
        self.assertEqual(response.status_code, 403, response.text)

        response = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=admin_headers,
            json={"role": "Admin", "admin_password": "WrongPassword123!"},
        )
        self.assertEqual(response.status_code, 400, response.text)

        response = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=admin_headers,
            json={"role": "Admin", "admin_password": "Password123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["role"], "Admin")
        self.assertTrue(response.json()["is_admin"])

        response = self.client.delete(f"/api/admin/staff/{staff_id}", headers=admin_headers)
        self.assertEqual(response.status_code, 204, response.text)
        response = self.client.get("/api/admin/staff", headers=admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(any(profile["id"] == staff_id for profile in response.json()))

        admin_page = self.client.get("/admin")
        self.assertEqual(admin_page.status_code, 200, admin_page.text)
        self.assertIn("Dashboard", admin_page.text)
        self.assertIn("admin-dashboard-metrics", admin_page.text)
        self.assertIn("admin-panel-bookings", admin_page.text)
        self.assertIn("admin-panel-rooms", admin_page.text)
        self.assertIn("admin-panel-staff", admin_page.text)
        self.assertIn("admin-panel-roles", admin_page.text)
        self.assertIn('data-admin-create-room="true"', admin_page.text)
        self.assertIn('class="header-brand-block"', admin_page.text)
        self.assertIn("/assets/styles/app.css?v=", admin_page.text)
        self.assertNotIn("[object Object]", admin_page.text)
        self.assertNotIn("TODO", admin_page.text)

        admin_js = self.client.get("/assets/js/views/admin.js")
        self.assertEqual(admin_js.status_code, 200, admin_js.text)
        self.assertIn("let adminRoomEditorOpen = false;", admin_js.text)
        self.assertIn("adminRoomEditorOpen && activeAdminTab === \"rooms\"", admin_js.text)
        self.assertIn("renderAdminDashboardMetrics(currentState)", admin_js.text)
        self.assertIn("analytics ? analytics.total_bookings : \"Loading\"", admin_js.text)
        self.assertIn("analytics ? formatMoney(analytics.net_revenue_cents, currency) : \"Loading\"", admin_js.text)
        self.assertNotIn("currentState.adminAnalytics?.net_revenue_cents ??", admin_js.text)
        self.assertIn("Mark paid", admin_js.text)
        self.assertIn("Refund", admin_js.text)
        self.assertIn("const updatedAccount = await api.adminUpdateUserRole", admin_js.text)
        self.assertIn("...updatedAccount", admin_js.text)
        self.assertIn("Process a ${amountLabel} refund? This changes payment records.", admin_js.text)
        self.assertIn("window.confirm(\"Skip Stripe and mark this booking free?\")", admin_js.text)
        self.assertIn("window.confirm(\"Mark this booking paid manually?\")", admin_js.text)
        self.assertIn("window.confirm(`Delete ${profileName}? This will also remove the profile from any rooms.`)", admin_js.text)

        main_js = self.client.get("/assets/js/main.js")
        self.assertEqual(main_js.status_code, 200, main_js.text)
        self.assertIn("api.getAdminAnalyticsSummary()", main_js.text)

        rooms_js = self.client.get("/assets/js/views/rooms.js")
        self.assertEqual(rooms_js.status_code, 200, rooms_js.text)
        self.assertIn('} else if (!isAdminPage()) {', rooms_js.text)
        self.assertNotIn('elements.roomForm.classList.toggle("hidden", !canManageRooms);', rooms_js.text)

        app_css = self.client.get("/assets/styles/app.css")
        self.assertEqual(app_css.status_code, 200, app_css.text)
        self.assertIn('body[data-page="admin"] #room-form {', app_css.text)
        self.assertIn('body[data-page="admin"].admin-room-modal-active #room-form:not(.hidden)', app_css.text)
        self.assertIn("background: linear-gradient(135deg, var(--brand-red), #a70f16);", app_css.text)

        with self.SessionLocal() as db:
            audit_actions = {item.action for item in db.query(self.AuditLog).all()}

        self.assertIn("room_created", audit_actions)
        self.assertIn("room_updated", audit_actions)
        self.assertIn("room_archived", audit_actions)
        self.assertIn("room_restored", audit_actions)
        self.assertIn("room_permanently_deleted", audit_actions)
        self.assertIn("staff_profile_created", audit_actions)
        self.assertIn("staff_profile_updated", audit_actions)
        self.assertIn("staff_profile_deleted", audit_actions)
        self.assertIn("manual_booking_created", audit_actions)


if __name__ == "__main__":
    unittest.main()
