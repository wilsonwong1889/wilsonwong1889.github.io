"""Step 7a/7b: staff self-service portal + admin aggregate schedule."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffPortalTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="portal-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0119",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "portal-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _register(self, email: str) -> None:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Person", "phone": "403-555-0100"},
        )

    def _login(self, email: str) -> dict:
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _linked_staff(self, admin, name, email) -> str:
        self._register(email)
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": name, "booking_rate_cents": 6000, "linked_user_email": email, "active": True, "schedule_published": True},
            headers=admin,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def test_01_get_my_profile(self) -> None:
        admin = self._admin_headers()
        self._linked_staff(admin, "Portal Engineer", "eng@example.com")
        resp = self.client.get("/api/staff/me", headers=self._login("eng@example.com"))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["name"], "Portal Engineer")

    def test_02_manage_own_schedule(self) -> None:
        admin = self._admin_headers()
        self._linked_staff(admin, "Sched Engineer", "sched@example.com")
        headers = self._login("sched@example.com")

        created = self.client.post(
            "/api/staff/me/availability/rules",
            json={"weekday": 4, "start_minute": 840, "end_minute": 1200},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(len(self.client.get("/api/staff/me/availability/rules", headers=headers).json()), 1)

        deleted = self.client.delete(
            f"/api/staff/me/availability/rules/{created.json()['id']}", headers=headers
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

        exc = self.client.post(
            "/api/staff/me/availability/exceptions",
            json={"exception_date": "2026-07-03", "is_available": False, "reason": "Away"},
            headers=headers,
        )
        self.assertEqual(exc.status_code, 201, exc.text)

    def test_03_non_staff_forbidden(self) -> None:
        self._register("justcustomer@example.com")
        resp = self.client.get("/api/staff/me", headers=self._login("justcustomer@example.com"))
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_04_accept_own_request_in_app(self) -> None:
        admin = self._admin_headers()
        staff_id = self._linked_staff(admin, "Inbox Engineer", "inbox@example.com")
        staff_headers = self._login("inbox@example.com")

        # A customer requests this staff member.
        self._register("buyer@example.com")
        start = self._future_time(day=1, hour=12)
        self._make_staff_available_for_time(staff_id, start)
        booked = self.client.post(
            "/api/staff-bookings",
            headers=self._login("buyer@example.com"),
            json={"staff_profile_id": staff_id, "start_time": start.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(booked.status_code, 201, booked.text)
        booking_id = booked.json()["id"]

        requests = self.client.get("/api/staff/me/booking-requests", headers=staff_headers)
        self.assertEqual(requests.status_code, 200, requests.text)
        self.assertTrue(any(item["id"] == booking_id for item in requests.json()))

        accepted = self.client.post(
            f"/api/staff/me/booking-requests/{booking_id}/accept", headers=staff_headers
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "AcceptedPendingPayment")

    def test_05_cannot_act_on_others_request(self) -> None:
        admin = self._admin_headers()
        staff_a = self._linked_staff(admin, "Engineer A", "enga@example.com")
        self._linked_staff(admin, "Engineer B", "engb@example.com")

        self._register("buyer2@example.com")
        start = self._future_time(day=1, hour=12)
        self._make_staff_available_for_time(staff_a, start)
        booking_id = self.client.post(
            "/api/staff-bookings",
            headers=self._login("buyer2@example.com"),
            json={"staff_profile_id": staff_a, "start_time": start.isoformat(), "duration_minutes": 60},
        ).json()["id"]

        # Engineer B can't accept Engineer A's request.
        resp = self.client.post(
            f"/api/staff/me/booking-requests/{booking_id}/accept", headers=self._login("engb@example.com")
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_07_staff_edit_own_profile(self) -> None:
        admin = self._admin_headers()
        self._linked_staff(admin, "Editable Engineer", "edit@example.com")
        headers = self._login("edit@example.com")

        resp = self.client.put(
            "/api/staff/me",
            json={
                "name": "Editable Engineer Renamed",
                "role_title": "Senior Engineer",
                "bio": "20 years behind the board.",
                "skills": ["Pro Tools", "Mixing"],
                "notify_by_sms": True,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["name"], "Editable Engineer Renamed")
        self.assertEqual(body["role_title"], "Senior Engineer")
        self.assertEqual(body["skills"], ["Pro Tools", "Mixing"])
        self.assertTrue(body["notify_by_sms"])
        # Admin-only fields untouched (rate set to 6000 by _linked_staff).
        self.assertEqual(body["booking_rate_cents"], 6000)

    def test_08_staff_cannot_edit_admin_only_fields(self) -> None:
        admin = self._admin_headers()
        staff_id = self._linked_staff(admin, "Locked Engineer", "locked@example.com")
        headers = self._login("locked@example.com")

        for forbidden in [
            {"booking_rate_cents": 1},
            {"schedule_published": False},
            {"linked_user_email": "someone-else@example.com"},
            {"active": False},
            {"booking_requires_approval": False},
        ]:
            resp = self.client.put("/api/staff/me", json={"name": "Locked Engineer", **forbidden}, headers=headers)
            self.assertEqual(resp.status_code, 422, f"{forbidden} -> {resp.status_code}: {resp.text}")

        # Confirm nothing changed via admin read.
        current = next(p for p in self.client.get("/api/admin/staff", headers=admin).json() if p["id"] == staff_id)
        self.assertEqual(current["booking_rate_cents"], 6000)
        self.assertTrue(current["schedule_published"])
        self.assertTrue(current["active"])

    def test_09_staff_upload_own_photo(self) -> None:
        import io

        from PIL import Image

        admin = self._admin_headers()
        self._linked_staff(admin, "Photo Engineer", "photo@example.com")
        headers = self._login("photo@example.com")

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (120, 80, 200)).save(buf, format="PNG")
        resp = self.client.post(
            "/api/staff/me/photo",
            files={"photo": ("me.png", buf.getvalue(), "image/png")},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["photo_url"].startswith("/assets/media/staff/"))

    def test_06_admin_aggregate_schedule(self) -> None:
        from datetime import datetime, timedelta, timezone

        admin = self._admin_headers()
        staff_id = self._linked_staff(admin, "Calendar Engineer", "cal@example.com")
        target = (datetime.now(timezone.utc).date() + timedelta(days=14))
        # Move to the staff member's configured weekday.
        self.client.post(
            "/api/staff/me/availability/rules",
            json={"weekday": target.weekday(), "start_minute": 840, "end_minute": 1200},
            headers=self._login("cal@example.com"),
        )
        resp = self.client.get(f"/api/admin/staff/schedule?date={target.isoformat()}", headers=admin)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = next(item for item in resp.json() if item["staff_profile_id"] == staff_id)
        self.assertEqual(row["windows"], [{"start_minute": 840, "end_minute": 1200}])
