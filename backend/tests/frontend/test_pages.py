"""
Frontend tests — HTML page content.

Each test makes a GET request to a served page and asserts on static HTML
structure. No database mutations; these verify the HTML templates are correct.
"""
import re
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.base import BaseAppTest


class PageContentTest(BaseAppTest):

    def test_00_all_pages_return_200(self) -> None:
        for path in ("/", "/account", "/pricing", "/rooms", "/room", "/reserve",
                     "/staff", "/staff-dashboard", "/bookings", "/booking",
                     "/payment-success", "/admin"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"{path} returned {resp.status_code}")

    def test_01_home_page(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Creative Innovation Hub", resp.text)
        self.assertIn("2525 36 St N, Lethbridge, AB T1H 5L1", resp.text)
        self.assertIn("403-393-8857", resp.text)
        self.assertIn("lethsmakeithappen@bipocfoundation.org", resp.text)
        self.assertIn("Wednesday to Saturday 12:00 PM &ndash; 8:00 PM", resp.text)
        self.assertIn("home-booking-search", resp.text)
        self.assertIn("Book now", resp.text)
        self.assertNotIn("home-stats-band", resp.text)
        self.assertIn("BIPOC Digital Media &amp; Creative Innovation Hub", resp.text)
        self.assertIn("home-carousel-button-prev", resp.text)
        self.assertIn("home-carousel-dots", resp.text)
        self.assertIn("Studio location on Google Maps", resp.text)
        self.assertIn("header-user-menu-shell", resp.text)
        self.assertIn("header-user-trigger", resp.text)
        self.assertIn("header-profile-link", resp.text)
        self.assertIn("header-bookings-link", resp.text)
        self.assertNotIn('id="rooms-grid"', resp.text)
        self.assertIn('/assets/styles/app.css?v=', resp.text)

    def test_01b_social_icons_point_at_real_social_accounts(self) -> None:
        """They shipped pointing at /contact, so clicking Facebook landed the
        visitor on a contact page rather than Facebook."""
        expected = {
            "facebook.com/bipocfoundation",
            "instagram.com/bipocfoundation",
            "youtube.com/channel/",
        }
        for path in ("/", "/rooms", "/pricing", "/contact"):
            with self.subTest(path=path):
                html = self.client.get(path).text
                links = re.findall(r'home-social-link" href="([^"]+)"', html)
                self.assertTrue(links, f"no social links on {path}")
                for href in links:
                    self.assertTrue(
                        href.startswith("https://"),
                        f"{path}: social link is not an external URL: {href}",
                    )
                self.assertNotIn("/contact", links)
                for fragment in expected:
                    self.assertTrue(
                        any(fragment in href for href in links),
                        f"{path}: no link matching {fragment}",
                    )
                # New tab on someone else's origin needs noopener.
                self.assertIn('rel="noopener noreferrer"', html)

    def test_02_pricing_page(self) -> None:
        resp = self.client.get("/pricing")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Pricing & membership", resp.text)
        self.assertIn("$50/hr", resp.text)
        self.assertIn("$15", resp.text)
        self.assertIn("Now Open", resp.text)
        # The launch dates are past; they must not creep back in.
        self.assertNotIn("Open Studio Night", resp.text)
        self.assertNotIn("Grand opening", resp.text)
        self.assertNotIn("60% beta", resp.text)

    def test_02b_pages_name_every_studio_that_is_open(self) -> None:
        """The homepage claimed two studios while the rooms API returned five,
        and the pricing page listed two of them. If a sixth studio opens, this
        should fail until the copy is updated with it."""
        studios = (
            "Conference Room",
            "Large Photography / Videography Studio",
            "Precision / Brand Studio &amp; Editing Suite",
            "Sound Engineering / Recording Studio",
            "Podcast Studio",
        )
        pricing = self.client.get("/pricing").text
        for studio in studios:
            with self.subTest(studio=studio):
                self.assertIn(studio, pricing)

        home = self.client.get("/").text
        self.assertIn("Five studios open for booking now", home)
        self.assertNotIn("Two studios", home)

    def test_03_account_page(self) -> None:
        resp = self.client.get("/account")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Delete profile", resp.text)
        self.assertNotIn("Require two-factor verification at login", resp.text)
        self.assertNotIn("login-2fa-form", resp.text)
        self.assertIn("forgot-password-form", resp.text)
        self.assertIn("reset-password-form", resp.text)
        self.assertIn("Forgot password?", resp.text)
        self.assertIn("Confirm password", resp.text)
        self.assertIn("signup-password-match-feedback", resp.text)
        self.assertIn("reset-password-match-feedback", resp.text)
        self.assertIn("profile-password-match-feedback", resp.text)
        self.assertIn("profile-avatar-file", resp.text)
        self.assertIn("profile-avatar-preview", resp.text)
        self.assertIn("account-danger-zone", resp.text)
        self.assertIn('/assets/styles/app.css?v=', resp.text)

    def test_04_bookings_page(self) -> None:
        resp = self.client.get("/bookings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("My Bookings", resp.text)
        self.assertIn("Manage room and staff bookings in one place without switching flows.", resp.text)
        self.assertIn("Book room", resp.text)
        self.assertIn("Book staff", resp.text)
        self.assertIn("Upcoming reservations", resp.text)
        self.assertIn("Past &amp; cancelled", resp.text)
        self.assertIn("booking-history-upcoming-tab", resp.text)
        self.assertIn("booking-history-history-tab", resp.text)
        self.assertIn("booking-history-upcoming-count", resp.text)
        self.assertIn("booking-history-history-count", resp.text)
        self.assertIn("recent-bookings-shell", resp.text)
        self.assertIn("pending-bookings-list", resp.text)
        self.assertIn("recent-bookings-list", resp.text)
        self.assertIn('/assets/styles/app.css?v=', resp.text)

    def test_05_booking_page(self) -> None:
        resp = self.client.get("/booking")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Ready to book a studio?", resp.text)
        self.assertIn("booking-detail-empty", resp.text)
        self.assertIn("booking-detail-card", resp.text)
        self.assertIn("Booking summary", resp.text)
        self.assertIn("Payment details", resp.text)
        self.assertIn("Back to bookings", resp.text)
        self.assertIn('/assets/styles/app.css?v=', resp.text)

    def test_06_reserve_page(self) -> None:
        resp = self.client.get("/reserve")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("continue as a guest", resp.text)
        self.assertIn("reserve-promo-code-input", resp.text)
        self.assertIn("reserve-promo-preview-button", resp.text)
        self.assertIn("reserve-promo-feedback", resp.text)

    def test_06b_staff_pages(self) -> None:
        resp = self.client.get("/staff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("staff-booking-calendar-panel", resp.text)
        self.assertIn("staff-booking-month-grid", resp.text)
        self.assertIn("staff-booking-prev-month", resp.text)
        self.assertIn("staff-booking-next-month", resp.text)

        dashboard = self.client.get("/staff-dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("staff-dashboard-month-grid", dashboard.text)
        self.assertIn("staff-dashboard-selected-date-label", dashboard.text)
        self.assertIn('data-staff-calendar-action="available"', dashboard.text)

    def test_07_admin_page(self) -> None:
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Accounts", resp.text)
        self.assertIn("Backend test cases", resp.text)
        self.assertIn("admin-panel-accounts", resp.text)
        self.assertIn("admin-panel-qa", resp.text)
        self.assertIn("admin-booking-quick-summary", resp.text)
        self.assertIn("admin-booking-quick-filters", resp.text)
        self.assertIn('data-admin-subpage-group="bookings"', resp.text)
        self.assertIn('data-admin-subpage-group="staff"', resp.text)
        self.assertIn('data-admin-subpage-group="rooms"', resp.text)
        self.assertIn("Room calendar", resp.text)
        self.assertIn("admin-calendar-month", resp.text)
        self.assertIn("admin-room-calendar-grid", resp.text)
        self.assertIn("Promos", resp.text)
        self.assertIn("admin-promo-form", resp.text)
        self.assertIn("admin-promo-codes-list", resp.text)
        self.assertIn("admin-accounts-list", resp.text)
        self.assertIn("admin-test-case-summary", resp.text)
        self.assertIn("admin-test-cases-list", resp.text)
        self.assertIn('id="admin-staff-schedule-date"', resp.text)
        self.assertEqual(resp.text.count('id="admin-staff-schedule-date"'), 1)
        self.assertEqual(resp.text.count('id="admin-schedule-date"'), 1)
        self.assertIn('/assets/styles/app.css?v=', resp.text)
        self.assertLess(resp.text.index("Room management"), resp.text.index("Backend test cases"))
        # From test_41 extended checks
        self.assertIn("Dashboard", resp.text)
        self.assertIn("admin-dashboard-metrics", resp.text)
        self.assertIn("admin-panel-bookings", resp.text)
        self.assertIn("admin-panel-rooms", resp.text)
        self.assertIn("admin-panel-staff", resp.text)
        self.assertIn("admin-panel-roles", resp.text)
        self.assertIn('data-admin-create-room="true"', resp.text)
        self.assertIn('class="header-brand-block"', resp.text)
        self.assertIn("Live booking queue", resp.text)
        self.assertNotIn("[object Object]", resp.text)
        self.assertNotIn("TODO", resp.text)
