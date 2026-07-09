"""Staff availability is public as soon as staff set it (no admin publish gate).

Historically a ``schedule_published`` flag hid staff availability until an admin
flipped it. That gate was removed: the windows a staff member configures are live
immediately, and a staff member with no windows simply has no bookable slots."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffScheduleVisibilityTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="pub-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0129",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "pub-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _customer_headers(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Customer", "phone": "403-555-0100"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _staff(self, admin) -> dict:
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Live Engineer", "booking_rate_cents": 6000, "active": True},
            headers=admin,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def _add_weekly_rule(self, admin, staff_id, day, start_minute=720, end_minute=1200):
        resp = self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={"weekday": day.weekday(), "start_minute": start_minute, "end_minute": end_minute},
            headers=admin,
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def _start_times(self, staff_id, day):
        resp = self.client.get(f"/api/staff/{staff_id}/availability?date={day.isoformat()}")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["available_start_times"]

    def test_01_availability_is_public_without_a_publish_step(self) -> None:
        admin = self._admin_headers()
        staff = self._staff(admin)
        day = self._future_time(day=1, hour=10).date()
        self._add_weekly_rule(admin, staff["id"], day)
        # No publish flag toggled — the configured window is immediately visible.
        self.assertTrue(self._start_times(staff["id"], day))

    def test_02_booking_succeeds_without_a_publish_step(self) -> None:
        admin = self._admin_headers()
        staff = self._staff(admin)
        day = self._future_time(day=1, hour=10).date()
        self._add_weekly_rule(admin, staff["id"], day)
        start = self._future_time(day=1, hour=12).isoformat()
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers("livebuyer@example.com"),
            json={"staff_profile_id": staff["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_03_no_windows_means_no_public_slots(self) -> None:
        admin = self._admin_headers()
        staff = self._staff(admin)  # no rules/exceptions configured
        day = self._future_time(day=1, hour=10).date()
        self.assertEqual(self._start_times(staff["id"], day), [])

        start = self._future_time(day=1, hour=12).isoformat()
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers("livebuyer2@example.com"),
            json={"staff_profile_id": staff["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"], "Selected staff member is not available for this time")

    def test_04_admin_calendar_shows_configured_windows(self) -> None:
        admin = self._admin_headers()
        staff = self._staff(admin)
        day = self._future_time(day=1, hour=10).date()
        self._add_weekly_rule(admin, staff["id"], day, start_minute=840, end_minute=1080)
        resp = self.client.get(f"/api/admin/staff/schedule?date={day.isoformat()}", headers=admin)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = next(item for item in resp.json() if item["staff_profile_id"] == staff["id"])
        self.assertEqual(row["windows"], [{"start_minute": 840, "end_minute": 1080}])
