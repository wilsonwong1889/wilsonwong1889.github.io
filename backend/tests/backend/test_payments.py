"""
Backend tests — payment flows.

Covers: pending payment window expiry, Stripe webhook handling, booking
cancellation, refund, manual booking, analytics, clear-day/clear-past ops,
notification and audit assertions.
"""
import hashlib
import hmac
import json
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from tests.base import BaseAppTest


class PaymentTest(BaseAppTest):

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

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "expiry@example.com",
                "password": "Password123!",
                "full_name": "Expiry User",
                "phone": "5551112222",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "expiry@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        user_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertIsNotNone(booking["payment_expires_at"])

        with self.SessionLocal() as db:
            db_booking = db.query(Booking).filter(Booking.id == UUID(booking["id"])).first()
            db_booking.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
            db.commit()

        resp = self.client.get(f"/api/bookings/{booking['id']}", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Cancelled")
        self.assertEqual(resp.json()["cancellation_reason"], "Payment window expired after 5 minutes")

        resp = self.client.post(
            f"/api/bookings/{booking['id']}/payment-session",
            headers=user_headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Payment is only available for pending bookings")

        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(start_time.isoformat(), resp.json()["available_start_times"])

    def test_30_stripe_webhook_refund_manual_booking_analytics(self) -> None:
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

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "ops-user@example.com",
                "password": "Password123!",
                "full_name": "Ops User",
                "phone": "5551230000",
            },
        )
        self.assertEqual(resp.status_code, 201)
        user_id = resp.json()["id"]

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.id == user_id).first()
            user.is_admin = True
            db.commit()

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "ops-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

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

        resp = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year, admin_self_booking_date.month,
                    admin_self_booking_date.day, 12, 0, tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": admin_room_id,
                "start_time": datetime(
                    admin_self_booking_date.year, admin_self_booking_date.month,
                    admin_self_booking_date.day, 13, 0, tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "paying-user@example.com",
                "password": "Password123!",
                "full_name": "Paying User",
                "phone": "5551239999",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "paying-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        user_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={"phone": "5551239999", "opt_in_sms": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["opt_in_sms"])

        start_time = datetime(
            pending_booking_date.year, pending_booking_date.month, pending_booking_date.day,
            12, 0, tzinfo=business_timezone,
        )
        target_date = pending_booking_date

        resp = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        pending_booking = resp.json()
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
        resp = self.client.post(
            "/api/webhooks/stripe",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={timestamp},v1={signature}",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")

        resp = self.client.get(f"/api/bookings/{pending_booking['id']}", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertIsNotNone(resp.json()["confirmed_at"])
        paid_booking = resp.json()

        resp = self.client.get(f"/api/bookings/{pending_booking['id']}/receipt", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn(
            f'studio-booking-receipt-{paid_booking["booking_code"]}.pdf',
            resp.headers["content-disposition"],
        )
        self.assertTrue(resp.content.startswith(b"%PDF-1."))

        resp = self.client.get(
            "/api/admin/bookings?email=paying-user@example.com", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]["status"], "Paid")

        resp = self.client.post(
            f"/api/bookings/{pending_booking['id']}/cancel",
            headers=user_headers,
            json={"reason": "Plans changed"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Cancelled")
        self.assertEqual(resp.json()["cancellation_reason"], "Plans changed")

        resp = self.client.get(f"/api/rooms/{room_id}/availability?date={target_date.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(start_time.isoformat(), resp.json()["available_start_times"])

        refund_context = (
            __import__("unittest.mock", fromlist=["patch"]).patch(
                "app.services.booking_service.create_refund", return_value="re_smoke_stripe"
            )
            if settings.PAYMENT_BACKEND == "stripe"
            else nullcontext()
        )

        with refund_context:
            resp = self.client.post(
                f"/api/admin/bookings/{pending_booking['id']}/refund",
                headers=admin_headers,
                json={"amount_cents": 5000, "reason": "Admin approved refund"},
            )
        self.assertEqual(resp.status_code, 200)
        refund = resp.json()
        self.assertEqual(refund["status"], "Processed")
        self.assertEqual(refund["amount_cents"], 5000)

        resp = self.client.get("/api/bookings", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["status"], "Refunded")

        manual_start_time = datetime(
            manual_booking_date.year, manual_booking_date.month, manual_booking_date.day,
            14, 0, tzinfo=business_timezone,
        )
        resp = self.client.post(
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
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertEqual(resp.json()["user_email"], "walkin@example.com")
        self.assertEqual(resp.json()["note"], "Front desk override")

        resp = self.client.post(
            "/api/admin/bookings/manual",
            headers=admin_headers,
            json={
                "user_email": "walkin@example.com",
                "full_name": "Walk In",
                "room_id": room_id,
                "start_time": datetime(
                    manual_booking_date.year, manual_booking_date.month, manual_booking_date.day,
                    15, 0, tzinfo=business_timezone,
                ).isoformat(),
                "duration_minutes": 60,
                "note": "Same day admin override",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "Paid")

        resp = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        paid_bookings = resp.json()
        self.assertGreaterEqual(
            sum(1 for b in paid_bookings if b["user_email"] == "walkin@example.com"), 2
        )
        walk_in_booking_id = next(
            b["id"] for b in paid_bookings if b["user_email"] == "walkin@example.com"
        )

        resp = self.client.post(
            f"/api/admin/bookings/{walk_in_booking_id}/check-in", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Completed")
        self.assertIsNotNone(resp.json()["checked_in_at"])

        resp = self.client.get("/api/admin/bookings?status=Completed", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(b["user_email"] == "walkin@example.com" for b in resp.json()))

        resp = self.client.get("/api/admin/analytics/summary", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        analytics = resp.json()
        self.assertEqual(analytics["currency"], "CAD")
        self.assertGreaterEqual(analytics["total_bookings"], 2)
        self.assertGreaterEqual(analytics["paid_bookings"], 1)
        self.assertGreaterEqual(analytics["refunded_bookings"], 1)
        self.assertGreaterEqual(analytics["gross_revenue_cents"], 10000)
        self.assertGreaterEqual(analytics["refunded_revenue_cents"], 5000)
        self.assertGreaterEqual(analytics["net_revenue_cents"], 5000)
        room_summary = next(s for s in analytics["room_summaries"] if s["room_id"] == room_id)
        self.assertEqual(room_summary["total_bookings"], 3)
        self.assertGreaterEqual(room_summary["paid_bookings"], 2)
        self.assertEqual(room_summary["revenue_cents"], 3 * self._room_price(10000, 60))

        resp = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        activity_actions = [item["action"] for item in resp.json()]
        self.assertIn("manual_booking_created", activity_actions)
        self.assertIn("refund_processed", activity_actions)
        self.assertIn("booking_checked_in", activity_actions)

        resp = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        test_cases = resp.json()
        self.assertTrue(any(item["id"] == "booking-service-regression-matrix" for item in test_cases))
        self.assertTrue(any("/bookings" in item["covered_paths"] for item in test_cases))

        resp = self.client.post(
            "/api/admin/bookings/clear-day",
            headers=admin_headers,
            json={"date": manual_booking_date.isoformat()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scope"], "day")
        self.assertEqual(resp.json()["target_date"], manual_booking_date.isoformat())
        self.assertGreaterEqual(resp.json()["deleted_count"], 1)

        resp = self.client.get("/api/admin/bookings?email=walkin@example.com", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(b["user_email"] == "walkin@example.com" for b in resp.json()))

        with self.SessionLocal() as db:
            from app.models.booking import Booking as BookingModel

            past_booking = BookingModel(
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

        resp = self.client.post("/api/admin/bookings/clear-past", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scope"], "past")
        self.assertGreaterEqual(resp.json()["deleted_count"], 1)

        resp = self.client.get(
            "/api/admin/bookings?booking_code=PASTCLR1", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

        with self.SessionLocal() as db:
            from app.models.booking import Booking as BookingModel2

            audit_count = db.query(self.AuditLog).count()
            notification_count = db.query(self.NotificationLog).count()
            refund_count = db.query(self.Refund).count()
            webhook_booking = db.query(BookingModel2).filter(
                BookingModel2.id == pending_booking["id"]
            ).first()
            webhook_notification_types = {
                n.type
                for n in db.query(self.NotificationLog)
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
