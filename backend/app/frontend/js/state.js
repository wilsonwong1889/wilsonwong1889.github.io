import { STORAGE_KEYS } from "./config.js";

const listeners = new Set();

export const state = {
  token: localStorage.getItem(STORAGE_KEYS.token),
  currentUser: null,
  rooms: [],
  roomAvailabilityPreview: {},
  roomPreviewDate: new Date().toISOString().slice(0, 10),
  roomAvailabilitySearch: {
    date: new Date().toISOString().slice(0, 10),
    time: "15:00",
    duration: 60,
    matchingRoomIds: [],
    hasSearched: false,
    mode: "exact",
  },
  bookings: [],
  actionRequiredCount: 0,
  adminBookings: [],
  adminTodayRoster: null,
  adminAnalytics: null,
  adminActivity: [],
  adminUsers: [],
  adminTestCases: [],
  adminStaffProfiles: [],
  adminPromoCodes: [],
  adminIntakes: [],
  publicStaffProfiles: [],
  selectedRoom: null,
  selectedRoomReviews: [],
  selectedRoomReviewSummary: null,
  selectedBooking: null,
  selectedBookingKind: null,
  selectedBookingReview: null,
  availability: null,
  health: null,
  showInactiveRooms: false,
  message: "Ready.",
};

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setState(patch) {
  Object.assign(state, patch);
  listeners.forEach((listener) => listener(state));
}

export function persistToken(token) {
  if (token) {
    localStorage.setItem(STORAGE_KEYS.token, token);
  } else {
    localStorage.removeItem(STORAGE_KEYS.token);
  }
  setState({ token });
}

export function getPersistedLastBookingId() {
  return localStorage.getItem(STORAGE_KEYS.lastBookingId);
}

export function persistLastBookingId(bookingId) {
  if (bookingId) {
    localStorage.setItem(STORAGE_KEYS.lastBookingId, String(bookingId));
    return;
  }
  localStorage.removeItem(STORAGE_KEYS.lastBookingId);
}

export function getPersistedCheckoutDraft() {
  const value = localStorage.getItem(STORAGE_KEYS.checkoutDraft);
  if (!value) {
    return null;
  }

  try {
    return JSON.parse(value);
  } catch (_error) {
    localStorage.removeItem(STORAGE_KEYS.checkoutDraft);
    return null;
  }
}

export function persistCheckoutDraft(draft) {
  if (!draft) {
    localStorage.removeItem(STORAGE_KEYS.checkoutDraft);
    return;
  }

  localStorage.setItem(
    STORAGE_KEYS.checkoutDraft,
    JSON.stringify({
      ...draft,
      saved_at: new Date().toISOString(),
    }),
  );
}
