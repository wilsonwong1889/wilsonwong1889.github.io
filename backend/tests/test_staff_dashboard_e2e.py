"""End-to-end staff journey mirroring the staff-dashboard.js frontend exactly:
apply -> upload photo -> admin approve -> staff self-sets weekly schedule via the
per-weekday PUT -> admin publishes -> customer requests+confirms -> staff sees the
request in their portal inbox -> staff accepts in-app. Catches wiring bugs the
per-feature unit tests miss."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffDashboardE2ETest(BaseAppTest):
    def _admin(self) -> dict:
        with self.SessionLocal() as db:
            self.ensure_admin_user(
                db, email="e2e-admin@example.com", password="AdminPass1!",
                full_name="Admin", phone="403-000-0300",
            )
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "e2e-admin@example.com", "password": "AdminPass1!"},
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _account(self, email: str) -> dict:
        self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": "TestPass1!", "full_name": "Person", "phone": "403-555-0111"},
        )
        resp = self.client.post("/api/auth/login", data={"username": email, "password": "TestPass1!"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def _png(self) -> bytes:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    def test_full_staff_journey(self) -> None:
        applicant = self._account("e2e-eng@example.com")
        admin = self._admin()

        # 1. Upload a photo as an applicant (dashboard: uploadMyApplicationPhoto).
        photo = self.client.post(
            "/api/staff/application/photo",
            files={"photo": ("head.png", self._png(), "image/png")},
            headers=applicant,
        )
        self.assertEqual(photo.status_code, 200, photo.text)
        photo_url = photo.json()["photo_url"]

        # 2. Submit the application (dashboard: submitMyStaffApplication).
        app_resp = self.client.put(
            "/api/staff/application",
            headers=applicant,
            json={
                "name": "Jordan Engineer",
                "role_title": "Mix Engineer",
                "bio": "Mixing since forever.",
                "skills": ["Mixing", "Mastering"],
                "gear": "Neve, UAD",
                "photo_url": photo_url,
                "headshot_urls": [photo_url],
            },
        )
        self.assertEqual(app_resp.status_code, 200, app_resp.text)
        profile_id = app_resp.json()["profile"]["id"]
        self.assertEqual(app_resp.json()["profile"]["photo_url"], photo_url)

        # 3. Admin approves -> grants Staff role + activates.
        approved = self.client.post(f"/api/admin/staff/{profile_id}/approve", headers=admin)
        self.assertEqual(approved.status_code, 200, approved.text)

        # 4. Staff self-edits profile via the portal (dashboard: updateMyStaffProfile).
        me = self.client.get("/api/staff/me", headers=applicant)
        self.assertEqual(me.status_code, 200, me.text)
        upd = self.client.put(
            "/api/staff/me",
            headers=applicant,
            json={"bio": "Updated bio", "skills": ["Mixing"], "photo_url": photo_url, "headshot_urls": [photo_url]},
        )
        self.assertEqual(upd.status_code, 200, upd.text)
        self.assertEqual(upd.json()["bio"], "Updated bio")

        # 5. Staff self-sets a weekly window (dashboard: setMyAvailabilityWeekday).
        start = self._future_time(day=1, hour=12)  # noon business-local
        weekday = start.weekday()
        rules = self.client.put(
            f"/api/staff/me/availability/rules/weekday/{weekday}",
            headers=applicant,
            json={"windows": [{"start_minute": 720, "end_minute": 1200}]},
        )
        self.assertEqual(rules.status_code, 200, rules.text)
        self.assertEqual(len(rules.json()), 1)

        # 6. The window the staff member set is live immediately — no admin
        # publish step. The customer sees availability right away.
        customer = self._account("e2e-cust@example.com")
        date_str = start.astimezone(__import__("zoneinfo").ZoneInfo("America/Edmonton")).date().isoformat()
        avail = self.client.get(f"/api/staff/{profile_id}/availability?date={date_str}")
        self.assertEqual(avail.status_code, 200, avail.text)
        self.assertTrue(avail.json()["available_start_times"], "Staff-set availability should be public immediately")

        # 7. The customer can request without any admin publish step.
        booking = self.client.post(
            "/api/staff-bookings",
            headers=customer,
            json={"staff_profile_id": profile_id, "start_time": start.isoformat(), "duration_minutes": 60},
        )
        self.assertEqual(booking.status_code, 201, booking.text)
        booking_id = booking.json()["id"]

        # 9. Staff should NOT see it until the customer confirms the request.
        inbox = self.client.get("/api/staff/me/booking-requests", headers=applicant)
        self.assertEqual(inbox.status_code, 200, inbox.text)
        self.assertFalse(any(b["id"] == booking_id for b in inbox.json()),
                         "Unconfirmed request must not appear in staff inbox")

        # 10. Customer confirms the request -> now it reaches the staff inbox.
        conf = self.client.post(f"/api/staff-bookings/{booking_id}/confirm-request", headers=customer)
        self.assertEqual(conf.status_code, 200, conf.text)
        inbox2 = self.client.get("/api/staff/me/booking-requests", headers=applicant)
        self.assertTrue(any(b["id"] == booking_id for b in inbox2.json()),
                        "Confirmed request should appear in staff inbox")

        # 11. Staff accepts in-app (dashboard: acceptMyBookingRequest).
        acc = self.client.post(
            f"/api/staff/me/booking-requests/{booking_id}/accept", headers=applicant
        )
        self.assertEqual(acc.status_code, 200, acc.text)
        self.assertEqual(acc.json()["status"], "AcceptedPendingPayment")

        # 12. Customer completes the free $0 confirmation.
        done = self.client.post(f"/api/staff-bookings/{booking_id}/confirm", headers=customer)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["status"], "Paid")

    def test_staff_cannot_accept_another_staffs_request(self) -> None:
        admin = self._admin()
        # Two staff profiles, each linked to its own account.
        acc_a = self._account("e2e-staff-a@example.com")
        acc_b = self._account("e2e-staff-b@example.com")
        a = self.client.post("/api/admin/staff", headers=admin, json={
            "name": "Staff A", "active": True, "schedule_published": True,
            "linked_user_email": "e2e-staff-a@example.com"}).json()
        self.client.post("/api/admin/staff", headers=admin, json={
            "name": "Staff B", "active": True, "schedule_published": True,
            "linked_user_email": "e2e-staff-b@example.com"})

        start = self._future_time(day=1, hour=12)
        self._make_staff_available_for_time(a["id"], start)
        customer = self._account("e2e-cust2@example.com")
        booking = self.client.post("/api/staff-bookings", headers=customer, json={
            "staff_profile_id": a["id"], "start_time": start.isoformat(), "duration_minutes": 60}).json()
        self.client.post(f"/api/staff-bookings/{booking['id']}/confirm-request", headers=customer)

        # Staff B must not be able to accept Staff A's request.
        resp = self.client.post(
            f"/api/staff/me/booking-requests/{booking['id']}/accept", headers=acc_b)
        self.assertEqual(resp.status_code, 404, resp.text)
