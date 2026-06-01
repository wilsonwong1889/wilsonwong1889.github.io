"""Backend tests for public intake forms (membership interest + engineer application)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class IntakeTest(BaseAppTest):
    def _admin_token(self) -> str:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="intake-admin@example.com",
                password="AdminPass1!",
                full_name="Intake Admin",
                phone="403-000-0009",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "intake-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["access_token"]

    def test_01_membership_interest_persists(self) -> None:
        resp = self.client.post(
            "/api/intake/membership-interest",
            json={
                "name": "Jane Artist",
                "email": "jane@example.com",
                "phone": "403-555-0111",
                "membership_interest": "Artist Member",
                "message": "I make beats.",
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["intake_type"], "membership_interest")
        self.assertEqual(body["status"], "new")
        self.assertEqual(body["details"]["membership_interest"], "Artist Member")
        self.assertEqual(body["details"]["message"], "I make beats.")

    def test_02_membership_interest_validation(self) -> None:
        # Missing required membership_interest -> 422
        resp = self.client.post(
            "/api/intake/membership-interest",
            json={"name": "No Interest", "email": "x@example.com", "phone": "403-555-0112"},
        )
        self.assertEqual(resp.status_code, 422, resp.text)
        # Invalid email -> 422
        resp = self.client.post(
            "/api/intake/membership-interest",
            json={
                "name": "Bad Email",
                "email": "not-an-email",
                "phone": "403-555-0112",
                "membership_interest": "Artist Member",
            },
        )
        self.assertEqual(resp.status_code, 422, resp.text)

    def test_03_engineer_application_persists(self) -> None:
        resp = self.client.post(
            "/api/intake/engineer-application",
            json={
                "name": "Sam Engineer",
                "email": "sam@example.com",
                "phone": "403-555-0113",
                "skillset": "Mixing, mastering",
                "equipment": "SSL console",
                "why_considered": "10 years of studio experience.",
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["intake_type"], "engineer_application")
        self.assertEqual(body["details"]["skillset"], "Mixing, mastering")
        self.assertEqual(body["details"]["equipment"], "SSL console")
        self.assertEqual(body["details"]["why_considered"], "10 years of studio experience.")

    def test_04_admin_list_filter_and_status_update(self) -> None:
        self.client.post(
            "/api/intake/membership-interest",
            json={
                "name": "A",
                "email": "a@example.com",
                "phone": "403-555-0001",
                "membership_interest": "Venture Member",
            },
        )
        self.client.post(
            "/api/intake/engineer-application",
            json={
                "name": "B",
                "email": "b@example.com",
                "phone": "403-555-0002",
                "skillset": "FOH",
                "why_considered": "Touring background.",
            },
        )
        headers = {"Authorization": f"Bearer {self._admin_token()}"}

        resp = self.client.get("/api/admin/intakes", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        items = resp.json()
        self.assertEqual(len(items), 2)
        # Newest first
        self.assertEqual(items[0]["intake_type"], "engineer_application")

        resp = self.client.get(
            "/api/admin/intakes?intake_type=membership_interest", headers=headers
        )
        self.assertEqual(len(resp.json()), 1)

        target_id = items[0]["id"]
        resp = self.client.patch(
            f"/api/admin/intakes/{target_id}", json={"status": "reviewed"}, headers=headers
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "reviewed")

        resp = self.client.get("/api/admin/intakes?status=reviewed", headers=headers)
        self.assertEqual(len(resp.json()), 1)

    def test_05_invalid_status_rejected(self) -> None:
        self.client.post(
            "/api/intake/membership-interest",
            json={
                "name": "C",
                "email": "c@example.com",
                "phone": "403-555-0003",
                "membership_interest": "Artist Member",
            },
        )
        headers = {"Authorization": f"Bearer {self._admin_token()}"}
        intake_id = self.client.get("/api/admin/intakes", headers=headers).json()[0]["id"]
        resp = self.client.patch(
            f"/api/admin/intakes/{intake_id}", json={"status": "bogus"}, headers=headers
        )
        self.assertEqual(resp.status_code, 422, resp.text)

    def test_06_admin_endpoints_require_auth(self) -> None:
        resp = self.client.get("/api/admin/intakes")
        self.assertIn(resp.status_code, (401, 403), resp.text)
