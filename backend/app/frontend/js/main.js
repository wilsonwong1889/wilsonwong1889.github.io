import { api } from "./api.js";
import { CURRENT_PAGE, getSearchParam } from "./config.js";
import {
  getPersistedCheckoutDraft,
  getPersistedLastBookingId,
  persistCheckoutDraft,
  persistLastBookingId,
  setState,
  state,
  subscribe,
  persistToken,
} from "./state.js";
import { initAdminView, renderAdminView } from "./views/admin.js";
import { initAuthView, renderAuthView } from "./views/auth.js";
import { initBookingDetailView, renderBookingDetailView } from "./views/booking-detail.js";
import { initBookingsView, renderBookingsView } from "./views/bookings.js";
import { initHomeView, renderHomeView } from "./views/home.js";
import { initInfoView, renderInfoView } from "./views/info.js";
import { initPaymentSuccessView, renderPaymentSuccessView } from "./views/payment-success.js";
import { initProfileView, renderProfileView } from "./views/profile.js";
import { initRoomBookingView, renderRoomBookingView } from "./views/room-booking.js";
import { initRoomDetailView, renderRoomDetailView } from "./views/room-detail.js";
import { initRoomsView, renderRoomsView } from "./views/rooms.js";
import { initStaffDirectoryView, renderStaffDirectoryView } from "./views/staff-directory.js";
import { renderStatus } from "./views/status.js";

const PAGE_DATA_REQUIREMENTS = {
  home: { rooms: true, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  account: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  contact: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  faq: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  info: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  pricing: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  programming: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: false },
  rooms: { rooms: true, bookings: false, admin: false, selectedRoom: false, selectedBooking: false },
  room: { rooms: false, bookings: false, admin: false, selectedRoom: true, selectedBooking: false },
  reserve: { rooms: false, bookings: false, admin: false, selectedRoom: true, selectedBooking: false },
  staff: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: false, publicStaff: true },
  bookings: { rooms: true, bookings: true, admin: false, selectedRoom: false, selectedBooking: false },
  booking: { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: true },
  "payment-success": { rooms: false, bookings: false, admin: false, selectedRoom: false, selectedBooking: true },
  admin: { rooms: true, bookings: false, admin: true, selectedRoom: false, selectedBooking: false },
};

function currentRequirements() {
  return PAGE_DATA_REQUIREMENTS[CURRENT_PAGE] || PAGE_DATA_REQUIREMENTS.home;
}

// Hide broken images gracefully
document.querySelectorAll("img").forEach((img) => {
  img.addEventListener("error", () => { img.style.display = "none"; });
  if (img.complete && img.naturalWidth === 0) img.style.display = "none";
});

// Mobile navigation toggle
(function initMobileNav() {
  const toggle = document.getElementById("mobile-nav-toggle");
  const header = toggle?.closest(".site-header");
  const nav = document.getElementById("site-nav");
  if (!toggle || !header || !nav) return;

  const OPEN_SVG = '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="4" y1="4" x2="18" y2="18"/><line x1="18" y1="4" x2="4" y2="18"/></svg>';
  const CLOSED_SVG = '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="3" y1="6" x2="19" y2="6"/><line x1="3" y1="11" x2="19" y2="11"/><line x1="3" y1="16" x2="19" y2="16"/></svg>';

  function openNav() {
    header.classList.add("nav-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.innerHTML = OPEN_SVG;
  }

  function closeNav() {
    header.classList.remove("nav-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = CLOSED_SVG;
  }

  toggle.addEventListener("click", () => {
    if (header.classList.contains("nav-open")) closeNav(); else openNav();
  });

  nav.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", closeNav);
  });

  document.addEventListener("click", (e) => {
    if (header.classList.contains("nav-open") && !header.contains(e.target)) closeNav();
  });
}());

