"""Self-service studio-engineer application: apply -> submit -> admin approve."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffApplicationTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="app-admin@example.com",
                password="AdminPass1!",
                full_name="Admin",
                phone="403-000-0150",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "app-admin@example.com", "password": "AdminPass1!"},
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _account(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Applicant", "phone": "403-555-0199"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_01_apply_submit_approve_grants_staff(self) -> None:
        applicant = self._account("eng-applicant@example.com")

        # Before applying: not staff, no profile.
        state = self.client.get("/api/staff/application", headers=applicant)
        self.assertEqual(state.status_code, 200, state.text)
        self.assertFalse(state.json()["is_staff"])
        self.assertIsNone(state.json()["profile"])

        # Submit a full profile application.
        resp = self.client.put(
            "/api/staff/application",
            headers=applicant,
            json={
                "name": "Riley Engineer",
                "role_title": "Sound Engineer",
                "bio": "10 years tracking bands.",
                "skills": ["Mixing", "Pro Tools"],
                "gear": "SM7B, Apollo Twin, Ableton",
                "portfolio_url": "https://riley.example.com",
                "headshot_urls": ["/assets/media/staff/a.jpg"],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        profile = resp.json()["profile"]
        self.assertEqual(profile["application_status"], "submitted")
        self.assertEqual(profile["gear"], "SM7B, Apollo Twin, Ableton")
        self.assertFalse(profile["active"])
        profile_id = profile["id"]

        # Still not staff yet — the portal is closed to them.
        self.assertEqual(self.client.get("/api/staff/me", headers=applicant).status_code, 403)

        # Admin sees the pending application.
        admin = self._admin_headers()
        apps = self.client.get("/api/admin/staff/applications", headers=admin)
        self.assertEqual(apps.status_code, 200, apps.text)
        match = next(a for a in apps.json() if a["id"] == profile_id)
        self.assertEqual(match["linked_user_email"], "eng-applicant@example.com")

        # Approve -> grants Staff role + activates the profile.
        approved = self.client.post(f"/api/admin/staff/{profile_id}/approve", headers=admin)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["application_status"], "approved")
        self.assertTrue(approved.json()["active"])

        # The applicant is now staff and can use the portal.
        me = self.client.get("/api/staff/me", headers=applicant)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["name"], "Riley Engineer")
        # No longer listed as a pending application.
        apps_after = self.client.get("/api/admin/staff/applications", headers=admin)
        self.assertFalse(any(a["id"] == profile_id for a in apps_after.json()))

    def test_02_application_photo_upload(self) -> None:
        import io

        from PIL import Image

        applicant = self._account("eng-photo@example.com")
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
        resp = self.client.post(
            "/api/staff/application/photo",
            files={"photo": ("head.png", buf.getvalue(), "image/png")},
            headers=applicant,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["photo_url"].startswith("/assets/media/staff/"))

    def test_03_application_requires_login(self) -> None:
        self.assertEqual(self.client.get("/api/staff/application").status_code, 401)
