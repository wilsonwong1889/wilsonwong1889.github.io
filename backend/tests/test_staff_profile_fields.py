"""Backend tests for the extended staff-profile showcase fields."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffProfileFieldsTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="staff-admin@example.com",
                password="AdminPass1!",
                full_name="Staff Admin",
                phone="403-000-0019",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "staff-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _create_payload(self, **overrides) -> dict:
        payload = {
            "name": "Ava Engineer",
            "description": "Mix and master.",
            "bio": "Ava has engineered records for a decade across genres.",
            "skills": ["Pro Tools", "Mixing"],
            "talents": ["Vocal comping"],
            "services": ["Full mix", "Podcast editing"],
            "portfolio_url": "https://example.com/ava",
            "headshot_urls": ["https://img.example.com/a.jpg", "https://img.example.com/b.jpg"],
            "add_on_price_cents": 5000,
            "equipment_rental_cost_cents": 12000,
            "active": True,
        }
        payload.update(overrides)
        return payload

    def test_01_create_with_showcase_fields(self) -> None:
        headers = self._admin_headers()
        resp = self.client.post("/api/admin/staff", json=self._create_payload(), headers=headers)
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["bio"], "Ava has engineered records for a decade across genres.")
        self.assertEqual(body["services"], ["Full mix", "Podcast editing"])
        self.assertEqual(body["portfolio_url"], "https://example.com/ava")
        self.assertEqual(body["headshot_urls"], ["https://img.example.com/a.jpg", "https://img.example.com/b.jpg"])
        self.assertEqual(body["equipment_rental_cost_cents"], 12000)

    def test_02_public_staff_exposes_fields(self) -> None:
        headers = self._admin_headers()
        self.client.post("/api/admin/staff", json=self._create_payload(), headers=headers)
        resp = self.client.get("/api/staff")
        self.assertEqual(resp.status_code, 200, resp.text)
        profiles = resp.json()
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertIn("bio", profile)
        self.assertEqual(profile["equipment_rental_cost_cents"], 12000)
        self.assertEqual(profile["services"], ["Full mix", "Podcast editing"])

    def test_03_update_showcase_fields(self) -> None:
        headers = self._admin_headers()
        created = self.client.post(
            "/api/admin/staff", json=self._create_payload(), headers=headers
        ).json()
        resp = self.client.put(
            f"/api/admin/staff/{created['id']}",
            json={"bio": "Updated bio.", "equipment_rental_cost_cents": 8000, "services": ["Tracking"]},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["bio"], "Updated bio.")
        self.assertEqual(body["equipment_rental_cost_cents"], 8000)
        self.assertEqual(body["services"], ["Tracking"])

    def test_04_defaults_when_fields_omitted(self) -> None:
        headers = self._admin_headers()
        resp = self.client.post(
            "/api/admin/staff",
            json={"name": "Minimal Member", "active": True},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertIsNone(body["bio"])
        self.assertEqual(body["services"], [])
        self.assertEqual(body["headshot_urls"], [])
        self.assertIsNone(body["portfolio_url"])
        self.assertEqual(body["equipment_rental_cost_cents"], 0)
