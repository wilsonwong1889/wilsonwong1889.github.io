import { API_BASE_URL } from "./config.js";
import { state } from "./state.js";

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const isFormData = options.body instanceof FormData;

  if (!isFormData && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (state.token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new Error(extractErrorMessage(data));
  }

  return data;
}

// Turn a FastAPI error body into a human-readable string. `detail` may be a
// plain string (HTTPException), a list of validation errors (422), or absent.
function extractErrorMessage(data) {
  const detail =
    typeof data === "object" && data !== null && "detail" in data
      ? data.detail
      : data;

  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" ? item.msg : item))
      .filter(Boolean);
    if (messages.length) {
      return messages.join("; ");
    }
  }
  if (detail && typeof detail === "object" && typeof detail.msg === "string") {
    return detail.msg;
  }
  return "Request failed";
}

export const api = {
  getHealth() {
    return request("/health");
  },
  getPublicStaffProfiles() {
    return request("/api/staff");
  },
  signup(payload) {
    return request("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  login(email, password) {
    const formData = new FormData();
    formData.append("username", email);
    formData.append("password", password);
    return request("/api/auth/login", {
      method: "POST",
      body: formData,
    });
  },
  loginWithGoogle(accessToken) {
    return request("/api/auth/google/exchange", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken }),
    });
  },
  getMe() {
    return request("/api/auth/me");
  },
  updateProfile(payload) {
    return request("/api/users/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  uploadProfileAvatar(file) {
    const formData = new FormData();
    formData.append("photo", file);
    return request("/api/users/me/avatar", {
      method: "POST",
      body: formData,
    });
  },
  deleteProfile(payload) {
    return request("/api/users/me", {
      method: "DELETE",
      body: JSON.stringify(payload),
    });
  },
  updatePassword(payload) {
    return request("/api/users/me/password", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  getRooms(includeInactive = false) {
    const query = includeInactive ? "?include_inactive=true" : "";
    return request(`/api/rooms${query}`);
  },
  getRoom(roomId) {
    return request(`/api/rooms/${roomId}`);
  },
  getAvailability(roomId, date, holdToken = null) {
    const holdParam = holdToken ? `&hold_token=${encodeURIComponent(holdToken)}` : "";
    return request(`/api/rooms/${roomId}/availability?date=${date}${holdParam}`);
  },
  getMonthlyAvailability(month) {
    return request(`/api/availability/monthly?month=${encodeURIComponent(month)}`);
  },
  getBookings() {
    return request("/api/bookings");
  },
  getBookingsFeed() {
    return request("/api/bookings/feed").catch(() => request("/api/bookings"));
  },
  getActionRequiredCount() {
    return request("/api/bookings/action-required");
  },
  getBooking(bookingId) {
    return request(`/api/bookings/${bookingId}`);
  },
  getBookingByKind(kind, bookingId) {
    if (String(kind || "").toLowerCase() === "staff") {
      return this.getStaffBooking(bookingId).catch(() => this.getBooking(bookingId));
    }
    return this.getBooking(bookingId);
  },
  getBookingReview(bookingId) {
    return request(`/api/bookings/${bookingId}/review`);
  },
  saveBookingReview(bookingId, payload) {
    return request(`/api/bookings/${bookingId}/review`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  getBookingPaymentSession(bookingId) {
    return request(`/api/bookings/${bookingId}/payment-session`, {
      method: "POST",
    });
  },
  captureBookingPayment(bookingId) {
    return request(`/api/bookings/${bookingId}/capture-payment`, {
      method: "POST",
    });
  },
  confirmFreeBooking(bookingId) {
    return request(`/api/bookings/${bookingId}/confirm-free`, {
      method: "POST",
    });
  },
  updateBookingContact(bookingId, payload) {
    return request(`/api/bookings/${bookingId}/contact`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  createBooking(payload) {
    return request("/api/bookings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createReservationHold(payload) {
    return request("/api/bookings/reservations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  extendReservationHold(token, slotKeys) {
    return request("/api/bookings/reservations/extend", {
      method: "POST",
      body: JSON.stringify({ token, slot_keys: slotKeys || [] }),
    });
  },
  releaseReservationHold(token, slotKeys) {
    const params = new URLSearchParams();
    params.set("token", token);
    (slotKeys || []).forEach((key) => params.append("slot_keys", key));
    return request(`/api/bookings/reservations?${params.toString()}`, {
      method: "DELETE",
    });
  },
  createGuestBooking(payload) {
    return request("/api/bookings/guest", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  previewPromoCode(code, amountCents) {
    return request("/api/public/promo-codes/preview", {
      method: "POST",
      body: JSON.stringify({
        code,
        amount_cents: amountCents,
      }),
    });
  },
  submitMembershipInterest(payload) {
    return request("/api/intake/membership-interest", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  submitEngineerApplication(payload) {
    return request("/api/intake/engineer-application", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  cancelBooking(bookingId, payload) {
    return request(`/api/bookings/${bookingId}/cancel`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  rescheduleBooking(bookingId, payload) {
    return request(`/api/bookings/${bookingId}/reschedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getStaffBooking(bookingId) {
    return request(`/api/staff-bookings/${bookingId}`);
  },
  getStaffBookingPaymentSession(bookingId) {
    return request(`/api/staff-bookings/${bookingId}/payment-session`, {
      method: "POST",
    });
  },
  captureStaffBookingPayment(bookingId) {
    return request(`/api/staff-bookings/${bookingId}/capture-payment`, {
      method: "POST",
    });
  },
  updateStaffBookingContact(bookingId, payload) {
    return request(`/api/staff-bookings/${bookingId}/contact`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  cancelStaffBooking(bookingId, payload) {
    return request(`/api/staff-bookings/${bookingId}/cancel`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  confirmFreeStaffBooking(bookingId) {
    return request(`/api/staff-bookings/${bookingId}/confirm`, { method: "POST" });
  },
  confirmStaffBookingRequest(bookingId) {
    return request(`/api/staff-bookings/${bookingId}/confirm-request`, { method: "POST" });
  },
  rescheduleStaffBooking(bookingId, payload) {
    return request(`/api/staff-bookings/${bookingId}/reschedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getStaffAvailability(staffId, date) {
    return request(`/api/staff/${staffId}/availability?date=${date}`);
  },
  getStaffMonthlyAvailability(staffId, month) {
    return request(`/api/staff/${staffId}/availability/monthly?month=${encodeURIComponent(month)}`);
  },
  createStaffBooking(payload) {
    return request("/api/staff-bookings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createGuestStaffBooking(payload) {
    return request("/api/staff-bookings/guest", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getRoomReviews(roomId, limit = 6) {
    return request(`/api/rooms/${roomId}/reviews?limit=${limit}`);
  },
  createRoom(payload) {
    return request("/api/rooms", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  archiveRoom(roomId) {
    return request(`/api/rooms/${roomId}`, {
      method: "DELETE",
    });
  },
  deleteRoomPermanently(roomId) {
    return request(`/api/rooms/${roomId}/permanent`, {
      method: "DELETE",
    });
  },
  restoreRoom(roomId) {
    return request(`/api/rooms/${roomId}/restore`, {
      method: "POST",
    });
  },
  adminLookupBookings(query) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value) {
        params.set(key, value);
      }
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request(`/api/admin/bookings${suffix}`);
  },
  adminGetTodayRoster() {
    return request("/api/admin/today");
  },
  adminClearBookingsForDay(payload) {
    return request("/api/admin/bookings/clear-day", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminClearPastBookings() {
    return request("/api/admin/bookings/clear-past", {
      method: "POST",
    });
  },
  getAdminAnalyticsSummary() {
    return request("/api/admin/analytics/summary");
  },
  getAdminUsers() {
    return request("/api/admin/users");
  },
  getAdminTestCases() {
    return request("/api/admin/test-cases");
  },
  getAdminActivity(limit = 12) {
    return request(`/api/admin/activity?limit=${limit}`);
  },
  getAdminNotifications({ limit = 50, status = "", type = "" } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set("status", status);
    if (type) params.set("type", type);
    return request(`/api/admin/notifications?${params.toString()}`);
  },
  getAdminStaffProfiles() {
    return request("/api/admin/staff");
  },
  getAdminPromoCodes() {
    return request("/api/admin/promo-codes");
  },
  adminCreatePromoCode(payload) {
    return request("/api/admin/promo-codes", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminUpdatePromoCode(promoCodeId, payload) {
    return request(`/api/admin/promo-codes/${promoCodeId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  adminCreateMemberCode(payload) {
    return request("/api/admin/promo-codes/member", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminGenerateMonthlyMemberCodes(payload) {
    return request("/api/admin/promo-codes/generate-monthly", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminCreateStaffProfile(payload) {
    return request("/api/admin/staff", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminUpdateStaffProfile(staffProfileId, payload) {
    return request(`/api/admin/staff/${staffProfileId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  adminDeleteStaffProfile(staffProfileId) {
    return request(`/api/admin/staff/${staffProfileId}`, {
      method: "DELETE",
    });
  },
  adminUploadStaffPhoto(file) {
    const formData = new FormData();
    formData.append("photo", file);
    return request("/api/admin/staff/photo", {
      method: "POST",
      body: formData,
    });
  },
  adminUploadRoomPhoto(file) {
    const formData = new FormData();
    formData.append("photo", file);
    return request("/api/admin/rooms/photo", {
      method: "POST",
      body: formData,
    });
  },
  adminCreateManualBooking(payload) {
    return request("/api/admin/bookings/manual", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminRefundBooking(bookingId, payload) {
    return request(`/api/admin/bookings/${bookingId}/refund`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  adminCheckInBooking(bookingId) {
    return request(`/api/admin/bookings/${bookingId}/check-in`, {
      method: "POST",
    });
  },
  adminWaiveBookingPayment(bookingId) {
    return request(`/api/admin/bookings/${bookingId}/waive-payment`, {
      method: "POST",
    });
  },
  adminMarkBookingPaid(bookingId) {
    return request(`/api/admin/bookings/${bookingId}/mark-paid`, {
      method: "POST",
    });
  },
  adminWaiveStaffBookingPayment(bookingId) {
    return request(`/api/admin/staff-bookings/${bookingId}/waive-payment`, {
      method: "POST",
    });
  },
  adminMarkStaffBookingPaid(bookingId) {
    return request(`/api/admin/staff-bookings/${bookingId}/mark-paid`, {
      method: "POST",
    });
  },
  adminDeleteUser(userId, payload) {
    return request(`/api/admin/users/${userId}`, {
      method: "DELETE",
      body: JSON.stringify(payload),
    });
  },
  adminUpdateUserRole(userId, payload) {
    return request(`/api/admin/users/${userId}/role`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  adminUpdateUserMembership(userId, payload) {
    return request(`/api/admin/users/${userId}/membership`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  adminUpdateRoom(roomId, payload) {
    return request(`/api/admin/rooms/${roomId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  getAdminIntakes(query = {}) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value) {
        params.set(key, value);
      }
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request(`/api/admin/intakes${suffix}`);
  },
  adminUpdateIntakeStatus(intakeId, status) {
    return request(`/api/admin/intakes/${intakeId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  },
  getAdminStaffSchedule(date) {
    return request(`/api/admin/staff/schedule?date=${encodeURIComponent(date)}`);
  },
  getMyStaffProfile() {
    return request("/api/staff/me");
  },
  getMyAvailabilityRules() {
    return request("/api/staff/me/availability/rules");
  },
  createMyAvailabilityRulesBulk(payload) {
    return request("/api/staff/me/availability/rules/bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  setMyAvailabilityWeekday(weekday, windows) {
    return request(`/api/staff/me/availability/rules/weekday/${weekday}`, {
      method: "PUT",
      body: JSON.stringify({ windows: windows || [] }),
    });
  },
  createMyAvailabilityRule(payload) {
    return request("/api/staff/me/availability/rules", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteMyAvailabilityRule(ruleId) {
    return request(`/api/staff/me/availability/rules/${ruleId}`, { method: "DELETE" });
  },
  getMyAvailabilityExceptions() {
    return request("/api/staff/me/availability/exceptions");
  },
  createMyAvailabilityException(payload) {
    return request("/api/staff/me/availability/exceptions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteMyAvailabilityException(exceptionId) {
    return request(`/api/staff/me/availability/exceptions/${exceptionId}`, { method: "DELETE" });
  },
  updateMyStaffProfile(payload) {
    return request("/api/staff/me", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  uploadMyStaffPhoto(file) {
    const formData = new FormData();
    formData.append("photo", file);
    return request("/api/staff/me/photo", {
      method: "POST",
      body: formData,
    });
  },
  getMyStaffApplication() {
    return request("/api/staff/application");
  },
  submitMyStaffApplication(payload) {
    return request("/api/staff/application", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  uploadMyApplicationPhoto(file) {
    const formData = new FormData();
    formData.append("photo", file);
    return request("/api/staff/application/photo", {
      method: "POST",
      body: formData,
    });
  },
  adminListStaffApplications() {
    return request("/api/admin/staff/applications");
  },
  adminApproveStaffApplication(staffProfileId) {
    return request(`/api/admin/staff/${staffProfileId}/approve`, { method: "POST" });
  },
  getMyBookingRequests() {
    return request("/api/staff/me/booking-requests");
  },
  acceptMyBookingRequest(bookingId) {
    return request(`/api/staff/me/booking-requests/${bookingId}/accept`, { method: "POST" });
  },
  declineMyBookingRequest(bookingId, reason) {
    return request(`/api/staff/me/booking-requests/${bookingId}/decline`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    });
  },
};