// Inject icons into nav links on all pages
(function injectNavIcons() {
  const ICONS = {
    "/": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z"/><polyline points="9 21 9 12 15 12 15 21"/></svg>`,
    "/staff": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>`,
    "/rooms": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
    "/pricing": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>`,
    "/services": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>`,
    "/programming": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>`,
    "/bookings": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
    "/faq": `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  };
  document.querySelectorAll(".site-nav .nav-link").forEach((link) => {
    const icon = ICONS[link.getAttribute("href")];
    if (icon) {
      const text = link.textContent.trim();
      link.innerHTML = `${icon}<span>${text}</span>`;
    }
  });
}());

function getBookingKind(booking, fallbackKind = null) {
  const explicitKind = String(booking?.booking_kind || booking?.kind || fallbackKind || "").toLowerCase();
  if (explicitKind === "staff") {
    return "staff";
  }
  if (explicitKind === "room") {
    return "room";
  }
  if (booking?.staff_profile_id || booking?.staff_profile_name || booking?.staff_name || booking?.service_type) {
    return "staff";
  }
  return "room";
}

function normalizeBookingRecord(booking, fallbackKind = null) {
  if (!booking) {
    return booking;
  }

  const kind = getBookingKind(booking, fallbackKind);
  const staffName =
    booking.staff_name ||
    booking.staff_profile_name ||
    booking.staff_profile?.name ||
    booking.service_type ||
    booking.room_name ||
    "Staff booking";
  return {
    ...booking,
    booking_kind: kind,
    kind,
    room_name: kind === "staff" ? staffName : booking.room_name,
    staff_name: kind === "staff" ? staffName : booking.staff_name,
    staff_photo_url: booking.staff_photo_url || booking.staff_profile?.photo_url || booking.staff_profile?.avatar_url || null,
    location_label: booking.location_label || booking.room_location || (kind === "staff" ? "Staff session" : "Downtown studio district"),
  };
}

function renderApp(currentState) {
  renderHomeView(currentState);
  renderStatus(currentState);
  renderAuthView(currentState);
  renderAdminView(currentState);
  renderBookingsView(currentState);
  renderBookingDetailView(currentState);
  renderInfoView(currentState);
  renderPaymentSuccessView(currentState);
  renderProfileView(currentState);
  renderRoomBookingView(currentState);
  renderRoomDetailView(currentState);
  renderRoomsView(currentState);
  renderStaffDirectoryView(currentState);
}

function initRevealAnimations() {
  const revealNodes = Array.from(document.querySelectorAll("[data-reveal]"));
  if (!revealNodes.length) {
    return;
  }

  const stagedNodes = revealNodes.filter((node) => !node.dataset.reveal.startsWith("hero"));
  if (!stagedNodes.length) {
    return;
  }

  if (!("IntersectionObserver" in window)) {
    stagedNodes.forEach((node) => node.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }

        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    {
      threshold: 0.18,
      rootMargin: "0px 0px -8% 0px",
    },
  );

  stagedNodes.forEach((node, index) => {
    node.dataset.revealDelay = String(Math.min(index, 4));
    observer.observe(node);
  });
}

function resetScopedData() {
  const requirements = currentRequirements();
  const patch = {};

  if (!requirements.rooms) {
    patch.rooms = [];
    patch.roomAvailabilityPreview = {};
    patch.roomAvailabilitySearch = {
      date: new Date().toISOString().slice(0, 10),
      time: "15:00",
      duration: 60,
      matchingRoomIds: [],
      hasSearched: false,
    };
    patch.showInactiveRooms = false;
  }
  if (!requirements.bookings) {
    patch.bookings = [];
    patch.availability = null;
  }
  if (!requirements.admin) {
    patch.adminBookings = [];
    patch.adminAnalytics = null;
    patch.adminActivity = [];
    patch.adminUsers = [];
    patch.adminTestCases = [];
    patch.adminStaffProfiles = [];
    patch.adminPromoCodes = [];
  }
  if (!requirements.publicStaff) {
    patch.publicStaffProfiles = [];
  }
  if (!requirements.selectedRoom) {
    patch.selectedRoom = null;
    patch.selectedRoomReviews = [];
    patch.selectedRoomReviewSummary = null;
  }
  if (!requirements.selectedBooking) {
    patch.selectedBooking = null;
    patch.selectedBookingKind = null;
    patch.selectedBookingReview = null;
  }

  if (Object.keys(patch).length) {
    setState(patch);
  }
}

async function loadHealth() {
  try {
    const health = await api.getHealth();
    setState({ health, message: "Backend connected." });
  } catch (error) {
    setState({ health: false, message: error.message });
  }
}

async function refreshRooms(message) {
  if (!currentRequirements().rooms) {
    return;
  }

  try {
    const shouldIncludeInactive = Boolean(
      state.currentUser?.is_admin && state.showInactiveRooms,
    );
    const rooms = await api.getRooms(shouldIncludeInactive);
    setState({ rooms, message: message || "Rooms loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshBookings(message) {
  if (!currentRequirements().bookings) {
    return;
  }

  if (!state.token) {
    setState({ bookings: [], availability: null, message: message || "Signed out." });
    return;
  }

  try {
    const bookings = await api.getBookingsFeed();
    setState({
      bookings: bookings.map((booking) => normalizeBookingRecord(booking)),
      message: message || "Bookings loaded.",
    });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminBookings(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminBookings: [], message: message || state.message });
    return;
  }

  try {
    const adminBookings = await api.adminLookupBookings({});
    setState({ adminBookings, message: message || "Admin bookings loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminAnalytics(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminAnalytics: null, message: message || state.message });
    return;
  }

  try {
    const adminAnalytics = await api.getAdminAnalyticsSummary();
    setState({ adminAnalytics, message: message || "Admin analytics loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminActivity(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminActivity: [], message: message || state.message });
    return;
  }

  try {
    const adminActivity = await api.getAdminActivity();
    setState({ adminActivity, message: message || "Admin activity loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminUsers(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminUsers: [], message: message || state.message });
    return;
  }

  try {
    const adminUsers = await api.getAdminUsers();
    setState({ adminUsers, message: message || "Accounts loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminTestCases(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminTestCases: [], message: message || state.message });
    return;
  }

  try {
    const adminTestCases = await api.getAdminTestCases();
    setState({ adminTestCases, message: message || "Backend test cases loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminStaffProfiles(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminStaffProfiles: [], message: message || state.message });
    return;
  }

  try {
    const adminStaffProfiles = await api.getAdminStaffProfiles();
    setState({ adminStaffProfiles, message: message || "Staff profiles loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshAdminPromoCodes(message) {
  if (!currentRequirements().admin) {
    return;
  }

  if (!state.currentUser?.is_admin) {
    setState({ adminPromoCodes: [], message: message || state.message });
    return;
  }

  try {
    const adminPromoCodes = await api.getAdminPromoCodes();
    setState({ adminPromoCodes, message: message || "Promo codes loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function refreshPublicStaffProfiles(message) {
  if (!currentRequirements().publicStaff) {
    return;
  }

  try {
    const publicStaffProfiles = await api.getPublicStaffProfiles();
    setState({ publicStaffProfiles, message: message || "Staff directory loaded." });
  } catch (error) {
    setState({ message: error.message });
  }
}

async function loadSelectedRoom(message) {
  if (!currentRequirements().selectedRoom) {
    return;
  }

  const roomId = getSearchParam("id");
  if (!roomId) {
    setState({ selectedRoom: null, message: "Room id is missing." });
    return;
  }

  try {
    const selectedRoom = await api.getRoom(roomId);
    const reviewFeed = await api.getRoomReviews(roomId).catch(() => ({
      summary: null,
      reviews: [],
    }));
    setState({
      selectedRoom,
      selectedRoomReviews: reviewFeed.reviews || [],
      selectedRoomReviewSummary: reviewFeed.summary || null,
      message: message || "Room loaded.",
    });
  } catch (error) {
    setState({
      selectedRoom: null,
      selectedRoomReviews: [],
      selectedRoomReviewSummary: null,
      message: error.message,
    });
  }
}

async function loadSelectedBooking(message) {
  if (!currentRequirements().selectedBooking) {
    return;
  }

  const explicitBookingId = getSearchParam("id");
  const requestedKind = String(getSearchParam("kind") || "").toLowerCase() || null;
  const persistedBookingId = getPersistedLastBookingId();
  const persistedCheckoutDraft = getPersistedCheckoutDraft();
  const checkoutDraftKind = String(persistedCheckoutDraft?.kind || persistedCheckoutDraft?.booking?.booking_kind || "").toLowerCase() || null;
  const bookingKind = requestedKind || checkoutDraftKind || null;

  let bookingId = explicitBookingId || persistedBookingId || persistedCheckoutDraft?.booking?.id;
  if (!bookingId && state.token) {
    try {
      const bookings = (await api.getBookingsFeed()).map((booking) => normalizeBookingRecord(booking));
      const prioritizedBooking =
        bookings.find((booking) => booking.status === "PendingPayment" && (!bookingKind || booking.booking_kind === bookingKind))
        || bookings.find((booking) => booking.status === "PendingPayment")
        || bookings.find((booking) => booking.status === "Paid" && (!bookingKind || booking.booking_kind === bookingKind))
        || bookings.find((booking) => booking.status === "Paid")
        || bookings[0];
      if (prioritizedBooking?.id) {
        bookingId = prioritizedBooking.id;
        persistLastBookingId(bookingId);
      }
    } catch (error) {
      setState({ message: error.message });
    }
  }

  if (!bookingId) {
    setState({
      selectedBooking: null,
      selectedBookingKind: bookingKind,
      message: "Start from Rooms or My Bookings to open the active checkout with the correct booking details.",
    });
    return;
  }

  if (!explicitBookingId) {
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("id", bookingId);
    if (bookingKind) {
      nextUrl.searchParams.set("kind", bookingKind);
    }
    window.history.replaceState({}, "", nextUrl);
  }

  try {
    const selectedBooking = normalizeBookingRecord(
      await api.getBookingByKind(bookingKind, bookingId),
      bookingKind,
    );
    const selectedBookingReview = await api.getBookingReview(bookingId).catch(() => null);
    persistLastBookingId(selectedBooking.id);
    if (selectedBooking.status !== "PendingPayment") {
      persistCheckoutDraft(null);
    } else {
      persistCheckoutDraft({ booking: selectedBooking, kind: selectedBooking.booking_kind });
    }
    setState({
      selectedBooking,
      selectedBookingKind: selectedBooking.booking_kind,
      selectedBookingReview,
      message: message || "Booking loaded.",
    });
  } catch (error) {
    if (!explicitBookingId && state.token) {
      try {
        const bookings = (await api.getBookingsFeed()).map((booking) => normalizeBookingRecord(booking));
        const fallbackBooking =
          bookings.find((booking) => booking.status === "PendingPayment" && (!bookingKind || booking.booking_kind === bookingKind))
          || bookings.find((booking) => booking.status === "PendingPayment")
          || bookings.find((booking) => booking.status === "Paid" && (!bookingKind || booking.booking_kind === bookingKind))
          || bookings.find((booking) => booking.status === "Paid")
          || bookings[0];
        if (fallbackBooking?.id && fallbackBooking.id !== bookingId) {
          persistLastBookingId(fallbackBooking.id);
          const nextUrl = new URL(window.location.href);
          nextUrl.searchParams.set("id", fallbackBooking.id);
          if (fallbackBooking.booking_kind) {
            nextUrl.searchParams.set("kind", fallbackBooking.booking_kind);
          }
          window.history.replaceState({}, "", nextUrl);
          const selectedBooking = normalizeBookingRecord(
            await api.getBookingByKind(fallbackBooking.booking_kind, fallbackBooking.id),
            fallbackBooking.booking_kind,
          );
          const selectedBookingReview = await api.getBookingReview(fallbackBooking.id).catch(() => null);
          setState({
            selectedBooking,
            selectedBookingKind: selectedBooking.booking_kind,
            selectedBookingReview,
            message: message || "Booking loaded.",
          });
          return;
        }
      } catch (fallbackError) {
        setState({ message: fallbackError.message });
      }
    }

    if (
      persistedCheckoutDraft?.booking &&
      String(persistedCheckoutDraft.booking.id) === String(bookingId)
    ) {
      setState({
        selectedBooking: normalizeBookingRecord(
          persistedCheckoutDraft.booking,
          persistedCheckoutDraft.kind || bookingKind,
        ),
        selectedBookingKind: persistedCheckoutDraft.kind || bookingKind || persistedCheckoutDraft.booking.booking_kind || null,
        selectedBookingReview: null,
        message: "Checkout restored from your last booking.",
      });
      return;
    }

    setState({
      selectedBooking: null,
      selectedBookingKind: bookingKind,
      selectedBookingReview: null,
      message: error.message,
    });
  }
}

async function refreshAvailabilityAndBookings(message) {
  await refreshRooms(message);
  await refreshBookings(message);
  await refreshAdminBookings(message);
  await refreshAdminAnalytics(message);
  await refreshAdminActivity(message);
  await refreshAdminUsers(message);
  await refreshAdminTestCases(message);
  await refreshAdminStaffProfiles(message);
  await refreshAdminPromoCodes(message);
  await refreshPublicStaffProfiles(message);
  await loadSelectedBooking(message);
}

async function loadPageData(message) {
  const requirements = currentRequirements();

  if (requirements.rooms) {
    await refreshRooms(message || "Rooms ready.");
  }
  if (requirements.bookings) {
    await refreshBookings(message || "Bookings ready.");
  }
  if (requirements.admin) {
    await refreshAdminBookings(message || "Admin workspace ready.");
    await refreshAdminAnalytics(message || "Admin workspace ready.");
    await refreshAdminActivity(message || "Admin workspace ready.");
    await refreshAdminUsers(message || "Admin workspace ready.");
    await refreshAdminTestCases(message || "Admin workspace ready.");
    await refreshAdminStaffProfiles(message || "Admin workspace ready.");
    await refreshAdminPromoCodes(message || "Admin workspace ready.");
  }
  if (requirements.publicStaff) {
    await refreshPublicStaffProfiles(message || "Staff page ready.");
  }
  if (requirements.selectedRoom) {
    await loadSelectedRoom(message || "Room ready.");
  }
  if (requirements.selectedBooking) {
    await loadSelectedBooking(message || "Booking ready.");
  }
}

async function refreshSession(message) {
  resetScopedData();

  if (!state.token) {
    setState({ currentUser: null, message: message || "Signed out." });
    await loadPageData("Public view loaded.");
    return;
  }

  try {
    const currentUser = await api.getMe();
    setState({ currentUser, message: message || "Session restored." });
    await loadPageData("Session ready.");
  } catch (error) {
    persistToken(null);
    setState({
      currentUser: null,
      bookings: [],
      adminBookings: [],
      adminAnalytics: null,
      adminActivity: [],
      adminUsers: [],
      adminTestCases: [],
      adminStaffProfiles: [],
      adminPromoCodes: [],
      publicStaffProfiles: [],
      selectedRoom: null,
      selectedRoomReviews: [],
      selectedRoomReviewSummary: null,
      selectedBooking: null,
      selectedBookingKind: null,
      selectedBookingReview: null,
      availability: null,
      message: error.message,
    });
    await loadPageData("Token cleared.");
  }
}

async function clearSession() {
  setState({
    currentUser: null,
    bookings: [],
    adminBookings: [],
    adminAnalytics: null,
    adminActivity: [],
    adminUsers: [],
    adminTestCases: [],
    adminStaffProfiles: [],
    adminPromoCodes: [],
    publicStaffProfiles: [],
    selectedRoom: null,
    selectedRoomReviews: [],
    selectedRoomReviewSummary: null,
    selectedBooking: null,
    selectedBookingKind: null,
    selectedBookingReview: null,
    availability: null,
    message: "Signed out.",
  });
  await loadPageData("Public view loaded.");
}

subscribe(renderApp);

initAdminView({ refreshAll: refreshAvailabilityAndBookings, getState: () => state });
initAuthView({ refreshSession, clearSession });
initBookingsView({ refreshAvailabilityAndBookings });
initBookingDetailView({ reloadBookingDetail: loadSelectedBooking });
initHomeView();
initInfoView();
initPaymentSuccessView({ reloadPaymentSuccess: loadSelectedBooking });
initProfileView({ clearSession });
initRoomBookingView();
initRoomDetailView();
initRoomsView({ refreshRooms });
initStaffDirectoryView();

renderApp(state);
resetScopedData();
initRevealAnimations();
await loadHealth();
await refreshSession("Frontend ready.");
