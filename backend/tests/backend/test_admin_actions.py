"""
Backend tests — admin booking actions.

Covers: test case catalog API, SuiteDash integration status, admin skip-Stripe
/ waive-payment, admin mark-paid, check-in, refund, staff booking admin
actions, error paths, audit log entries.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.base import BaseAppTest


class AdminActionsTest(BaseAppTest):

    def test_32_admin_backend_test_case_catalog(self) -> None:
        with self.SessionLocal() as db:
            type(self).ensure_admin_user(
                db,
                email="catalog-admin@example.com",
                password="Password123!",
                full_name="Catalog Admin",
            )

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "catalog-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.get("/api/admin/test-cases", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()

        self.assertGreaterEqual(len(payload), 12)
        self.assertTrue(all("health" in item for item in payload))
        self.assertTrue(all(item["health"] in {"working", "needs_fix", "not_working"} for item in payload))
        self.assertTrue(any(item["health"] == "working" for item in payload))
        self.assertTrue(any(item["health"] == "needs_fix" for item in payload))
        self.assertTrue(any(item["health"] == "not_working" for item in payload))
        self.assertTrue(any(item["title"] == "Payment confirmation end-to-end" for item in payload))
        self.assertTrue(
            any(item["title"] == "Runtime config rejects placeholder production secrets" for item in payload)
        )

        resp = self.client.get(
            "/api/admin/integrations/suitedash/status", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])
        self.assertFalse(resp.json()["configured"])
        self.assertEqual(resp.json()["contact_meta_path"], "/contact/meta")

        resp = self.client.get(
            "/api/admin/integrations/suitedash/contact-meta", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("SuiteDash integration is disabled", resp.text)

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

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-admin@example.com",
                "password": "Password123!",
                "full_name": "Free Admin",
                "phone": "5551231111",
            },
        )
        self.assertEqual(resp.status_code, 201)
        admin_id = resp.json()["id"]

        with self.SessionLocal() as db:
            admin = db.query(self.User).filter(self.User.id == admin_id).first()
            admin.is_admin = True
            db.commit()

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "free-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "free-guest@example.com",
                "password": "Password123!",
                "full_name": "Free Guest",
                "phone": "5551232222",
            },
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "free-guest@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        guest_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        business_timezone = ZoneInfo("America/Edmonton")
        free_booking_date = datetime.now(business_timezone).date() + timedelta(days=4)
        start_time = datetime(
            free_booking_date.year, free_booking_date.month, free_booking_date.day,
            16, 0, tzinfo=business_timezone,
        )
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()
        self.assertEqual(booking["status"], "PendingPayment")
        self.assertEqual(booking["price_cents"], self._room_price(10000, 60))

        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/waive-payment", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        waived_booking = resp.json()
        self.assertEqual(waived_booking["status"], "Paid")
        self.assertEqual(waived_booking["price_cents"], 0)
        self.assertTrue(waived_booking["payment_intent_id"].startswith("admin_waived_"))

        resp = self.client.get(f"/api/bookings/{booking['id']}", headers=guest_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertEqual(resp.json()["price_cents"], 0)

        resp = self.client.get("/api/admin/bookings?status=Paid", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        paid_booking = next(item for item in resp.json() if item["id"] == booking["id"])
        self.assertEqual(paid_booking["price_cents"], 0)

        resp = self.client.get("/api/admin/activity?limit=10", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        activity_actions = [item["action"] for item in resp.json()]
        self.assertIn("payment_waived_by_admin", activity_actions)

    def test_34_admin_booking_action_suite(self) -> None:
        from app.models.room import Room
        from app.models.staff_profile import StaffProfile

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

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "suite-admin@example.com",
                "password": "Password123!",
                "full_name": "Suite Admin",
                "phone": "4031110001",
            },
        )
        self.assertEqual(resp.status_code, 201)
        admin_user_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == admin_user_id).first()
            u.is_admin = True
            db.commit()
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "suite-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "suite-guest@example.com",
                "password": "Password123!",
                "full_name": "Suite Guest",
                "phone": "4031110002",
            },
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "suite-guest@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        guest_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        biz_tz = ZoneInfo("America/Edmonton")
        base = datetime.now(biz_tz).date() + timedelta(days=10)

        def make_start(day_offset, hour):
            d = base + timedelta(days=day_offset)
            return datetime(d.year, d.month, d.day, hour + 2, 0, tzinfo=biz_tz).isoformat()

        # 1. admin mark-paid (room booking)
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(0, 10), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()
        self.assertEqual(booking["status"], "PendingPayment")
        price = booking["price_cents"]
        self.assertGreater(price, 0)

        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/mark-paid", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        paid = resp.json()
        self.assertEqual(paid["status"], "Paid")
        self.assertTrue(paid["payment_intent_id"].startswith("admin_manual_paid_"))
        self.assertEqual(paid["price_cents"], price)

        # 2. check-in (room booking already paid)
        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/check-in", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        checked_in = resp.json()
        self.assertEqual(checked_in["status"], "Completed")
        self.assertIsNotNone(checked_in["checked_in_at"])

        # 3. refund (completed booking)
        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/refund",
            headers=admin_headers,
            json={"amount_cents": price, "reason": "Test refund"},
        )
        self.assertEqual(resp.status_code, 200)
        refund = resp.json()
        self.assertIn("id", refund)
        self.assertEqual(refund["amount_cents"], price)

        # 4. admin waive-payment (second room booking)
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(1, 14), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking2 = resp.json()
        self.assertEqual(booking2["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/bookings/{booking2['id']}/waive-payment", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        waived = resp.json()
        self.assertEqual(waived["status"], "Paid")
        self.assertEqual(waived["price_cents"], 0)
        self.assertTrue(waived["payment_intent_id"].startswith("admin_waived_"))

        # 5. staff booking: waive-payment
        resp = self.client.post(
            "/api/staff-bookings",
            headers=guest_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": make_start(2, 10),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        staff_booking = resp.json()
        self.assertEqual(staff_booking["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking['id']}/waive-payment",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertEqual(resp.json()["price_cents"], 0)

        # 6. staff booking: mark-paid
        resp = self.client.post(
            "/api/staff-bookings",
            headers=guest_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": make_start(3, 10),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        staff_booking2 = resp.json()
        self.assertEqual(staff_booking2["status"], "PendingPayment")

        resp = self.client.post(
            f"/api/admin/staff-bookings/{staff_booking2['id']}/mark-paid",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "Paid")
        self.assertTrue(resp.json()["payment_intent_id"].startswith("admin_staff_manual_paid_"))

        # 7. error: mark-paid on already-Paid booking
        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/mark-paid", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("pending", resp.json()["detail"].lower())

        # 8. error: waive-payment on already-Paid booking
        resp = self.client.post(
            f"/api/admin/bookings/{booking2['id']}/waive-payment", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 400)

        # 9. error: check-in on PendingPayment booking
        resp = self.client.post(
            "/api/bookings",
            headers=guest_headers,
            json={"room_id": room_id, "start_time": make_start(4, 10), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        pending_id = resp.json()["id"]

        resp = self.client.post(
            f"/api/admin/bookings/{pending_id}/check-in", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("paid", resp.json()["detail"].lower())

        # 10. error: check-in on already-completed/refunded booking
        resp = self.client.post(
            f"/api/admin/bookings/{booking['id']}/check-in", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 400)

        # 11. non-admin is rejected
        resp = self.client.post(
            f"/api/admin/bookings/{pending_id}/mark-paid", headers=guest_headers
        )
        self.assertEqual(resp.status_code, 403)

        # 12. admin lookup returns both room and staff bookings
        resp = self.client.get("/api/admin/bookings", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        all_bookings = resp.json()
        kinds = {b["booking_kind"] for b in all_bookings}
        self.assertIn("room", kinds)
        self.assertIn("staff", kinds)

        # 13. audit log records admin actions
        resp = self.client.get("/api/admin/activity?limit=50", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        actions = {item["action"] for item in resp.json()}
        self.assertIn("payment_marked_paid_by_admin", actions)
        self.assertIn("payment_waived_by_admin", actions)
        self.assertIn("booking_checked_in", actions)

    def test_35_room_and_staff_rate_changes_reflect_in_bookings(self) -> None:
        from app.models.room import Room
        from app.models.staff_profile import StaffProfile

        with self.SessionLocal() as db:
            room = Room(
                name="Rate Change Room",
                description="Room for admin rate-change price verification",
                capacity=4,
                photos=[],
                hourly_rate_cents=10000,
            )
            profile = StaffProfile(
                name="Rate Change Engineer",
                description="Staff for admin rate-change price verification",
                skills=["Recording"],
                talents=[],
                booking_rate_cents=10000,
                add_on_price_cents=0,
                service_types=["Recording"],
                booking_enabled=True,
                active=True,
            )
            db.add(room)
            db.add(profile)
            db.commit()
            db.refresh(room)
            db.refresh(profile)
            room_id = str(room.id)
            profile_id = str(profile.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "rate-admin@example.com",
                "password": "Password123!",
                "full_name": "Rate Admin",
                "phone": "5559990001",
            },
        )
        self.assertEqual(resp.status_code, 201)
        admin_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == admin_id).first()
            u.is_admin = True
            db.commit()
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "rate-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "org-member@example.com",
                "password": "Password123!",
                "full_name": "Org Member",
                "phone": "5559990002",
            },
        )
        self.assertEqual(resp.status_code, 201)
        member_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == member_id).first()
            u.user_category = "organizational_member"
            db.commit()
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "org-member@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        member_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        # Room booking at $100/hr — driven by room.hourly_rate_cents (admin-controlled)
        resp = self.client.post(
            "/api/bookings",
            headers=member_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=1, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["price_cents"], self._room_price(10000, 60))

        # Admin changes room to $50/hr
        resp = self.client.put(
            f"/api/admin/rooms/{room_id}",
            headers=admin_headers,
            json={"hourly_rate_cents": 5000},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["hourly_rate_cents"], 5000)

        # New room booking reflects updated $50/hr rate
        resp = self.client.post(
            "/api/bookings",
            headers=member_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=2, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["price_cents"], self._room_price(5000, 60))

        # Staff booking at $100/hr
        resp = self.client.post(
            "/api/staff-bookings",
            headers=member_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": self._future_time(day=3, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["price_cents"], self._staff_price(10000, 60))

        # Admin changes staff to $50/hr
        resp = self.client.put(
            f"/api/admin/staff/{profile_id}",
            headers=admin_headers,
            json={"booking_rate_cents": 5000},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["booking_rate_cents"], 5000)

        # New staff booking reflects updated $50/hr rate
        resp = self.client.post(
            "/api/staff-bookings",
            headers=member_headers,
            json={
                "staff_profile_id": profile_id,
                "start_time": self._future_time(day=4, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["price_cents"], self._staff_price(5000, 60))
