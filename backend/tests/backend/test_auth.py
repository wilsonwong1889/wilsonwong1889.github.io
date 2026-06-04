"""
Backend tests — authentication.

Covers: health/ready endpoints, user signup, login, profile update,
password change, login error messages, password reset.
"""
import json
import re
import sys
import os
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.base import BaseAppTest


class AuthTest(BaseAppTest):

    def test_00_health_and_ready(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

        resp = self.client.get("/ready")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ready")
        self.assertTrue(resp.json()["checks"]["database"])

    def test_01_signup_login_profile_password(self) -> None:
        signup_payload = {
            "email": "user@example.com",
            "password": "Password123!",
            "full_name": "Week One User",
            "phone": "1234567890",
        }
        resp = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(resp.status_code, 201, resp.text)
        user_id = resp.json()["id"]

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        user_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.get("/api/auth/me", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["email"], "user@example.com")

        resp = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "full_name": "Updated User",
                "birthday": "1995-07-14",
                "billing_address": {
                    "line1": "123 Booking St",
                    "line2": "Unit 4",
                    "city": "Edmonton",
                    "state": "AB",
                    "postal_code": "T5J0N3",
                    "country": "Canada",
                },
                "opt_in_sms": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["full_name"], "Updated User")
        self.assertEqual(resp.json()["birthday"], "1995-07-14")
        self.assertEqual(resp.json()["billing_address"]["city"], "Edmonton")
        self.assertNotIn("saved_payment_method", resp.json())
        self.assertTrue(resp.json()["opt_in_sms"])

        resp = self.client.put(
            "/api/users/me/password",
            headers=user_headers,
            json={"current_password": "Password123!", "new_password": "NewPassword456!"},
        )
        self.assertEqual(resp.status_code, 204)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 401)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "user@example.com", "password": "NewPassword456!"},
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/rooms")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_15_login_clears_legacy_challenge_flags(self) -> None:
        signup_payload = {
            "email": "legacy-auth-flags@example.com",
            "password": "Password123!",
            "full_name": "Legacy Auth User",
            "phone": "5552223333",
        }
        resp = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(resp.status_code, 201)

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.email == signup_payload["email"]).one()
            user.two_factor_enabled = True
            user.two_factor_method = "sms"
            user.two_factor_code_hash = "stale-code"
            user.two_factor_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            db.commit()

        resp = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["access_token"])
        self.assertNotIn("two_factor_required", payload)
        self.assertNotIn("two_factor_token", payload)

        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.email == signup_payload["email"]).one()
            self.assertFalse(user.two_factor_enabled)
            self.assertEqual(user.two_factor_method, "email")
            self.assertIsNone(user.two_factor_code_hash)
            self.assertIsNone(user.two_factor_code_expires_at)

    def test_16_login_feedback_and_password_reset_flow(self) -> None:
        signup_payload = {
            "email": "reset-user@example.com",
            "password": "Password123!",
            "full_name": "Reset User",
            "phone": "5554443333",
        }
        resp = self.client.post("/api/auth/signup", json=signup_payload)
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "not-an-email", "password": signup_payload["password"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Enter a valid email address.")

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "missing@example.com", "password": signup_payload["password"]},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Invalid email or password.")

        resp = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "WrongPassword123!"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Invalid email or password.")

        resp = self.client.post(
            "/api/auth/forgot-password",
            json={"email": signup_payload["email"]},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(
            resp.json()["message"],
            "If we found an account with that email, we sent a password reset link.",
        )

        with self.SessionLocal() as db:
            notification = (
                db.query(self.NotificationLog)
                .filter(self.NotificationLog.type == "password_reset_email_worker")
                .order_by(self.NotificationLog.created_at.desc())
                .first()
            )

        self.assertIsNotNone(notification)
        delivery_message = json.loads(notification.details["delivery"]["message"])
        token_search = re.search(r"reset_token=([A-Za-z0-9._-]+)", delivery_message["body"])
        token = token_search.group(1) if token_search else None
        self.assertIsNotNone(token)

        resp = self.client.post(
            "/api/auth/reset-password",
            json={"reset_token": token, "new_password": "NewPassword123!"},
        )
        self.assertEqual(resp.status_code, 204)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": signup_payload["password"]},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"], "Invalid email or password.")

        resp = self.client.post(
            "/api/auth/login",
            data={"username": signup_payload["email"], "password": "NewPassword123!"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["access_token"])
