import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from uuid import UUID
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text


class BookingPaymentE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_database_url = os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres",
        )
        cls.test_database_name = f"studio_e2e_{uuid4().hex[:8]}"
        cls.test_database_url = os.environ.get(
            "TEST_DATABASE_URL",
            f"postgresql://postgres:password@localhost:5432/{cls.test_database_name}",
        )
        cls._create_database()

        os.environ["DATABASE_URL"] = cls.test_database_url
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "e2e-test-secret")
        os.environ["PAYMENT_BACKEND"] = "stub"

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                sys.modules.pop(module_name)

        from app.database import Base, SessionLocal, engine
        from app.main import app
        from app.models.booking import Booking, NotificationLog
        from app.models.room import Room
        from app.services.seed_service import ensure_admin_user

        cls.Base = Base
        cls.SessionLocal = SessionLocal
        cls.engine = engine
        cls.Booking = Booking
        cls.NotificationLog = NotificationLog
        cls.Room = Room
        cls.ensure_admin_user = staticmethod(ensure_admin_user)

        with cls.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        cls.Base.metadata.create_all(bind=cls.engine)

        from fastapi.testclient import TestClient

        cls.client = TestClient(app)

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

    def _signup_and_login(self, email: str, password: str) -> dict:
        signup = self.client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "full_name": email.split("@")[0],
                "phone": "5551111111",
            },
        )
        self.assertEqual(signup.status_code, 201, signup.text)

        login = self.client.post(
            "/api/auth/login",
            data={"username": email, "password": password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _future_time(self, *, days: int, hour: int) -> datetime:
        business_timezone = ZoneInfo("America/Edmonton")
        base = datetime.now(business_timezone).date() + timedelta(days=30)
        days_until_wed = (2 - base.weekday()) % 7
        wednesday = base + timedelta(days=days_until_wed)
        week_offset = (days - 1) // 4
        day_in_week = (days - 1) % 4
        target_date = wednesday + timedelta(weeks=week_offset, days=day_in_week)
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            0,
            tzinfo=business_timezone,
        )

    def _sign_webhook(self, event: dict) -> tuple[str, dict]:
        from app.config import settings

        payload = json.dumps(event)
        timestamp = str(int(time.time()))
        signature = hmac.new(
            settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
            f"{timestamp}.{payload}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return payload, {
            "Content-Type": "application/json",
            "Stripe-Signature": f"t={timestamp},v1={signature}",
        }

    def test_10_booking_payment_confirmation_e2e(self) -> None:
        with self.SessionLocal() as db:
            room = self.Room(
                name="E2E Room",
                description="Room for end-to-end payment confirmation",
                capacity=4,
                photos=[],
                staff_roles=[
                    {
                        "id": "sound-engineer",
                        "name": "Sound Engineer",
                        "description": "Tracks and balances the live session.",
                        "add_on_price_cents": 3500,
                    }
                ],
                hourly_rate_cents=10000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        headers = self._signup_and_login("e2e-user@example.com", "Password123!")
        start_time = self._future_time(days=20, hour=12)
        rooms_response = self.client.get("/api/rooms")
        self.assertEqual(rooms_response.status_code, 200, rooms_response.text)
        booking_room = next(room for room in rooms_response.json() if room["id"] == room_id)
        self.assertEqual(len(booking_room["staff_roles"]), 1)
        self.assertEqual(booking_room["staff_roles"][0]["name"], "Sound Engineer")

        availability_response = self.client.get(
            f"/api/rooms/{room_id}/availability?date={start_time.date().isoformat()}"
        )
        self.assertEqual(availability_response.status_code, 200, availability_response.text)
        availability = availability_response.json()
        self.assertEqual(availability["timezone"], "America/Edmonton")
        self.assertIn(start_time.isoformat(), availability["available_start_times"])
        self.assertEqual(availability["max_duration_minutes_by_start"][start_time.isoformat()], 300)

        profile_response = self.client.put(
            "/api/users/me",
            headers=headers,
            json={
                "phone": "5551111111",
                "opt_in_sms": True,
            },
        )
        self.assertEqual(profile_response.status_code, 200, profile_response.text)

        booking_response = self.client.post(
            "/api/bookings",
            headers=headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
                "staff_assignments": ["sound-engineer"],
            },
        )
        self.assertEqual(booking_response.status_code, 201, booking_response.text)
        booking = booking_response.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], 14175)
        self.assertEqual(len(booking["staff_assignments"]), 1)
        self.assertEqual(booking["staff_assignments"][0]["name"], "Sound Engineer")
        self.assertIsNotNone(booking["payment_expires_at"])
        self.assertGreater(booking["payment_seconds_remaining"], 0)
        self.assertLessEqual(booking["payment_seconds_remaining"], 300)

        payment_session_response = self.client.post(
            f"/api/bookings/{booking['id']}/payment-session",
            headers=headers,
        )
        self.assertEqual(payment_session_response.status_code, 200, payment_session_response.text)
        payment_session = payment_session_response.json()
        self.assertEqual(payment_session["booking_id"], booking["id"])
        self.assertEqual(payment_session["payment_intent_id"], booking["payment_intent_id"])
        self.assertTrue(payment_session["payment_client_secret"].startswith("pi_client_secret_stub_"))
        self.assertEqual(payment_session["payment_backend"], "stub")
        self.assertIsNotNone(payment_session["payment_expires_at"])

        event = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": booking["payment_intent_id"],
                    "metadata": {"booking_id": booking["id"]},
                }
            },
        }
        payload, webhook_headers = self._sign_webhook(event)
        webhook_response = self.client.post(
            "/api/webhooks/stripe",
            data=payload,
            headers=webhook_headers,
        )
        self.assertEqual(webhook_response.status_code, 200, webhook_response.text)

        booking_detail = self.client.get(f"/api/bookings/{booking['id']}", headers=headers)
        self.assertEqual(booking_detail.status_code, 200, booking_detail.text)
        self.assertEqual(booking_detail.json()["status"], "Paid")
        self.assertIsNotNone(booking_detail.json()["confirmed_at"])

        with self.SessionLocal() as db:
            signup_notifications = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.user_id.isnot(None))
                .filter(self.NotificationLog.booking_id.is_(None))
                .all()
            )
            notifications = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.booking_id == UUID(booking["id"]))
                .all()
            )
        signup_notification_types = {notification.type for notification in signup_notifications}
        notification_types = {notification.type for notification in notifications}
        self.assertIn("account_created", signup_notification_types)
        self.assertIn("account_created_email_worker", signup_notification_types)
        self.assertIn("account_created_sms_worker", signup_notification_types)
        self.assertIn("booking_created", notification_types)
        self.assertIn("booking_created_email_worker", notification_types)
        self.assertIn("booking_created_sms_worker", notification_types)
        self.assertIn("booking_confirmation_email", notification_types)
        self.assertIn("booking_confirmation_email_worker", notification_types)
        self.assertIn("booking_confirmation_sms_worker", notification_types)

    def test_20_booking_payment_failure_e2e(self) -> None:
        with self.SessionLocal() as db:
            room = self.Room(
                name="E2E Failure Room",
                description="Room for end-to-end payment failure",
                capacity=3,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        headers = self._signup_and_login("e2e-failure@example.com", "Password123!")
        start_time = self._future_time(days=21, hour=13)

        booking_response = self.client.post(
            "/api/bookings",
            headers=headers,
            json={
                "room_id": room_id,
                "start_time": start_time.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(booking_response.status_code, 201, booking_response.text)
        booking = booking_response.json()

        event = {
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": booking["payment_intent_id"],
                    "metadata": {"booking_id": booking["id"]},
                }
            },
        }
        payload, webhook_headers = self._sign_webhook(event)
        webhook_response = self.client.post(
            "/api/webhooks/stripe",
            data=payload,
            headers=webhook_headers,
        )
        self.assertEqual(webhook_response.status_code, 200, webhook_response.text)

        booking_detail = self.client.get(f"/api/bookings/{booking['id']}", headers=headers)
        self.assertEqual(booking_detail.status_code, 200, booking_detail.text)
        self.assertEqual(booking_detail.json()["status"], "Cancelled")
        self.assertEqual(booking_detail.json()["cancellation_reason"], "Payment failed")


if __name__ == "__main__":
    unittest.main()
