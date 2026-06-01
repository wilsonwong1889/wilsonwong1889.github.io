"""Backend tests for member-scoped monthly coupon codes."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest

# Use the current month so generated codes (start = 1st, expiry = next 1st)
# are active right now and previewable.
CURRENT_MONTH = datetime.now(timezone.utc).strftime("%Y-%m")


class MemberCouponTest(BaseAppTest):
    def _admin_headers(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db,
                email="coupon-admin@example.com",
                password="AdminPass1!",
                full_name="Coupon Admin",
                phone="403-000-0029",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "coupon-admin@example.com", "password": "AdminPass1!"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _register(self, email: str, category=None):
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Member", "phone": "403-555-0100"},
        )
        login = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        with self.SessionLocal() as db:
            user = db.query(self.User).filter(self.User.email == email).first()
            user_id = user.id
            if category:
                db.add(self.UserMembership(user_id=user.id, category=category))
                db.commit()
        return user_id, headers

    def _generate(self, headers, *, month=CURRENT_MONTH, category="artist_member", percent_off=50):
        return self.client.post(
            "/api/admin/promo-codes/generate-monthly",
            json={"month": month, "member_category": category, "percent_off": percent_off},
            headers=headers,
        )

    def test_01_generate_one_code_per_member(self) -> None:
        admin = self._admin_headers()
        self._register("a1@example.com", "artist_member")
        self._register("a2@example.com", "artist_member")
        self._register("v1@example.com", "venture_member")  # different category, excluded

        resp = self._generate(admin)
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["skipped"], 0)
        self.assertEqual(len(body["codes"]), 2)
        for code in body["codes"]:
            self.assertEqual(code["percent_off"], 50)
            self.assertTrue(code["member_unique"])
            self.assertEqual(code["member_category"], "artist_member")
            self.assertEqual(code["valid_month"], CURRENT_MONTH)
            self.assertEqual(code["max_redemptions"], 1)
            self.assertIsNotNone(code["assigned_user_id"])

    def test_02_generator_is_idempotent(self) -> None:
        admin = self._admin_headers()
        self._register("a1@example.com", "artist_member")
        first = self._generate(admin).json()
        self.assertEqual(first["created"], 1)
        second = self._generate(admin).json()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_03_assigned_code_scoped_to_owner(self) -> None:
        admin = self._admin_headers()
        owner_id, owner_headers = self._register("owner@example.com", "artist_member")
        _, other_headers = self._register("other@example.com", "artist_member")
        codes = self._generate(admin).json()["codes"]
        owner_code = next(c["code"] for c in codes if str(c["assigned_user_id"]) == str(owner_id))

        # Owner: 50% off
        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": owner_code, "amount_cents": 10000},
            headers=owner_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["discount_cents"], 5000)

        # A different member cannot use someone else's personal code
        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": owner_code, "amount_cents": 10000},
            headers=other_headers,
        )
        self.assertEqual(resp.status_code, 400, resp.text)

        # Anonymous cannot use it either
        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": owner_code, "amount_cents": 10000},
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_04_category_scoped_code(self) -> None:
        admin = self._admin_headers()
        _, artist_headers = self._register("artist@example.com", "artist_member")
        _, public_headers = self._register("public@example.com", None)
        self.client.post(
            "/api/admin/promo-codes",
            json={"code": "ARTISTONLY", "percent_off": 60, "member_category": "artist_member"},
            headers=admin,
        )

        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": "ARTISTONLY", "amount_cents": 10000},
            headers=artist_headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["discount_cents"], 6000)

        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": "ARTISTONLY", "amount_cents": 10000},
            headers=public_headers,
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_05_open_summer_code_unscoped(self) -> None:
        admin = self._admin_headers()
        # The shared "summer" 60% code is a normal open code — works anonymously.
        self.client.post(
            "/api/admin/promo-codes",
            json={"code": "SUMMER60", "percent_off": 60},
            headers=admin,
        )
        resp = self.client.post(
            "/api/public/promo-codes/preview",
            json={"code": "SUMMER60", "amount_cents": 10000},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["discount_cents"], 6000)

    def test_06_generate_requires_admin(self) -> None:
        resp = self._generate({})
        self.assertIn(resp.status_code, (401, 403), resp.text)
