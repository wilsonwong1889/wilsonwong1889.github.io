import { api } from "../api.js";
import { elements } from "../dom.js";
import { setState, state } from "../state.js";

let bookingHistoryTab = "upcoming";
let bookingHistoryKind = "all";

const BOOKING_VISUALS = {
  recording: "/assets/media/studio-room-2.png",
  podcast: "/assets/media/studio-lobby-2.png",
  photography: "/assets/media/studio-room-2.png",
  film: "/assets/media/studio-exterior-2.png",
  dance: "/assets/media/studio-exterior-2.png",
  production: "/assets/media/studio-room-2.png",
};

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function parseDate(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function formatBookingDay(value) {
  const date = parseDate(value);
  if (!date) {
    return "Date pending";
  }
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function formatTimeOnly(value) {
  const date = parseDate(value);
  if (!date) {
    return "Time pending";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(minutes) {
  const safeMinutes = Number(minutes || 0);
  if (!safeMinutes) {
    return "Duration pending";
  }
  const hours = safeMinutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format((cents || 0) / 100);
}

function inferBookingCategory(booking) {
  const text = `${booking.room_name || ""} ${booking.note || ""}`.toLowerCase();
  if (text.includes("podcast")) {
    return "podcast";
  }
  if (text.includes("photo")) {
    return "photography";
  }
  if (text.includes("film")) {
    return "film";
  }
  if (text.includes("dance")) {
    return "dance";
  }
  if (text.includes("production")) {
    return "production";
  }
  return "recording";
}

function formatStatusLabel(status) {
  return String(status || "Unknown")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
}

function getStatusClassName(status) {
  return `status-${String(status || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "")}`;
}

function getBookingSortValue(value) {
  return parseDate(value)?.getTime() || 0;
}

function formatCountdown(seconds) {
  const safeSeconds = Math.max(0, seconds || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatBookingCount(count) {
  return `${count} booking${count === 1 ? "" : "s"}`;
}

function getBookingKind(booking) {
  const explicitKind = String(booking?.booking_kind || booking?.kind || booking?.type || "").toLowerCase();
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

function getBookingDisplayName(booking) {
  if (getBookingKind(booking) === "staff") {
    return (
      booking?.staff_name ||
      booking?.staff_profile_name ||
      booking?.staff_profile?.name ||
      booking?.service_type ||
      "Staff booking"
    );
  }
  return booking?.room_name || "Studio booking";
}

function getBookingTypeLabel(booking) {
  return getBookingKind(booking) === "staff" ? "Staff" : "Room";
}

function getBookingTypeBadgeClass(booking) {
  return getBookingKind(booking) === "staff"
    ? "booking-card-category booking-card-kind-staff"
    : "booking-card-category booking-card-kind-room";
}

function getBookingDetailHref(booking) {
  const href = new URL("/booking", window.location.origin);
  href.searchParams.set("id", booking.id || "");
  if (getBookingKind(booking) === "staff") {
    href.searchParams.set("kind", "staff");
  }
  return href.pathname + href.search;
}

function getBookingImage(booking) {
  if (getBookingKind(booking) === "staff" && (booking?.staff_photo_url || booking?.photo_url)) {
    return booking.staff_photo_url || booking.photo_url;
  }
  const category = inferBookingCategory(booking);
  return BOOKING_VISUALS[category] || BOOKING_VISUALS.recording;
}

function getBookingLocationLabel(booking) {
  if (getBookingKind(booking) === "staff") {
    return booking?.location_label || "Studio support session";
  }
  return booking?.location_label || "Downtown studio district";
}

function bookingMatchesKindFilter(booking, filter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "rooms") {
    return getBookingKind(booking) === "room";
  }
  return getBookingKind(booking) === filter;
}

function getFilteredBookingCounts(bookings) {
  return bookings.reduce(
    (counts, booking) => {
      const kind = getBookingKind(booking);
      counts.all += 1;
      if (kind === "staff") {
        counts.staff += 1;
      } else {
        counts.rooms += 1;
      }
      return counts;
    },
    { all: 0, rooms: 0, staff: 0 },
  );
}

function getFilteredBookingCollection(bookings) {
  return bookings.filter((booking) => bookingMatchesKindFilter(booking, bookingHistoryKind));
}

function getBookingsEmptyMessage(scope) {
  const kindLabel = bookingHistoryKind === "staff" ? "staff" : bookingHistoryKind === "rooms" ? "room" : "booking";
  const kindPrefix = bookingHistoryKind === "all" ? "" : `${kindLabel} `;
  if (scope === "upcoming") {
    return bookingHistoryKind === "all"
      ? "No upcoming bookings yet. New room and staff reservations will appear here."
      : `No upcoming ${kindPrefix}bookings yet.`;
  }
  return bookingHistoryKind === "all"
    ? "No past or cancelled bookings yet."
    : `No past or cancelled ${kindPrefix}bookings yet.`;
}

function getBookingStatusLabel(booking) {
  if (booking.status === "PendingPayment") {
    return "Pending payment";
  }
  if (booking.status === "Paid") {
    return isBookingUpcoming(booking) ? "Confirmed" : "Paid";
  }
  return formatStatusLabel(booking.status);
}

function getBookingLifecycleTimeValue(booking) {
  if (booking.status === "PendingPayment") {
    return getBookingSortValue(booking.payment_expires_at || booking.start_time || booking.created_at);
  }
  if (booking.status === "Paid") {
    return getBookingSortValue(booking.confirmed_at || booking.start_time || booking.created_at);
  }
  if (booking.status === "Completed") {
    return getBookingSortValue(booking.checked_in_at || booking.end_time || booking.start_time || booking.created_at);
  }
  if (booking.status === "Refunded") {
    return getBookingSortValue(booking.updated_at || booking.created_at || booking.start_time);
  }
  if (booking.status === "Cancelled") {
    return getBookingSortValue(booking.cancelled_at || booking.created_at || booking.start_time);
  }
  return getBookingSortValue(booking.start_time || booking.created_at);
}

function isBookingUpcoming(booking) {
  if (booking.status === "PendingPayment") {
    return true;
  }
  if (booking.status !== "Paid") {
    return false;
  }
  return getBookingSortValue(booking.end_time || booking.start_time) > Date.now();
}

function getUpcomingBookings(bookings) {
  return bookings
    .filter((booking) => isBookingUpcoming(booking))
    .sort((left, right) => {
      return (
        getBookingSortValue(left.start_time || left.payment_expires_at || left.created_at) -
        getBookingSortValue(right.start_time || right.payment_expires_at || right.created_at)
      );
    });
}

function getHistoryBookings(bookings) {
  return bookings
    .filter((booking) => !isBookingUpcoming(booking) && ["Paid", "Completed", "Cancelled", "Refunded"].includes(booking.status))
    .sort((left, right) => getBookingLifecycleTimeValue(right) - getBookingLifecycleTimeValue(left));
}

function renderBookingCollection(bookings, emptyMessage, { upcoming = false } = {}) {
  if (!bookings.length) {
    return `
      <div class="empty-state">
        <p>${escapeHtml(emptyMessage)}</p>
        <div class="booking-card-actions">
          <a class="primary-button primary-link" href="/rooms">Book room</a>
          <a class="ghost-button ghost-link" href="/staff">Book staff</a>
        </div>
      </div>
    `;
  }
  return bookings.map((booking) => renderBookingCard(booking, { upcoming })).join("");
}

function renderBookingCard(booking, { upcoming = false } = {}) {
  const pendingPayment = booking.status === "PendingPayment";
  const kind = getBookingKind(booking);
  const category = inferBookingCategory(booking);
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);
  const bookingTypeLabel = getBookingTypeLabel(booking);
  const bookingTitle = getBookingDisplayName(booking);
  const bookingServiceLabel = booking.service_type || booking.location_label || getBookingLocationLabel(booking);
  const bookingStatusLabel = getBookingStatusLabel(booking);
  const bookingDateLabel = formatBookingDay(booking.start_time);
  const bookingTimeLabel = `${formatTimeOnly(booking.start_time)} · ${formatDuration(booking.duration_minutes)}`;
  const bookingTotalLabel = formatCurrency(booking.price_cents);
  const actionLabel = pendingPayment ? "Finish payment" : upcoming ? "Manage booking" : "View details";
  const actionClass = pendingPayment ? "primary-button primary-link" : "ghost-button ghost-link";
  const canCancel = upcoming && ["PendingPayment", "Paid"].includes(booking.status);
  const detailHref = getBookingDetailHref(booking);
  const supportCopy = pendingPayment
    ? typeof booking.payment_seconds_remaining === "number"
      ? `Checkout expires in ${formatCountdown(booking.payment_seconds_remaining)}`
      : kind === "staff"
        ? "Finish payment to keep the staff session reserved."
        : "Finish payment to keep the reservation"
    : upcoming
      ? "Deposits are non-refundable"
      : booking.status === "Cancelled"
        ? "Reservation cancelled"
        : "Reservation history";

  return `
    <article class="booking-card ${pendingPayment ? "booking-card-pending" : "booking-card-secondary"}">
      <a class="booking-card-main" href="${escapeHtml(detailHref)}">
        <div class="booking-card-media">
          <img class="booking-card-image" src="${escapeHtml(getBookingImage(booking))}" alt="${escapeHtml(bookingTitle)}" loading="lazy" />
        </div>
        <div class="booking-card-copy">
          <div class="booking-card-heading">
            <div class="booking-card-title-row">
              <h4>${escapeHtml(bookingTitle)}</h4>
              <span class="pill ${kind === "staff" ? "booking-card-type-booking" : getBookingTypeBadgeClass(booking)}">${bookingTypeLabel}</span>
              ${kind === "staff" && bookingServiceLabel ? `<span class="pill booking-card-category">${escapeHtml(bookingServiceLabel)}</span>` : `<span class="pill booking-card-category">${escapeHtml(categoryLabel)}</span>`}
            </div>
            <div class="booking-card-meta-row">
              <span>${escapeHtml(bookingDateLabel)}</span>
              <span>${escapeHtml(bookingTimeLabel)}</span>
              <span>${escapeHtml(bookingTotalLabel)}</span>
              <span>${escapeHtml(getBookingLocationLabel(booking))}</span>
            </div>
          </div>
        </div>
      </a>
      <div class="booking-card-side">
        <div class="booking-card-status-group">
          <span class="pill ${getStatusClassName(booking.status)}">${escapeHtml(bookingStatusLabel)}</span>
          <span class="booking-card-status-note">${escapeHtml(supportCopy)}</span>
        </div>
        <div class="booking-card-actions">
          <a class="${actionClass}" href="${escapeHtml(detailHref)}">${escapeHtml(actionLabel)}</a>
          ${canCancel ? `<button class="ghost-button" type="button" data-booking-action="cancel" data-booking-id="${escapeHtml(booking.id)}">Cancel</button>` : ""}
        </div>
      </div>
    </article>
  `;
}

export function initBookingsView(actions) {
  if (!elements.bookingHistoryPanel || !elements.pendingBookingsList || !elements.recentBookingsList || !elements.recentBookingsShell) {
    return;
  }

  elements.bookingHistoryPanel.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-booking-action='cancel']");
    if (!button) {
      return;
    }

    const booking = state.bookings.find((item) => String(item.id) === String(button.dataset.bookingId));
    const bookingKind = getBookingKind(booking);

    try {
      const confirmed = window.confirm("Are you sure you want to cancel this booking?");
      if (!confirmed) {
        return;
      }
      setState({ message: "Cancelling booking..." });
      if (bookingKind === "staff") {
        await api.cancelStaffBooking(button.dataset.bookingId, { reason: "Cancelled by user" });
      } else {
        await api.cancelBooking(button.dataset.bookingId, { reason: "Cancelled by user" });
      }
      await actions.refreshAvailabilityAndBookings("Booking cancelled.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.bookingHistoryAllTab?.addEventListener("click", () => {
    bookingHistoryKind = "all";
    renderBookingsView(state);
  });
  elements.bookingHistoryRoomsTab?.addEventListener("click", () => {
    bookingHistoryKind = "rooms";
    renderBookingsView(state);
  });
  elements.bookingHistoryStaffTab?.addEventListener("click", () => {
    bookingHistoryKind = "staff";
    renderBookingsView(state);
  });

  document.getElementById("booking-history-upcoming-tab")?.addEventListener("click", () => {
    bookingHistoryTab = "upcoming";
    renderBookingsView(state);
  });

  document.getElementById("booking-history-history-tab")?.addEventListener("click", () => {
    bookingHistoryTab = "history";
    renderBookingsView(state);
  });
}

export function renderBookingsView(currentState) {
  if (!elements.pendingBookingsList || !elements.recentBookingsList || !elements.recentBookingsShell) {
    return;
  }

  const bookings = currentState.bookings || [];
  const filteredBookings = getFilteredBookingCollection(bookings);
  const bookingCounts = getFilteredBookingCounts(bookings);
  const upcomingBookings = getUpcomingBookings(filteredBookings);
  const historyBookings = getHistoryBookings(filteredBookings);

  if (elements.bookingHistoryAllCount) {
    elements.bookingHistoryAllCount.textContent = String(bookingCounts.all);
  }
  if (elements.bookingHistoryRoomsCount) {
    elements.bookingHistoryRoomsCount.textContent = String(bookingCounts.rooms);
  }
  if (elements.bookingHistoryStaffCount) {
    elements.bookingHistoryStaffCount.textContent = String(bookingCounts.staff);
  }
  if (elements.pendingBookingsCount) {
    elements.pendingBookingsCount.classList.toggle("hidden", upcomingBookings.length === 0);
    elements.pendingBookingsCount.textContent = upcomingBookings.length ? formatBookingCount(upcomingBookings.length) : "";
  }
  if (elements.recentBookingsCount) {
    elements.recentBookingsCount.textContent = formatBookingCount(historyBookings.length);
  }

  const upcomingTab = document.getElementById("booking-history-upcoming-tab");
  const historyTab = document.getElementById("booking-history-history-tab");
  const upcomingPanel = document.getElementById("booking-history-upcoming-panel");
  const historyPanel = document.getElementById("booking-history-history-panel");
  const upcomingTabCount = document.getElementById("booking-history-upcoming-count");
  const historyTabCount = document.getElementById("booking-history-history-count");

  if (upcomingTabCount) {
    upcomingTabCount.textContent = String(upcomingBookings.length);
  }
  if (historyTabCount) {
    historyTabCount.textContent = String(historyBookings.length);
  }

  elements.bookingHistoryAllTab?.classList.toggle("is-active", bookingHistoryKind === "all");
  elements.bookingHistoryRoomsTab?.classList.toggle("is-active", bookingHistoryKind === "rooms");
  elements.bookingHistoryStaffTab?.classList.toggle("is-active", bookingHistoryKind === "staff");
  elements.bookingHistoryAllTab?.setAttribute("aria-pressed", bookingHistoryKind === "all" ? "true" : "false");
  elements.bookingHistoryRoomsTab?.setAttribute("aria-pressed", bookingHistoryKind === "rooms" ? "true" : "false");
  elements.bookingHistoryStaffTab?.setAttribute("aria-pressed", bookingHistoryKind === "staff" ? "true" : "false");

  const upcomingViewActive = bookingHistoryTab !== "history";
  upcomingTab?.classList.toggle("is-active", upcomingViewActive);
  historyTab?.classList.toggle("is-active", !upcomingViewActive);
  upcomingTab?.setAttribute("aria-selected", upcomingViewActive ? "true" : "false");
  historyTab?.setAttribute("aria-selected", upcomingViewActive ? "false" : "true");
  upcomingPanel?.classList.toggle("hidden", !upcomingViewActive);
  historyPanel?.classList.toggle("hidden", upcomingViewActive);

  elements.recentBookingsShell.classList.remove("hidden");
  elements.pendingBookingsList.innerHTML = renderBookingCollection(upcomingBookings, getBookingsEmptyMessage("upcoming"), {
    upcoming: true,
  });
  elements.recentBookingsList.innerHTML = renderBookingCollection(historyBookings, getBookingsEmptyMessage("history"));
}
