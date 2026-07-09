"""
Frontend tests — JS and CSS file content.

Each test fetches a served static asset and asserts on its text content.
These verify that the correct JS views and CSS variables are being served.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.base import BaseAppTest


class JsAssetTest(BaseAppTest):

    def test_00_css_and_svg(self) -> None:
        resp = self.client.get("/assets/styles/app.css")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("--bg:", resp.text)
        # From test_41 extended checks
        self.assertIn('body[data-page="admin"] #room-form {', resp.text)
        self.assertIn('body[data-page="admin"].admin-room-modal-active #room-form:not(.hidden)', resp.text)
        self.assertIn("background: linear-gradient(135deg, var(--brand-red), #a70f16);", resp.text)
        # Admin Today Live Ops dashboard styles
        self.assertIn(".admin-today-counters", resp.text)
        self.assertIn(".admin-today-row.is-imminent", resp.text)
        self.assertIn("body.admin-printing-today", resp.text)

        resp = self.client.get("/assets/media/staff/staff-placeholder.svg")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<svg", resp.text)

    def test_01_main_js(self) -> None:
        resp = self.client.get("/assets/js/main.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("refreshSession", resp.text)
        self.assertIn('./api.js"', resp.text)
        self.assertIn('./state.js"', resp.text)
        self.assertIn('views/admin.js"', resp.text)
        self.assertIn('views/booking-detail.js"', resp.text)
        self.assertIn('views/payment-success.js"', resp.text)
        self.assertIn('views/bookings.js"', resp.text)
        self.assertIn('views/room-booking.js"', resp.text)
        self.assertIn('views/rooms.js"', resp.text)
        self.assertIn('views/room-detail.js"', resp.text)
        self.assertIn('views/info.js"', resp.text)
        self.assertIn('views/auth.js"', resp.text)
        self.assertIn('views/profile.js"', resp.text)
        self.assertNotIn("?v=", resp.text)
        # From test_41
        self.assertIn("api.getAdminAnalyticsSummary()", resp.text)
        # Admin Today Live Ops dashboard — main.js fetches the new endpoint
        self.assertIn("api.adminGetTodayRoster", resp.text)
        self.assertIn("refreshAdminToday", resp.text)

    def test_02_bookings_js(self) -> None:
        resp = self.client.get("/assets/js/views/bookings.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('../state.js"', resp.text)
        self.assertIn('let bookingHistoryTab = "upcoming";', resp.text)
        self.assertIn("Pending payment", resp.text)
        self.assertIn("No upcoming bookings yet. New room and staff reservations will appear here.", resp.text)
        self.assertIn('bookingHistoryTab = "history";', resp.text)
        self.assertIn('window.confirm("Are you sure you want to cancel this booking?")', resp.text)
        self.assertNotIn("api.previewPromoCode", resp.text)
        self.assertNotIn("booking-room-select", resp.text)

    def test_03_room_booking_js(self) -> None:
        resp = self.client.get("/assets/js/views/room-booking.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('api.previewPromoCode(code, context.amountCents)', resp.text)
        self.assertIn("reserve-promo-preview-button", resp.text)
        self.assertIn("promo_code: getReservePromoInputValue() || null", resp.text)

    def test_04_booking_detail_js(self) -> None:
        resp = self.client.get("/assets/js/views/booking-detail.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("paypal.Buttons({", resp.text)
        self.assertIn("https://www.paypal.com/sdk/js", resp.text)
        self.assertIn("api.captureBookingPayment(session.booking_id)", resp.text)
        self.assertIn('new URL("/payment-success"', resp.text)
        self.assertIn("bookingReschedulePanel", resp.text)
        self.assertIn("api.rescheduleBooking(state.selectedBooking.id", resp.text)
        self.assertIn("Skip payment as admin", resp.text)
        self.assertIn('api.adminWaiveBookingPayment(button.dataset.bookingId)', resp.text)
        self.assertIn("Mark paid manually as admin", resp.text)
        self.assertIn('api.adminMarkBookingPaid(button.dataset.bookingId)', resp.text)
        self.assertIn('window.confirm("Are you sure you want to cancel this booking?")', resp.text)
        self.assertIn("Add to calendar", resp.text)
        self.assertIn("downloadBookingCalendarFile(booking)", resp.text)
        self.assertIn("Download receipt PDF", resp.text)
        self.assertIn("downloadBookingReceiptPdf(booking.id, booking.booking_code)", resp.text)

    def test_05_payment_success_js(self) -> None:
        resp = self.client.get("/assets/js/views/payment-success.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Booking confirmed", resp.text)
        self.assertIn("You're all booked", resp.text)
        self.assertIn("Payment received — confirming your booking", resp.text)
        self.assertIn("Refresh status", resp.text)
        self.assertIn("Add to calendar", resp.text)
        self.assertIn("downloadBookingCalendarFile(currentPaymentSuccessBooking)", resp.text)
        self.assertIn("Download receipt PDF", resp.text)
        self.assertIn(
            "downloadBookingReceiptPdf(currentPaymentSuccessBooking.id, currentPaymentSuccessBooking.booking_code)",
            resp.text,
        )

    def test_06_profile_js(self) -> None:
        resp = self.client.get("/assets/js/views/profile.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('window.prompt("Enter your password to delete this account.")', resp.text)
        self.assertIn("api.uploadProfileAvatar(avatarFile)", resp.text)
        self.assertIn('api.deleteProfile({ password: deletePassword })', resp.text)

    def test_07_admin_js(self) -> None:
        resp = self.client.get("/assets/js/views/admin.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("setActiveAdminSubpage", resp.text)
        self.assertIn('document.querySelectorAll("[data-admin-subpage-button]")', resp.text)
        self.assertIn('setActiveAdminSubpage("bookings", "queue")', resp.text)
        self.assertIn('setActiveAdminSubpage("accounts", "detail")', resp.text)
        self.assertIn('data-admin-calendar-date', resp.text)
        self.assertIn('Showing day board for ${selectedAdminScheduleDate}.', resp.text)
        self.assertIn("formatMonthHeading(selectedAdminCalendarMonth)", resp.text)
        self.assertIn("Showing ${filteredBookings.length} of ${baseBookings.length}", resp.text)
        self.assertIn("Needs attention", resp.text)
        self.assertIn("admin-promo-form", resp.text)
        self.assertIn("renderAdminPromoCodes(currentState)", resp.text)
        self.assertIn("api.adminCreatePromoCode(payload)", resp.text)
        self.assertIn('setActiveAdminSubpage("bookings", "promos")', resp.text)
        self.assertIn('window.prompt("Enter your admin password to delete this account.")', resp.text)
        self.assertIn("api.adminDeleteUser(button.dataset.userId, { admin_password: adminPassword })", resp.text)
        # From test_41 extended checks
        self.assertIn("let adminRoomEditorOpen = false;", resp.text)
        self.assertIn('adminRoomEditorOpen && activeAdminTab === "rooms"', resp.text)
        self.assertIn("renderAdminDashboardMetrics(currentState)", resp.text)
        self.assertIn('analytics ? analytics.total_bookings : "Loading"', resp.text)
        self.assertIn('analytics ? formatMoney(analytics.net_revenue_cents, currency) : "Loading"', resp.text)
        self.assertNotIn("currentState.adminAnalytics?.net_revenue_cents ??", resp.text)
        self.assertIn("Mark paid", resp.text)
        self.assertIn("Refund", resp.text)
        self.assertIn("const updatedAccount = await api.adminUpdateUserRole", resp.text)
        self.assertIn("...updatedAccount", resp.text)
        self.assertIn("Process a ${amountLabel} refund? This changes payment records.", resp.text)
        self.assertIn('window.confirm("Skip payment and mark this booking free?")', resp.text)
        self.assertIn('window.confirm("Mark this booking paid manually?")', resp.text)
        self.assertIn(
            'window.confirm(`Delete ${profileName}? This will also remove the profile from any rooms.`)',
            resp.text,
        )
        # Admin Today Live Ops dashboard — renders + polling + print live in admin.js
        self.assertIn("renderAdminTodayCounters(currentState)", resp.text)
        self.assertIn("renderAdminTodayRoster(currentState)", resp.text)
        self.assertIn("renderAdminUpcomingRoster(currentState)", resp.text)
        self.assertIn("startAdminTodayPolling", resp.text)
        self.assertIn("stopAdminTodayPolling", resp.text)
        self.assertIn("window.print()", resp.text)
        self.assertIn('data-today-counter="', resp.text)
        self.assertIn("Pending arrival", resp.text)
        self.assertIn("Already arrived", resp.text)

    def test_08_rooms_js(self) -> None:
        resp = self.client.get("/assets/js/views/rooms.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('detail: { group: "rooms", subpage: "editor" }', resp.text)
        self.assertIn("elements.roomsSearchButton?.addEventListener", resp.text)
        self.assertIn("searchRoomsByAvailability", resp.text)
        self.assertIn("function escapeHtml(value)", resp.text)
        # Room cards link to the reserve flow via the buildRoomReserveUrl helper.
        self.assertIn("buildRoomReserveUrl(", resp.text)
        # From test_41
        self.assertIn('} else if (!isAdminPage()) {', resp.text)
        self.assertNotIn('elements.roomForm.classList.toggle("hidden", !canManageRooms);', resp.text)
