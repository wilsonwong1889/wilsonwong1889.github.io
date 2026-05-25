"""
Backend tests — account management.

Covers: profile update, user self-delete (wrong/correct password), booking
history preserved after deletion, admin-delete user, avatar URL, reschedule,
review submit/fetch, room reviews summary.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from tests.base import BaseAppTest


class AccountTest(BaseAppTest):

    def test_35_account_management_and_deleted_user_history(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Account Ops Room",
                description="Room for account management coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "accounts-admin@example.com",
                "password": "Password123!",
                "full_name": "Accounts Admin",
                "phone": "5555551000",
            },
        )
        self.assertEqual(resp.status_code, 201)
        admin_id = resp.json()["id"]

        with self.SessionLocal() as db:
            admin_user = db.query(self.User).filter(self.User.id == admin_id).first()
            admin_user.is_admin = True
            admin_user.role = "AdminManager"
            db.commit()

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "accounts-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "history-user@example.com",
                "password": "Password123!",
                "full_name": "History User",
                "phone": "5555552000",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "history-user@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        history_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.put(
            "/api/users/me",
            headers=history_headers,
            json={
                "billing_address": {
                    "line1": "500 Studio Way",
                    "city": "Calgary",
                    "state": "AB",
                    "postal_code": "T2P1J9",
                    "country": "Canada",
                },
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("saved_payment_method", resp.json())

        resp = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        history_account = next(
            a for a in resp.json() if a["email"] == "history-user@example.com"
        )
        self.assertNotIn("saved_payment_method", history_account)
        self.assertEqual(history_account["billing_address"]["city"], "Calgary")

        start_time = self._future_time(day=5, hour=11, minute=0)
        resp = self.client.post(
            "/api/bookings",
            headers=history_headers,
            json={"room_id": room_id, "start_time": start_time.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()

        resp = self.client.request(
            "DELETE",
            "/api/users/me",
            headers=history_headers,
            json={"password": "WrongPassword123!"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Password is incorrect")

        resp = self.client.request(
            "DELETE",
            "/api/users/me",
            headers=history_headers,
            json={"password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 204)

        resp = self.client.get("/api/auth/me", headers=history_headers)
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get(
            "/api/admin/bookings?email=history-user@example.com", headers=admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(item["booking_code"] == booking["booking_code"] for item in resp.json()))
        deleted_user_booking = next(
            item for item in resp.json() if item["booking_code"] == booking["booking_code"]
        )
        self.assertEqual(deleted_user_booking["user_email"], "history-user@example.com")
        self.assertEqual(deleted_user_booking["user_full_name"], "History User")
        self.assertEqual(deleted_user_booking["user_phone"], "5555552000")

        resp = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(a["email"] == "history-user@example.com" for a in resp.json()))

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "delete-by-admin@example.com",
                "password": "Password123!",
                "full_name": "Delete By Admin",
                "phone": "5555553000",
            },
        )
        self.assertEqual(resp.status_code, 201)
        removable_user_id = resp.json()["id"]

        resp = self.client.request(
            "DELETE",
            f"/api/admin/users/{removable_user_id}",
            headers=admin_headers,
            json={"admin_password": "WrongPassword123!"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Admin password is incorrect")

        resp = self.client.request(
            "DELETE",
            f"/api/admin/users/{removable_user_id}",
            headers=admin_headers,
            json={"admin_password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 204)

        resp = self.client.get("/api/admin/users", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(a["email"] == "delete-by-admin@example.com" for a in resp.json()))

    def test_36_profile_avatar_reschedule_and_review_flow(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Review Flow Room",
                description="Room for avatar, reschedule, and review coverage",
                capacity=4,
                photos=[],
                hourly_rate_cents=5000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "reviewer@example.com",
                "password": "Password123!",
                "full_name": "Review User",
                "phone": "5555554100",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            "/api/auth/login",
            data={"username": "reviewer@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        user_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.put(
            "/api/users/me",
            headers=user_headers,
            json={
                "full_name": "Review User",
                "avatar_url": "/assets/media/avatars/example-avatar.jpg",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["avatar_url"], "/assets/media/avatars/example-avatar.jpg")

        resp = self.client.post(
            "/api/bookings",
            headers=user_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=20, hour=10, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()

        # Customers can no longer reschedule themselves — only admins can.
        resp = self.client.post(
            f"/api/bookings/{booking['id']}/reschedule",
            headers=user_headers,
            json={"start_time": self._future_time(day=20, hour=12, minute=0).isoformat()},
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "reschedule-admin@example.com",
                "password": "Password123!",
                "full_name": "Reschedule Admin",
                "phone": "5555554101",
            },
        )
        self.assertEqual(resp.status_code, 201)
        admin_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == admin_id).first()
            u.is_admin = True
            db.commit()
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "reschedule-admin@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            f"/api/bookings/{booking['id']}/reschedule",
            headers=admin_headers,
            json={"start_time": self._future_time(day=20, hour=12, minute=0).isoformat()},
        )
        self.assertEqual(resp.status_code, 200)
        rescheduled_booking = resp.json()
        self.assertEqual(
            datetime.fromisoformat(rescheduled_booking["start_time"].replace("Z", "+00:00")),
            self._future_time(day=20, hour=12).astimezone(timezone.utc),
        )

        with self.SessionLocal() as db:
            booking_row = db.query(self.Booking).filter(
                self.Booking.id == rescheduled_booking["id"]
            ).first()
            booking_row.status = "Completed"
            booking_row.confirmed_at = datetime.now(timezone.utc)
            booking_row.checked_in_at = datetime.now(timezone.utc)
            db.commit()

        resp = self.client.put(
            f"/api/bookings/{rescheduled_booking['id']}/review",
            headers=user_headers,
            json={"rating": 5, "comment": "Great room and smooth session."},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rating"], 5)

        resp = self.client.get(
            f"/api/bookings/{rescheduled_booking['id']}/review",
            headers=user_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["comment"], "Great room and smooth session.")

        resp = self.client.get(f"/api/rooms/{room_id}/reviews")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"]["review_count"], 1)
        self.assertEqual(resp.json()["reviews"][0]["rating"], 5)

    def test_37_room_rename_does_not_rewrite_booking_history(self) -> None:
        from app.models.room import Room

        with self.SessionLocal() as db:
            room = Room(
                name="Original Studio Name",
                description="Original studio description",
                capacity=4,
                photos=[],
                hourly_rate_cents=10000,
            )
            db.add(room)
            db.commit()
            db.refresh(room)
            room_id = str(room.id)

        resp = self.client.post(
            "/api/auth/signup",
            json={
                "email": "history-snapshot@example.com",
                "password": "Password123!",
                "full_name": "Snapshot User",
                "phone": "5550009100",
            },
        )
        self.assertEqual(resp.status_code, 201)
        snapshot_user_id = resp.json()["id"]
        with self.SessionLocal() as db:
            u = db.query(self.User).filter(self.User.id == snapshot_user_id).first()
            u.is_admin = True
            db.commit()
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "history-snapshot@example.com", "password": "Password123!"},
        )
        self.assertEqual(resp.status_code, 200)
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=8, hour=11, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        booking = resp.json()
        booking_id = booking["id"]
        booking_code = booking["booking_code"]
        self.assertEqual(booking["room_name_snapshot"], "Original Studio Name")
        self.assertEqual(booking["room_description_snapshot"], "Original studio description")

        resp = self.client.put(
            f"/api/admin/rooms/{room_id}",
            headers=admin_headers,
            json={
                "name": "Renamed Studio",
                "description": "Updated description after rename",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Renamed Studio")

        # Booking detail still shows the original name from the snapshot.
        resp = self.client.get(f"/api/bookings/{booking_id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["room_name_snapshot"], "Original Studio Name")
        self.assertEqual(resp.json()["room_description_snapshot"], "Original studio description")

        # Feed view (used by /bookings list) reads from the snapshot.
        resp = self.client.get("/api/bookings/feed", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        feed_item = next(item for item in resp.json() if item["id"] == booking_id)
        self.assertEqual(feed_item["room_name"], "Original Studio Name")
        self.assertEqual(feed_item["title"], "Original Studio Name")
        self.assertEqual(feed_item["subtitle"], "Original studio description")

        # Admin lookup also reads from the snapshot.
        resp = self.client.get(
            f"/api/admin/bookings?booking_code={booking_code}",
            headers=admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["room_name"], "Original Studio Name")

        # A brand-new booking after the rename uses the new name.
        resp = self.client.post(
            "/api/bookings",
            headers=admin_headers,
            json={
                "room_id": room_id,
                "start_time": self._future_time(day=9, hour=11, minute=0).isoformat(),
                "duration_minutes": 60,
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["room_name_snapshot"], "Renamed Studio")
