"""Step 7d: schedule_published gates public availability + booking."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffSchedulePublishTest(BaseAppTest):
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

    def _unpublished_staff(self, admin) -> dict:
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Unpublished Engineer", "booking_rate_cents": 6000, "active": True},
            headers=admin,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertFalse(body["schedule_published"])  # default
        return body

    def _start_times(self, staff_id, day):
        resp = self.client.get(f"/api/staff/{staff_id}/availability?date={day.isoformat()}")
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["available_start_times"]

    def test_01_unpublished_has_no_public_availability(self) -> None:
        admin = self._admin_headers()
        staff = self._unpublished_staff(admin)
        day = self._future_time(day=1, hour=10).date()
        self.assertEqual(self._start_times(staff["id"], day), [])

    def test_02_unpublished_booking_is_rejected(self) -> None:
        admin = self._admin_headers()
        staff = self._unpublished_staff(admin)
        start = self._future_time(day=1, hour=12).isoformat()
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers("pubbuyer@example.com"),
            json={"staff_profile_id": staff["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"], "Selected staff member is not available for this time")

    def test_03_publishing_makes_bookable(self) -> None:
        admin = self._admin_headers()
        staff = self._unpublished_staff(admin)
        published = self.client.put(
            f"/api/admin/staff/{staff['id']}", json={"schedule_published": True}, headers=admin
        )
        self.assertEqual(published.status_code, 200, published.text)
        self.assertTrue(published.json()["schedule_published"])

        day = self._future_time(day=1, hour=10).date()
        self.assertTrue(self._start_times(staff["id"], day))  # now has availability

        start = self._future_time(day=1, hour=12).isoformat()
        resp = self.client.post(
            "/api/staff-bookings",
            headers=self._customer_headers("pubbuyer2@example.com"),
            json={"staff_profile_id": staff["id"], "start_time": start, "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_04_admin_calendar_shows_unpublished(self) -> None:
        admin = self._admin_headers()
        staff = self._unpublished_staff(admin)
        day = self._future_time(day=1, hour=10).date()
        # Give the (still unpublished) staff a weekly rule for that weekday.
        self.client.post(
            f"/api/admin/staff/{staff['id']}/availability/rules",
            json={"weekday": day.weekday(), "start_minute": 840, "end_minute": 1080},
            headers=admin,
        )
        resp = self.client.get(f"/api/admin/staff/schedule?date={day.isoformat()}", headers=admin)
        self.assertEqual(resp.status_code, 200, resp.text)
        row = next(item for item in resp.json() if item["staff_profile_id"] == staff["id"])
        # Admin reviews the schedule even before publishing.
        self.assertEqual(row["windows"], [{"start_minute": 840, "end_minute": 1080}])
