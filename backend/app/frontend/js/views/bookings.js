import { api } from "../api.js";
import { elements } from "../dom.js";
import { setState, state } from "../state.js";

let bookingHistoryTab = "upcoming";
let bookingHistoryKind = "all";

const BOOKING_VISUALS = {
  recording: "/assets/media/placeholder-carousel-3.jpg",
  podcast: "/assets/media/placeholder-carousel-2.jpg",
  photography: "/assets/media/placeholder-carousel-1.jpg",
  film: "/assets/media/studio-photo-editing.jpg",
  dance: "/assets/media/studio-conference-room.jpg",
  production: "/assets/media/placeholder-carousel-3.jpg",
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

// Balance still owed after a deposit-only payment (mirrors backend upfront_charge_cents).
function getBalanceOwedCents(booking) {
  const deposit = Number(booking.deposit_amount_cents || 0);
  if (booking.status !== "DepositPaid" || deposit <= 0) {
    return 0;
  }
  const charge = deposit + Math.floor(deposit * 0.05);
  return Math.max(0, Number(booking.price_cents || 0) - charge);
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

function bookingNeedsConfirmation(booking) {
  return (
    Boolean(booking.needs_confirmation) ||
    (booking.status === "AcceptedPendingPayment" && (booking.price_cents || 0) <= 0)
  );
}

function bookingNeedsRequestConfirmation(booking) {
  return (
    Boolean(booking.needs_request_confirmation) ||
    (getBookingKind(booking) === "staff" && booking.status === "Requested" && !booking.customer_confirmed_at)
  );
}

function getBookingStatusLabel(booking) {
  if (booking.status === "PendingPayment") {
    return "Pending payment";
  }
  if (booking.status === "Requested") {
    return bookingNeedsRequestConfirmation(booking) ? "Awaiting your confirmation" : "Awaiting staff response";
  }
  if (booking.status === "AcceptedPendingPayment") {
    return bookingNeedsConfirmation(booking) ? "Accepted — confirm to book" : "Accepted — payment due";
  }
  if (booking.status === "Declined") {
    return "Declined by staff";
  }
  if (booking.status === "Expired") {
    return "Request expired";
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
  if (booking.status === "Paid" || booking.status === "DepositPaid") {
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
  // Active staff requests (awaiting staff response or the customer's free
  // confirmation) are surfaced as upcoming so the customer can act on them.
  if (["PendingPayment", "Requested", "AcceptedPendingPayment"].includes(booking.status)) {
    return true;
  }
  if (booking.status !== "Paid" && booking.status !== "DepositPaid") {
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
    .filter((booking) => !isBookingUpcoming(booking) && ["Paid", "DepositPaid", "Completed", "Cancelled", "Refunded", "Declined", "Expired"].includes(booking.status))
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
  const needsConfirmation = bookingNeedsConfirmation(booking);
  const needsRequestConfirmation = bookingNeedsRequestConfirmation(booking);
  const isRequested = booking.status === "Requested";
  const highlight = pendingPayment || needsConfirmation || needsRequestConfirmation;
  const kind = getBookingKind(booking);
  const category = inferBookingCategory(booking);
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);
  const bookingTypeLabel = getBookingTypeLabel(booking);
  const bookingTitle = getBookingDisplayName(booking);
  const bookingServiceLabel = booking.service_type || booking.location_label || getBookingLocationLabel(booking);
  const bookingStatusLabel = getBookingStatusLabel(booking);
  const bookingDateLabel = formatBookingDay(booking.start_time);
  const bookingTimeLabel = `${formatTimeOnly(booking.start_time)} · ${formatDuration(booking.duration_minutes)}`;
  const bookingTotalLabel = needsConfirmation || (kind === "staff" && (booking.price_cents || 0) <= 0)
    ? "Request"
    : formatCurrency(booking.price_cents);
  const actionLabel = pendingPayment ? "Finish payment" : upcoming ? "Manage booking" : "View details";
  const actionClass = pendingPayment ? "primary-button primary-link" : "ghost-button ghost-link";
  const canCancel = upcoming && ["PendingPayment", "Paid", "DepositPaid", "Requested", "AcceptedPendingPayment"].includes(booking.status);
  const detailHref = getBookingDetailHref(booking);
  const hasLiveCountdown = pendingPayment && booking.payment_expires_at;
  const supportCopy = pendingPayment
    ? typeof booking.payment_seconds_remaining === "number"
      ? `Checkout expires in ${formatCountdown(booking.payment_seconds_remaining)}`
      : kind === "staff"
        ? "Finish payment to keep the staff session reserved."
        : "Finish payment to keep the reservation"
    : needsRequestConfirmation
      ? `Confirm to send your request to ${bookingTitle}. It isn't booked until you confirm.`
      : needsConfirmation
      ? `${bookingTitle} accepted your request — confirm to lock in your session.`
      : isRequested
        ? `Waiting for ${bookingTitle} to accept your request.`
        : booking.status === "DepositPaid"
          ? (getBalanceOwedCents(booking) > 0
              ? `Deposit paid — ${formatCurrency(getBalanceOwedCents(booking))} balance due at the studio`
              : "Deposit paid")
        : upcoming
          ? "Deposits are non-refundable"
          : booking.status === "Declined"
            ? "Your request was declined."
            : booking.status === "Expired"
              ? "This request expired before it was accepted."
              : booking.status === "Cancelled"
                ? "Reservation cancelled"
                : "Reservation history";
  const supportNoteAttrs = hasLiveCountdown
    ? ` data-payment-countdown="${escapeHtml(booking.payment_expires_at)}" data-booking-kind="${escapeHtml(kind)}"`
    : "";

  return `
    <article class="booking-card ${highlight ? "booking-card-pending" : "booking-card-secondary"}">
      <a class="booking-card-main" href="${escapeHtml(detailHref)}">
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
          <span class="booking-card-status-note"${supportNoteAttrs}>${escapeHtml(supportCopy)}</span>
        </div>
        <div class="booking-card-actions">
          ${needsRequestConfirmation ? `<button class="primary-button" type="button" data-booking-action="confirm-request" data-booking-id="${escapeHtml(booking.id)}">Confirm &amp; send request</button>` : ""}
          ${needsConfirmation ? `<button class="primary-button" type="button" data-booking-action="confirm-free" data-booking-id="${escapeHtml(booking.id)}">Confirm booking</button>` : ""}
          <a class="${actionClass}" href="${escapeHtml(detailHref)}">${escapeHtml(actionLabel)}</a>
          ${canCancel ? `<button class="ghost-button" type="button" data-booking-action="cancel" data-booking-id="${escapeHtml(booking.id)}">Cancel</button>` : ""}
        </div>
      </div>
    </article>
  `;
}

let bookingsCountdownTimer = null;
let bookingsCountdownActions = null;
function startBookingsCountdownTimer(actions) {
  if (bookingsCountdownTimer) return;
  bookingsCountdownActions = actions;
  const tick = () => {
    const nodes = document.querySelectorAll("[data-payment-countdown]");
    if (!nodes.length) {
      return;
    }
    const now = Date.now();
    let anyExpired = false;
    nodes.forEach((node) => {
      const expiresAt = new Date(node.dataset.paymentCountdown).getTime();
      if (Number.isNaN(expiresAt)) return;
      const secondsRemaining = Math.max(0, Math.floor((expiresAt - now) / 1000));
      if (secondsRemaining === 0) {
        node.textContent = "Checkout window expired";
        node.classList.add("booking-card-status-note-expired");
        delete node.dataset.paymentCountdown;
        anyExpired = true;
      } else {
        node.textContent = `Checkout expires in ${formatCountdown(secondsRemaining)}`;
      }
    });
    if (anyExpired && bookingsCountdownActions?.refreshAvailabilityAndBookings) {
      // Re-fetch so the card flips to Cancelled the next tick rather than staying "Pending payment".
      void bookingsCountdownActions.refreshAvailabilityAndBookings();
    }
  };
  bookingsCountdownTimer = window.setInterval(tick, 1000);
  tick();
}

export function initBookingsView(actions) {
  if (!elements.bookingHistoryPanel || !elements.pendingBookingsList || !elements.recentBookingsList || !elements.recentBookingsShell) {
    return;
  }
  startBookingsCountdownTimer(actions);

  elements.bookingHistoryPanel.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-booking-action]");
    if (!button) {
      return;
    }
    const action = button.dataset.bookingAction;
    const bookingId = button.dataset.bookingId;

    if (action === "confirm-free") {
      try {
        setState({ message: "Confirming your booking..." });
        await api.confirmFreeStaffBooking(bookingId);
        await actions.refreshAvailabilityAndBookings("Booking confirmed.");
      } catch (error) {
        setState({ message: error.message });
      }
      return;
    }

    if (action === "confirm-request") {
      const booking = state.bookings.find((item) => String(item.id) === String(bookingId));
      const staffName = booking ? getBookingDisplayName(booking) : "this staff member";
      if (!window.confirm(`Send your booking request to ${staffName}? They'll be notified and have time to respond.`)) {
        return;
      }
      try {
        setState({ message: "Sending your request..." });
        await api.confirmStaffBookingRequest(bookingId);
        await actions.refreshAvailabilityAndBookings("Request sent — the staff member has been notified.");
      } catch (error) {
        setState({ message: error.message });
      }
      return;
    }

    if (action !== "cancel") {
      return;
    }

    const booking = state.bookings.find((item) => String(item.id) === String(bookingId));
    const bookingKind = getBookingKind(booking);

    try {
      const confirmed = window.confirm("Are you sure you want to cancel this booking?");
      if (!confirmed) {
        return;
      }
      setState({ message: "Cancelling booking..." });
      if (bookingKind === "staff") {
        await api.cancelStaffBooking(bookingId, { reason: "Cancelled by user" });
      } else {
        await api.cancelBooking(bookingId, { reason: "Cancelled by user" });
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
