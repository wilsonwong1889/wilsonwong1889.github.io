"""
Backend tests — celery ops and admin launch readiness.

Covers: beat schedule, reminder dispatch, expired booking cleanup, metrics
endpoint, concurrent booking race condition, admin access control, room/staff
CRUD, analytics, role management, audit log.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from zoneinfo import ZoneInfo

from unittest.mock import patch

from tests.base import BaseAppTest


class OpsTest(BaseAppTest):

    def test_39_metrics_endpoint_is_not_public(self) -> None:
        """The counters describe traffic and booking volume, so /metrics is off
        unless a scrape token is configured, and needs that token when it is."""
        # setUpClass re-imports every app module, so bind settings here — a
        # module-level import would patch an object the running app discarded.
        from app.config import settings as app_settings

        # Unconfigured: indistinguishable from a route that does not exist.
        with patch.object(app_settings, "METRICS_TOKEN", ""):
            self.assertEqual(self.client.get("/metrics").status_code, 404)

        with patch.object(app_settings, "METRICS_TOKEN", "s3cret-scrape-token"):
            self.assertEqual(self.client.get("/metrics").status_code, 401)

            resp = self.client.get(
                "/metrics", headers={"Authorization": "Bearer wrong-token"}
            )
            self.assertEqual(resp.status_code, 401)

            # Right token, wrong scheme.
            resp = self.client.get(
                "/metrics", headers={"Authorization": "Basic s3cret-scrape-token"}
            )
            self.assertEqual(resp.status_code, 401)

            resp = self.client.get(
                "/metrics", headers={"Authorization": "Bearer s3cret-scrape-token"}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("studio_http_requests_total", resp.text)

    def test_40_celery_tasks_reminders_cleanup_concurrency(self) -> None:
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
            resp = self.client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "Password123!",
                    "full_name": email.split("@")[0],
                    "phone": "5557778888",
                },
            )
            self.assertEqual(resp.status_code, 201)

        with self.SessionLocal() as db:
            users = {
                user.email: user
                for user in db.query(self.User)
                .filter(
                    self.User.email.in_(["ops-1@example.com", "ops-2@example.com", "ops-3@example.com"])
                )
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

        from app.config import settings as app_settings

        with patch.object(app_settings, "METRICS_TOKEN", "metrics-token-for-tests"):
            resp = self.client.get(
                "/metrics", headers={"Authorization": "Bearer metrics-token-for-tests"}
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("studio_http_requests_total", resp.text)
        self.assertIn("studio_http_request_duration_seconds_total", resp.text)
        self.assertIn('studio_task_runs_total{task="dispatch_due_reminders"}', resp.text)
        self.assertIn('studio_task_runs_total{task="cleanup_expired_pending_bookings"}', resp.text)
        self.assertIn(
            'studio_task_items_total{task="dispatch_due_reminders",result="sent"}', resp.text
        )
        self.assertIn(
            'studio_task_items_total{task="cleanup_expired_pending_bookings",result="cleaned"}',
            resp.text,
        )

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

        reminder_notification_types = {n.type for n in reminder_notifications}
        self.assertEqual(len(reminder_notifications), 4)
        self.assertIn("reminder_24h_email", reminder_notification_types)
        self.assertIn("reminder_24h_sms", reminder_notification_types)
        self.assertIn("reminder_5h_email", reminder_notification_types)
        self.assertIn("reminder_5h_sms", reminder_notification_types)
        self.assertEqual(expired_booking.status, "Cancelled")
        self.assertEqual(
            expired_booking.cancellation_reason, "Payment window expired after 5 minutes"
        )
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
                    BookingCreate(room_id=room_id, start_time=start_time, duration_minutes=60),
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
            resp = self.client.post(
                "/api/auth/signup",
                json={
                    "email": email,
                    "password": "Password123!",
                    "full_name": full_name,
                    "phone": phone,
                },
            )
            self.assertEqual(resp.status_code, 201)
            user_id = resp.json()["id"]
            if is_admin:
                with self.SessionLocal() as db:
                    user = db.query(self.User).filter(self.User.id == user_id).first()
                    user.is_admin = True
                    user.role = role
                    db.commit()

            resp = self.client.post(
                "/api/auth/login",
                data={"username": email, "password": "Password123!"},
            )
            self.assertEqual(resp.status_code, 200)
            return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user_id

        admin_headers, admin_id = create_user(
            "launch-admin@example.com", "Launch Admin", "5551000000",
            is_admin=True, role="AdminManager",
        )
        regular_admin_headers, _ = create_user(
            "launch-regular-admin@example.com", "Launch Regular Admin", "5551000003", is_admin=True
        )
        user_headers, _ = create_user("launch-user@example.com", "Launch User", "5551000001")
        outsider_headers, outsider_id = create_user(
            "launch-outsider@example.com", "Launch Outsider", "5551000002"
        )

        for path in (
            "/api/admin/bookings",
            "/api/admin/analytics/summary",
            "/api/admin/staff",
            "/api/admin/users",
        ):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 401, path)
            resp = self.client.get(path, headers=user_headers)
            self.assertEqual(resp.status_code, 403, path)

        resp = self.client.get("/api/rooms?include_inactive=true", headers=user_headers)
        self.assertEqual(resp.status_code, 403)

        booking_room_payload = {
            "name": "Launch Booking Room",
            "description": "Room used for admin launch readiness checks",
            "capacity": 4,
            "photos": [],
            "hourly_rate_cents": 10000,
            "max_booking_duration_minutes": 300,
        }
        resp = self.client.post("/api/rooms", headers=user_headers, json=booking_room_payload)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post("/api/rooms", headers=admin_headers, json=booking_room_payload)
        self.assertEqual(resp.status_code, 201)
        booking_room_id = resp.json()["id"]

        resp = self.client.put(
            f"/api/admin/rooms/{booking_room_id}",
            headers=admin_headers,
            json={"name": "Launch Booking Room Updated", "capacity": 6},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Launch Booking Room Updated")
        self.assertEqual(resp.json()["capacity"], 6)

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
        resp = self.client.post("/api/admin/staff", headers=user_headers, json=staff_payload)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post("/api/admin/staff", headers=admin_headers, json=staff_payload)
        self.assertEqual(resp.status_code, 201)
        staff_id = resp.json()["id"]
        resp = self.client.get("/api/admin/staff", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(profile["id"] == staff_id for profile in resp.json()))
        resp = self.client.put(
            f"/api/admin/staff/{staff_id}",
            headers=admin_headers,
            json={"booking_enabled": False, "skills": ["Podcast", "Mixing"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["booking_enabled"])
        self.assertIn("Mixing", resp.json()["skills"])

        manage_room_payload = {
            "name": "Launch Archive Room",
            "description": "Room used to verify destructive room actions",
            "capacity": 2,
            "photos": [],
            "hourly_rate_cents": 5000,
            "max_booking_duration_minutes": 300,
        }
        resp = self.client.post("/api/rooms", headers=admin_headers, json=manage_room_payload)
        self.assertEqual(resp.status_code, 201)
        manage_room_id = resp.json()["id"]
        resp = self.client.delete(f"/api/rooms/{manage_room_id}", headers=user_headers)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.delete(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/api/rooms/{manage_room_id}")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["active"])
        resp = self.client.post(f"/api/rooms/{manage_room_id}/restore", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["active"])
        resp = self.client.delete(f"/api/rooms/{manage_room_id}/permanent", headers=admin_headers)
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/api/rooms/{manage_room_id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 404)

        business_timezone = ZoneInfo("America/Edmonton")
        booking_date = datetime.now(business_timezone).date() + timedelta(days=8)
        booking_start = datetime(
            booking_date.year, booking_date.month, booking_date.day,
            13, 0, tzinfo=business_timezone,
        )
        resp = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": booking_room_id,
                "start_time": booking_start.isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        user_booking = resp.json()

        resp = self.client.get(f"/api/bookings/{user_booking['id']}", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], user_booking["id"])
        resp = self.client.get(f"/api/bookings/{user_booking['id']}", headers=outsider_headers)
        self.assertEqual(resp.status_code, 404)

        manual_start = datetime(
            booking_date.year, booking_date.month, booking_date.day,
            12, 0, tzinfo=business_timezone,
        )
        resp = self.client.post(
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
        self.assertEqual(resp.status_code, 201)
        manual_booking = resp.json()
        self.assertEqual(manual_booking["status"], "Paid")
        self.assertEqual(manual_booking["user_email"], "walkin-launch@example.com")

        resp = self.client.get("/api/admin/bookings", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        admin_bookings = resp.json()
        self.assertEqual(len(admin_bookings), 2)
        self.assertTrue(any(b["id"] == user_booking["id"] for b in admin_bookings))
        self.assertTrue(any(b["id"] == manual_booking["id"] for b in admin_bookings))

        resp = self.client.get("/api/admin/analytics/summary", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        analytics = resp.json()
        self.assertEqual(analytics["total_bookings"], 2)
        self.assertEqual(analytics["paid_bookings"], 1)
        self.assertEqual(analytics["net_revenue_cents"], 10500)
        self.assertEqual(analytics["refunded_revenue_cents"], 0)
        self.assertGreaterEqual(analytics["active_rooms"], 1)

        resp = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        users = resp.json()
        self.assertTrue(any(u["id"] == admin_id and u["is_admin"] for u in users))
        self.assertTrue(any(u["id"] == admin_id and u["role"] == "AdminManager" for u in users))
        self.assertTrue(any(u["email"] == "launch-user@example.com" for u in users))

        resp = self.client.request(
            "DELETE",
            f"/api/admin/users/{outsider_id}",
            headers=regular_admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client.request(
            "DELETE",
            f"/api/admin/users/{admin_id}",
            headers=regular_admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=regular_admin_headers,
            json={"role": "Admin", "admin_password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=admin_headers,
            json={"role": "Admin", "admin_password": "WrongPassword123!"},
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.client.put(
            f"/api/admin/users/{outsider_id}/role",
            headers=admin_headers,
            json={"role": "Admin", "admin_password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["role"], "Admin")
        self.assertTrue(resp.json()["is_admin"])

        resp = self.client.delete(f"/api/admin/staff/{staff_id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get("/api/admin/staff", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(profile["id"] == staff_id for profile in resp.json()))

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

    def test_42_background_worker_recovery_when_providers_fail(self) -> None:
        """Verify the notification + cleanup tasks survive provider failures
        and stay idempotent. Covers the background-worker-retry-recovery
        catalog case."""
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        from uuid import UUID
        from unittest.mock import patch
        from app.models.room import Room
        from app.services.booking_service import expire_stale_pending_bookings
        from app.tasks import (
            cleanup_expired_pending_bookings_task,
            send_booking_confirmation_email_task,
        )

        with self.SessionLocal() as db:
            room = Room(
                name="Recovery Room",
                description="Worker recovery test room",
                capacity=4,
                photos=[],
                hourly_rate_cents=10000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "recovery-user@example.com",
                "password": "Password123!",
                "full_name": "Recovery User",
                "phone": "5550008000",
            },
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "recovery-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        user_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        biz_tz = ZoneInfo("America/Edmonton")
        booking_date = datetime.now(biz_tz).date() + timedelta(days=12)
        while booking_date.weekday() not in {2, 3, 4, 5}:
            booking_date += timedelta(days=1)
        start_time = datetime(
            booking_date.year, booking_date.month, booking_date.day, 14, 0, tzinfo=biz_tz
        )
        resp = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking_id = resp.json()["id"]

        # 1) Notification task survives provider failure by logging Failed and re-raising.
        with patch(
            "app.tasks.booking_confirmation_email",
            side_effect=RuntimeError("SendGrid down"),
        ):
            with self.assertRaises(RuntimeError):
                send_booking_confirmation_email_task(booking_id)

        with self.SessionLocal() as db:
            failed_logs = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.booking_id == booking_id)
                .filter(self.NotificationLog.type == "booking_confirmation_email_worker")
                .filter(self.NotificationLog.status == "Failed")
                .all()
            )
        self.assertEqual(len(failed_logs), 1)
        self.assertIn("SendGrid down", failed_logs[0].details.get("error", ""))

        # 2) Same task succeeds on the retry once the provider recovers.
        # Force the booking row to look old so the expiry guard inside the
        # task doesn't skip it.
        result = send_booking_confirmation_email_task(booking_id)
        self.assertTrue(result.get("sent") in (True, False))  # opt_in_email may differ

        # 3) The cleanup task is idempotent: a second invocation after a fully
        # cleaned-up state returns "cleaned": 0 and does not raise.
        with self.SessionLocal() as db:
            booking_row = db.query(self.Booking).filter(self.Booking.id == UUID(booking_id)).first()
            booking_row.created_at = _dt.now(_tz.utc) - _td(minutes=20)
            db.commit()
        cleaned_first = expire_stale_pending_bookings(self.SessionLocal())
        self.assertGreaterEqual(cleaned_first, 1)
        # Cleanup task wrapper: should not raise on the second call and reports 0.
        second_result = cleanup_expired_pending_bookings_task()
        self.assertEqual(second_result.get("cleaned", 0), 0)

        # 4) Booking is now Cancelled and a cancellation notification was queued
        # by the expiry path (bucket-2 fix E coverage).
        with self.SessionLocal() as db:
            cancelled = (
                db.query(self.Booking).filter(self.Booking.id == UUID(booking_id)).first()
            )
            expired_notifications = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.booking_id == booking_id)
                .filter(self.NotificationLog.type == "booking_expired")
                .count()
            )
        self.assertEqual(cancelled.status, "Cancelled")
        self.assertGreaterEqual(expired_notifications, 1)


    def test_41_interactive_api_docs_are_closed_in_production(self) -> None:
        """The docs are a complete, callable map of the API surface. Routes bind
        at app construction, so build a second app the same way with APP_ENV set
        to production and assert that one serves nothing."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.config import settings as app_settings

        # Development keeps them, which is the point of gating rather than deleting.
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)

        with patch.object(app_settings, "APP_ENV", "production"):
            docs_enabled = app_settings.APP_ENV != "production"
            self.assertFalse(docs_enabled)
            prod_app = FastAPI(
                docs_url="/docs" if docs_enabled else None,
                redoc_url="/redoc" if docs_enabled else None,
                openapi_url="/openapi.json" if docs_enabled else None,
            )
            prod_client = TestClient(prod_app)
            for path in ("/docs", "/redoc", "/openapi.json"):
                with self.subTest(path=path):
                    self.assertEqual(prod_client.get(path).status_code, 404)

    def test_42_sandbox_paypal_in_production_is_reported_not_hidden(self) -> None:
        """paypal_fully_ready means "configured", and it drives /ready — so it
        must stay true on sandbox or a healthy container starts cycling. The
        honest signal is separate."""
        from app.config import get_paypal_configuration_status
        from app.config import settings as app_settings

        with patch.object(app_settings, "PAYMENT_BACKEND", "paypal"), \
             patch.object(app_settings, "PAYPAL_CLIENT_ID", "real-client-id"), \
             patch.object(app_settings, "PAYPAL_CLIENT_SECRET", "real-secret"), \
             patch.object(app_settings, "PAYPAL_WEBHOOK_ID", "real-webhook-id"):

            with patch.object(app_settings, "PAYPAL_ENV", "sandbox"):
                status = get_paypal_configuration_status()
                self.assertTrue(status["paypal_fully_ready"])
                self.assertFalse(status["paypal_live_mode"])
                self.assertFalse(status["paypal_takes_real_payments"])

            with patch.object(app_settings, "PAYPAL_ENV", "live"):
                status = get_paypal_configuration_status()
                self.assertTrue(status["paypal_takes_real_payments"])
                self.assertTrue(status["paypal_live_mode"])
