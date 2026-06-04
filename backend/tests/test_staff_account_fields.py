"""Backend tests for staff contact/account fields + the Staff role (Step 1)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class RolesUnitTest(BaseAppTest):
    def test_staff_role_normalization_and_access(self) -> None:
        from app.roles import (
            USER_ROLE_STAFF,
            normalize_user_role,
            user_has_staff_access,
        )

        self.assertEqual(normalize_user_role("staff"), USER_ROLE_STAFF)
        self.assertEqual(normalize_user_role("Service Engineer"), USER_ROLE_STAFF)

        class _U:
            def __init__(self, role, is_admin=False):
                self.role = role
                self.is_admin = is_admin

        self.assertTrue(user_has_staff_access(_U("Staff")))
        self.assertTrue(user_has_staff_access(_U("Admin", is_admin=True)))
        self.assertFalse(user_has_staff_access(_U("Customer")))


class StaffAccountFieldsTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="staffacct-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0059",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "staffacct-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _register(self, email: str) -> None:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Eng", "phone": "403-555-0100"},
        )

    def test_01_create_with_account_fields(self) -> None:
        headers = self._admin_headers()
        resp = self.client.post(
            "/api/admin/staff",
            json={
                "name": "Notifying Engineer",
                "role_title": "Sound Engineer",
                "notification_email": "notify@example.com",
                "notification_phone": "403-555-0199",
                "notify_by_email": True,
                "notify_by_sms": True,
                "booking_requires_approval": True,
                "active": True,
            },
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["role_title"], "Sound Engineer")
        self.assertEqual(body["notification_email"], "notify@example.com")
        self.assertEqual(body["notification_phone"], "403-555-0199")
        self.assertTrue(body["notify_by_sms"])
        self.assertTrue(body["booking_requires_approval"])
        self.assertIsNone(body["user_id"])

    def test_02_defaults(self) -> None:
        headers = self._admin_headers()
        resp = self.client.post(
            "/api/admin/staff", json={"name": "Default Engineer", "active": True}, headers=headers
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertTrue(body["notify_by_email"])
        self.assertFalse(body["notify_by_sms"])
        self.assertTrue(body["booking_requires_approval"])

    def test_03_link_account_grants_staff_role(self) -> None:
        headers = self._admin_headers()
        self._register("engineer@example.com")
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Linked Engineer", "linked_user_email": "engineer@example.com", "active": True},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertIsNotNone(resp.json()["user_id"])
        self.assertEqual(resp.json()["linked_user_email"], "engineer@example.com")
        listed = self.client.get("/api/admin/staff", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        linked = next(profile for profile in listed.json() if profile["id"] == resp.json()["id"])
        self.assertEqual(linked["linked_user_email"], "engineer@example.com")
        public = self.client.get("/api/staff")
        self.assertEqual(public.status_code, 200, public.text)
        public_profile = next(profile for profile in public.json() if profile["id"] == resp.json()["id"])
        self.assertNotIn("linked_user_email", public_profile)
        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.email == "engineer@example.com").first()
            self.assertEqual(user.role, "Staff")
            self.assertFalse(user.is_admin)

    def test_04_link_unknown_account_is_rejected(self) -> None:
        headers = self._admin_headers()
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Bad Link", "linked_user_email": "nobody@example.com", "active": True},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_05_update_account_fields(self) -> None:
        headers = self._admin_headers()
        created = self.client.post(
            "/api/admin/staff", json={"name": "Updatable Engineer", "active": True}, headers=headers
        ).json()
        resp = self.client.put(
            f"/api/admin/staff/{created['id']}",
            json={"booking_requires_approval": False, "notification_phone": "403-555-0200"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["booking_requires_approval"])
        self.assertEqual(resp.json()["notification_phone"], "403-555-0200")
