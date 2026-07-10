"""Backend tests for staff availability rules + exceptions (Step 2)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffAvailabilityTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="avail-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0069",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "avail-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _staff_id(self, headers) -> str:
        resp = self.client.post(
            "/api/admin/staff", json={"name": "Availability Engineer", "active": True}, headers=headers
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()["id"]

    def test_01_rule_crud(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        base = f"/api/admin/staff/{staff_id}/availability/rules"

        created = self.client.post(
            base, json={"weekday": 4, "start_minute": 840, "end_minute": 1200}, headers=headers
        )
        self.assertEqual(created.status_code, 201, created.text)
        rule_id = created.json()["id"]

        listed = self.client.get(base, headers=headers)
        self.assertEqual(len(listed.json()), 1)

        deleted = self.client.delete(f"{base}/{rule_id}", headers=headers)
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(len(self.client.get(base, headers=headers).json()), 0)

    def test_02_rule_validation(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        base = f"/api/admin/staff/{staff_id}/availability/rules"
        # end before start -> 422
        resp = self.client.post(base, json={"weekday": 1, "start_minute": 1200, "end_minute": 840}, headers=headers)
        self.assertEqual(resp.status_code, 422, resp.text)
        # invalid weekday -> 422
        resp = self.client.post(base, json={"weekday": 9, "start_minute": 0, "end_minute": 60}, headers=headers)
        self.assertEqual(resp.status_code, 422, resp.text)

    def test_03_exception_crud_and_validation(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        base = f"/api/admin/staff/{staff_id}/availability/exceptions"

        created = self.client.post(
            base,
            json={"exception_date": "2026-07-03", "start_minute": 900, "end_minute": 1000, "is_available": False, "reason": "Out"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(len(self.client.get(base, headers=headers).json()), 1)

        # Only one of start/end provided -> 422
        bad = self.client.post(
            base, json={"exception_date": "2026-07-04", "start_minute": 900, "is_available": False}, headers=headers
        )
        self.assertEqual(bad.status_code, 422, bad.text)

        deleted = self.client.delete(f"{base}/{created.json()['id']}", headers=headers)
        self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_04_delete_unknown_is_404(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        import uuid

        resp = self.client.delete(
            f"/api/admin/staff/{staff_id}/availability/rules/{uuid.uuid4()}", headers=headers
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_05_requires_admin(self) -> None:
        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        resp = self.client.get(f"/api/admin/staff/{staff_id}/availability/rules")
        self.assertIn(resp.status_code, (401, 403), resp.text)

    def test_06_available_windows_computation(self) -> None:
        from app.services.staff_availability_service import available_windows_for_date

        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        target = date(2026, 6, 15)
        weekday = target.weekday()

        # Weekly rule covering 14:00-20:00 (840-1200).
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/rules",
            json={"weekday": weekday, "start_minute": 840, "end_minute": 1200},
            headers=headers,
        )
        with self.SessionLocal() as db:
            self.assertEqual(available_windows_for_date(db, staff_id, target), [(840, 1200)])

        # Block 15:00-16:00 on that date -> split window.
        self.client.post(
            f"/api/admin/staff/{staff_id}/availability/exceptions",
            json={"exception_date": target.isoformat(), "start_minute": 900, "end_minute": 960, "is_available": False},
            headers=headers,
        )
        with self.SessionLocal() as db:
            self.assertEqual(
                available_windows_for_date(db, staff_id, target), [(840, 900), (960, 1200)]
            )

    def test_07_all_day_available_spans_studio_hours_not_midnight_to_midnight(self) -> None:
        """An all-day "extra available" exception opens 12 PM-8 PM, not 24 hours,
        so a staff member never becomes bookable at 3 AM. An all-day block still
        blocks the entire day."""
        from app.services.staff_availability_service import available_windows_for_date

        headers = self._admin_headers()
        staff_id = self._staff_id(headers)
        exceptions_url = f"/api/admin/staff/{staff_id}/availability/exceptions"

        # No weekly rules at all: the day is bookable only via the exception.
        available_day = date(2026, 6, 17)
        resp = self.client.post(
            exceptions_url,
            json={"exception_date": available_day.isoformat(), "is_available": True},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        with self.SessionLocal() as db:
            self.assertEqual(available_windows_for_date(db, staff_id, available_day), [(720, 1200)])

        # An all-day block covers the whole 24 hours, so nothing survives — even
        # a same-day all-day "available" exception.
        blocked_day = date(2026, 6, 18)
        self.client.post(
            exceptions_url,
            json={"exception_date": blocked_day.isoformat(), "is_available": True},
            headers=headers,
        )
        self.client.post(
            exceptions_url,
            json={"exception_date": blocked_day.isoformat(), "is_available": False},
            headers=headers,
        )
        with self.SessionLocal() as db:
            self.assertEqual(available_windows_for_date(db, staff_id, blocked_day), [])
