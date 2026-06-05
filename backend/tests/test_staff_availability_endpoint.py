"""Step 3: the public staff availability endpoint respects availability rules."""
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest

FRIDAY = 4


class StaffAvailabilityEndpointTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="availep-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0079",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "availep-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _staff_id(self, headers) -> str:
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Scheduled Engineer", "booking_rate_cents": 5000, "active": True, "schedule_published": True},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def _next_friday(self):
        base = datetime.now(timezone.utc).date() + timedelta(days=14)
        return base + timedelta(days=(FRIDAY - base.weekday()) % 7)

    def _next_sunday(self):
        business_timezone = ZoneInfo("America/Edmonton")
        base = datetime.now(business_timezone).date() + timedelta(days=14)
        return base + timedelta(days=(6 - base.weekday()) % 7)

    def _start_hours(self, staff_id, day):
        resp = self.client.get(f"/api/staff/{staff_id}/availability?date={day.isoformat()}")
        self.assertEqual(resp.status_code, 200, resp.text)
        return sorted(
            datetime.fromisoformat(value).hour for value in resp.json()["available_start_times"]
        )

    def test_01_rule_restricts_to_window(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        friday = self._next_friday()

        # Without any rule, staff are unavailable by default.
        self.assertEqual(self._start_hours(staff_id, friday), [])

        # Friday 14:00-18:00 rule -> only 14,15,16,17 start hours.
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={"weekday": FRIDAY, "start_minute": 840, "end_minute": 1080},
            headers=headers,
        )
        hours = self._start_hours(staff_id, friday)
        self.assertEqual(hours, [14, 15, 16, 17])

    def test_02_other_weekday_has_no_availability_when_scheduled(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={"weekday": FRIDAY, "start_minute": 840, "end_minute": 1080},
            headers=headers,
        )
        # A Wednesday (business day) with no Friday-style rule -> no slots.
        wednesday = self._next_friday() - timedelta(days=2)
        self.assertEqual(self._start_hours(staff_id, wednesday), [])

    def test_03_blocked_exception_removes_slot(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        friday = self._next_friday()
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={"weekday": FRIDAY, "start_minute": 840, "end_minute": 1080},
            headers=headers,
        )
        # Block 15:00-16:00 -> the 15:00 start can no longer fit an hour.
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/exceptions",
            json={
                "exception_date": friday.isoformat(),
                "start_minute": 900,
                "end_minute": 960,
                "is_available": False,
            },
            headers=headers,
        )
        hours = self._start_hours(staff_id, friday)
        self.assertNotIn(15, hours)
        self.assertIn(14, hours)
        self.assertIn(16, hours)

    def test_04_unscheduled_closed_day_has_no_default_availability(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        self.assertEqual(self._start_hours(staff_id, self._next_sunday()), [])

    def test_05_extra_available_exception_opens_closed_day_window(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        sunday = self._next_sunday()
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/exceptions",
            json={
                "exception_date": sunday.isoformat(),
                "start_minute": 720,
                "end_minute": 840,
                "is_available": True,
            },
            headers=headers,
        )
        self.assertEqual(self._start_hours(staff_id, sunday), [12, 13])

        monthly = self.client.get(
            f"/api/staff/{staff_id}/availability/monthly?month={sunday.isoformat()[:7]}"
        )
        self.assertEqual(monthly.status_code, 200, monthly.text)
        self.assertEqual(monthly.json()["days"][sunday.isoformat()], 2)

    def test_06_invalid_staff_id_returns_not_found(self) -> None:
        target_day = self._next_friday().isoformat()
        daily = self.client.get(f"/api/staff/not-a-uuid/availability?date={target_day}")
        monthly = self.client.get(
            f"/api/staff/not-a-uuid/availability/monthly?month={target_day[:7]}"
        )

        self.assertEqual(daily.status_code, 404, daily.text)
        self.assertEqual(monthly.status_code, 404, monthly.text)
