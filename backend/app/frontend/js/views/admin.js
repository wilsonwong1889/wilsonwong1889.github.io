import { api } from "../api.js";
import { elements } from "../dom.js";
import { setState } from "../state.js";

let editingStaffProfileId = null;
let activeAdminTab = "rooms";
let adminRoomEditorOpen = false;
let selectedAdminScheduleDate = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; })();
let selectedAdminScheduleRoomId = "all";
let selectedAdminCalendarMonth = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; })();
let selectedAdminCalendarRoomId = "all";
let selectedAdminAccountId = null;
let adminSearchResults = null;
let selectedAdminBookingQuickFilter = "all";
const DEFAULT_ADMIN_SUBPAGES = {
  overview: "dashboard",
  accounts: "directory",
  bookings: "queue",
  staff: "editor",
  rooms: "inventory",
};
const activeAdminSubpages = { ...DEFAULT_ADMIN_SUBPAGES };

const TEST_CASE_HEALTH_META = {
  working: {
    label: "Working",
    className: "test-health-working",
    sortOrder: 2,
  },
  needs_fix: {
    label: "Needs fix",
    className: "test-health-needs-fix",
    sortOrder: 1,
  },
  not_working: {
    label: "Not working",
    className: "test-health-not-working",
    sortOrder: 0,
  },
};

const ADMIN_BOOKING_GROUPS = [
  {
    key: "PendingPayment",
    label: "Pending payment",
    description: "These bookings still need payment or an admin decision.",
  },
  {
    key: "Paid",
    label: "Ready for arrival",
    description: "Paid bookings that may still need check-in.",
  },
  {
    key: "Completed",
    label: "Completed sessions",
    description: "Checked-in bookings already finished or in progress.",
  },
  {
    key: "Cancelled",
    label: "Cancelled",
    description: "Cancelled bookings stay here for follow-up and refund review.",
  },
  {
    key: "Refunded",
    label: "Refunded",
    description: "Refunded bookings remain visible for audit history.",
  },
];

function getAdminTriageMetrics(currentState) {
  const bookings = currentState.adminBookings || [];
  const today = todayString();

  return {
    needsAttention: bookings.filter(isAdminBookingNeedsAttention).length,
    pendingPayment: bookings.filter((booking) => booking.status === "PendingPayment").length,
    readyForArrival: bookings.filter((booking) => booking.status === "Paid" && !booking.checked_in_at).length,
    todayCount: bookings.filter((booking) => getDateKey(booking.start_time) === today).length,
  };
}

function setActiveAdminTab(tab) {
  activeAdminTab = tab;
  if (tab !== "rooms") {
    adminRoomEditorOpen = false;
  }
  const panels = Array.from(elements.adminPanels || []);
  elements.adminTabs?.forEach((button) => {
    const isActive = button.dataset.adminTab === tab;
    const tabKey = escapeClassToken(button.dataset.adminTab);
    const panel = panels.find((item) => item.dataset.adminPanel === button.dataset.adminTab);
    const buttonId = ensureElementId(button, `admin-tab-${tabKey}`);
    if (panel) {
      const panelId = ensureElementId(panel, `admin-panel-${tabKey}`);
      button.setAttribute("aria-controls", panelId);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", buttonId);
    }
    button.setAttribute("role", "tab");
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
    button.setAttribute("tabindex", isActive ? "0" : "-1");
  });
  panels.forEach((panel) => {
    const isActive = panel.dataset.adminPanel === tab;
    panel.classList.toggle("hidden", !isActive);
    panel.setAttribute("aria-hidden", isActive ? "false" : "true");
  });
  if (elements.adminWorkspaceSelect && elements.adminWorkspaceSelect.value !== tab) {
    elements.adminWorkspaceSelect.value = tab;
  }
  syncAdminModalState();
  syncAdminTodayPollingForActiveTab();
}

function setActiveAdminSubpage(group, subpage) {
  const nextSubpage = subpage || DEFAULT_ADMIN_SUBPAGES[group] || "overview";
  activeAdminSubpages[group] = nextSubpage;
  if (group === "rooms" && nextSubpage !== "editor") {
    adminRoomEditorOpen = false;
  }

  const panels = Array.from(document.querySelectorAll("[data-admin-subpage-panel]")).filter(
    (panel) => panel.dataset.adminSubpagePanel === group,
  );
  Array.from(document.querySelectorAll("[data-admin-subpage-button]"))
    .filter((button) => button.dataset.adminSubpageButton === group)
    .forEach((button) => {
      const isActive = button.dataset.adminSubpage === nextSubpage;
      const subpageKey = escapeClassToken(button.dataset.adminSubpage);
      const groupKey = escapeClassToken(group);
      const panel = panels.find((item) => item.dataset.adminSubpage === button.dataset.adminSubpage);
      const buttonId = ensureElementId(button, `admin-subpage-tab-${groupKey}-${subpageKey}`);
      if (panel) {
        const panelId = ensureElementId(panel, `admin-subpage-panel-${groupKey}-${subpageKey}`);
        button.setAttribute("aria-controls", panelId);
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", buttonId);
      }
      button.setAttribute("role", "tab");
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
      button.setAttribute("tabindex", isActive ? "0" : "-1");
    });

  const select = Array.from(document.querySelectorAll("[data-admin-subpage-select]")).find(
    (item) => item.dataset.adminSubpageSelect === group,
  );
  if (select && select.value !== nextSubpage) {
    select.value = nextSubpage;
  }

  panels.forEach((panel) => {
    const isActive = panel.dataset.adminSubpage === nextSubpage;
    panel.classList.toggle("hidden", !isActive);
    panel.setAttribute("aria-hidden", isActive ? "false" : "true");
  });
  syncAdminModalState();
  syncAdminTodayPollingForActiveTab();
}

function syncAdminModalState() {
  const roomEditorOpen = adminRoomEditorOpen && activeAdminTab === "rooms" && activeAdminSubpages.rooms === "editor";
  document.body?.classList.toggle("admin-room-modal-active", roomEditorOpen);
  if (!roomEditorOpen) {
    elements.roomForm?.classList.add("hidden");
    elements.roomForm?.setAttribute("aria-hidden", "true");
  }
}

function toIsoStringFromLocal(value) {
  const localDate = new Date(value);
  return localDate.toISOString();
}

function todayString() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function safeMonthValue(value) {
  return /^\d{4}-\d{2}$/.test(String(value || "").trim()) ? String(value).trim() : todayString().slice(0, 7);
}

function getMonthDateKey(monthValue, dayNumber) {
  return `${safeMonthValue(monthValue)}-${String(dayNumber).padStart(2, "0")}`;
}

function getMonthStartOffset(monthValue) {
  const [year, month] = safeMonthValue(monthValue).split("-").map(Number);
  return new Date(year, month - 1, 1).getDay();
}

function getMonthDayCount(monthValue) {
  const [year, month] = safeMonthValue(monthValue).split("-").map(Number);
  return new Date(year, month, 0).getDate();
}

function formatMonthHeading(monthValue) {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(new Date(`${safeMonthValue(monthValue)}-01T12:00:00`));
}

function getAdminCalendarMonthInput() {
  return document.getElementById("admin-calendar-month");
}

function getAdminCalendarRoomFilter() {
  return document.getElementById("admin-calendar-room-filter");
}

function getAdminRoomCalendarSummaryElement() {
  return document.getElementById("admin-room-calendar-summary");
}

function getAdminRoomCalendarGridElement() {
  return document.getElementById("admin-room-calendar-grid");
}

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDateOnly(value) {
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatTimeOnly(value) {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function renderManualDurationOptions(currentState) {
  if (!elements.adminManualBookingForm || !elements.adminRoomSelect) {
    return;
  }

  const durationSelect = elements.adminManualBookingForm.elements.duration_minutes;
  if (!durationSelect) {
    return;
  }

  const room = (currentState.rooms || []).find((item) => String(item.id) === elements.adminRoomSelect.value);
  const maxDuration = room?.max_booking_duration_minutes || 300;
  const previousValue = Number(durationSelect.value || 60);
  const options = [];
  for (let duration = 60; duration <= maxDuration; duration += 60) {
    options.push(`<option value="${duration}">${formatDuration(duration)}</option>`);
  }
  durationSelect.innerHTML = options.join("");
  durationSelect.value = options.some((_option, index) => (index + 1) * 60 === previousValue)
    ? String(previousValue)
    : "60";
}

function formatPhone(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return value || "No phone";
}

function getDateKey(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function getAdminRoomCalendarLabel(currentState) {
  if (selectedAdminCalendarRoomId === "all") {
    return "All rooms";
  }

  const room = (currentState.rooms || []).find((item) => String(item.id) === selectedAdminCalendarRoomId);
  return room?.name || "Selected room";
}

function getStatusClass(status) {
  return `status-${escapeClassToken(status)}`;
}

function getStatusLabel(status) {
  const normalized = String(status || "").trim();
  return normalized === "PendingPayment" ? "Pending payment" : normalized || "Unknown";
}

function normalizePhoneHref(value) {
  const digits = String(value || "").replace(/[^\d+]/g, "");
  return digits ? `tel:${digits}` : null;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => {
    switch (character) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return character;
    }
  });
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function escapeClassToken(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";
}

function ensureElementId(element, fallbackId) {
  if (!element.id) {
    element.id = fallbackId;
  }
  return element.id;
}

function isAdminBookingNeedsAttention(booking) {
  if (booking.status === "PendingPayment") {
    return true;
  }
  if (booking.status === "Paid" && !booking.checked_in_at) {
    return true;
  }
  if (booking.status === "Cancelled" && booking.price_cents > 0) {
    return true;
  }
  return false;
}

function matchesAdminBookingQuickFilter(booking, filterKey) {
  switch (filterKey) {
    case "needs_attention":
      return isAdminBookingNeedsAttention(booking);
    case "pending_payment":
      return booking.status === "PendingPayment";
    case "ready_for_arrival":
      return booking.status === "Paid" && !booking.checked_in_at;
    case "today":
      return getDateKey(booking.start_time) === todayString();
    case "completed":
      return booking.status === "Completed";
    case "cancelled":
      return booking.status === "Cancelled" || booking.status === "Refunded";
    case "all":
    default:
      return true;
  }
}

function getAdminBookingFilterOptions(bookings) {
  return [
    {
      key: "all",
      label: "All bookings",
      description: "Everything in the current queue or search result.",
    },
    {
      key: "needs_attention",
      label: "Needs attention",
      description: "Pending payment, not checked in, or refund follow-up.",
    },
    {
      key: "pending_payment",
      label: "Pending payment",
      description: "Waiting on Stripe or an admin override.",
    },
    {
      key: "ready_for_arrival",
      label: "Ready for arrival",
      description: "Paid and not checked in yet.",
    },
    {
      key: "today",
      label: "Today",
      description: "Sessions happening today.",
    },
    {
      key: "completed",
      label: "Completed",
      description: "Checked in or finished sessions.",
    },
    {
      key: "cancelled",
      label: "Cancelled / refunded",
      description: "Closed-out bookings and refund history.",
    },
  ].map((option) => ({
    ...option,
    count: bookings.filter((booking) => matchesAdminBookingQuickFilter(booking, option.key)).length,
  }));
}

function getAdminBookingSortPriority(booking) {
  switch (booking.status) {
    case "PendingPayment":
      return 0;
    case "Paid":
      return 1;
    case "Completed":
      return 2;
    case "Cancelled":
      return 3;
    case "Refunded":
      return 4;
    default:
      return 5;
  }
}

function getAdminBookingReferenceTime(booking) {
  if (booking.status === "PendingPayment") {
    return new Date(booking.payment_expires_at || booking.start_time).getTime();
  }
  if (booking.status === "Paid") {
    return new Date(booking.start_time).getTime();
  }
  if (booking.status === "Completed") {
    return new Date(booking.checked_in_at || booking.confirmed_at || booking.updated_at || booking.start_time).getTime();
  }
  if (booking.status === "Cancelled") {
    return new Date(booking.cancelled_at || booking.updated_at || booking.start_time).getTime();
  }
  return new Date(booking.updated_at || booking.cancelled_at || booking.start_time).getTime();
}

function compareAdminBookings(left, right) {
  const leftPriority = getAdminBookingSortPriority(left);
  const rightPriority = getAdminBookingSortPriority(right);
  if (leftPriority !== rightPriority) {
    return leftPriority - rightPriority;
  }

  const leftTime = getAdminBookingReferenceTime(left);
  const rightTime = getAdminBookingReferenceTime(right);

  if (left.status === "PendingPayment" || left.status === "Paid") {
    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }
  } else if (leftTime !== rightTime) {
    return rightTime - leftTime;
  }

  return new Date(right.created_at || right.start_time).getTime() - new Date(left.created_at || left.start_time).getTime();
}

function getAdminBookingCollections(currentState) {
  const sourceBookings = [...(adminSearchResults || currentState.adminBookings || [])];
  const sortedBookings = sourceBookings.sort(compareAdminBookings);
  const filteredBookings = sortedBookings.filter((booking) =>
    matchesAdminBookingQuickFilter(booking, selectedAdminBookingQuickFilter),
  );

  return {
    baseBookings: sortedBookings,
    filteredBookings,
    filterOptions: getAdminBookingFilterOptions(sortedBookings),
    searchActive: Boolean(adminSearchResults),
  };
}

function renderAdminBookingQuickSummary(bookings, filterOptions) {
  if (!elements.adminBookingQuickSummary) {
    return;
  }

  const cards = filterOptions
    .filter((option) => ["all", "needs_attention", "pending_payment", "ready_for_arrival", "today"].includes(option.key))
    .map(
      (option) => `
        <button
          class="metric-card admin-booking-summary-card${selectedAdminBookingQuickFilter === option.key ? " is-active" : ""}"
          type="button"
          data-admin-booking-filter="${escapeAttribute(option.key)}"
        >
          <span class="metric-label">${escapeHtml(option.label)}</span>
          <strong class="metric-value">${escapeHtml(option.count)}</strong>
          <span class="status-detail">${escapeHtml(option.description)}</span>
        </button>
      `,
    );

  elements.adminBookingQuickSummary.innerHTML = bookings.length
    ? cards.join("")
    : '<div class="empty-state">Booking summary cards will appear once records exist.</div>';
}

function renderAdminBookingQuickFilters(filterOptions) {
  if (!elements.adminBookingQuickFilters) {
    return;
  }

  elements.adminBookingQuickFilters.innerHTML = filterOptions
    .map(
      (option) => `
        <button
          class="pill admin-booking-filter-chip${selectedAdminBookingQuickFilter === option.key ? " is-active" : ""}"
          type="button"
          data-admin-booking-filter="${escapeAttribute(option.key)}"
        >
          ${escapeHtml(option.label)}
          <span>${escapeHtml(option.count)}</span>
        </button>
      `,
    )
    .join("");
}

const ADMIN_TODAY_COUNTER_CARDS = [
  { key: "total", label: "Total today" },
  { key: "arrived", label: "Already arrived" },
  { key: "pending_arrival", label: "Pending arrival" },
  { key: "pending_payment", label: "Pending payment" },
  { key: "cancelled", label: "Cancelled" },
];

function renderAdminTodayCounters(currentState) {
  if (!elements.adminTodayCounters) {
    return;
  }
  const counters = currentState.adminTodayRoster?.counters || null;
  if (!counters) {
    elements.adminTodayCounters.innerHTML = ADMIN_TODAY_COUNTER_CARDS
      .map(
        (card) => `
          <article class="metric-card admin-today-counter" data-today-counter="${card.key}">
            <span class="metric-label">${escapeHtml(card.label)}</span>
            <strong class="metric-value">—</strong>
          </article>
        `,
      )
      .join("");
    return;
  }
  elements.adminTodayCounters.innerHTML = ADMIN_TODAY_COUNTER_CARDS
    .map(
      (card) => `
        <article class="metric-card admin-today-counter" data-today-counter="${card.key}">
          <span class="metric-label">${escapeHtml(card.label)}</span>
          <strong class="metric-value">${counters[card.key] ?? 0}</strong>
        </article>
      `,
    )
    .join("");
}

function renderAdminTodayRoster(currentState) {
  if (!elements.adminTodayGlance) {
    return;
  }
  const roster = currentState.adminTodayRoster?.today
    || (currentState.adminBookings || [])
      .filter((booking) => getDateKey(booking.start_time) === todayString())
      .sort((left, right) => new Date(left.start_time).getTime() - new Date(right.start_time).getTime());

  if (!roster.length) {
    elements.adminTodayGlance.innerHTML = '<div class="empty-state">No bookings scheduled for today.</div>';
    return;
  }
  const nowMs = Date.now();
  elements.adminTodayGlance.innerHTML = roster
    .map((booking) => {
      const isStaff = booking.booking_kind === "staff";
      const venue = isStaff
        ? booking.staff_name || "Staff session"
        : booking.room_name || "Room";
      const guest = booking.user_full_name || booking.user_email || "Guest";
      const statusClass = getStatusClass(booking.status);
      const startMs = new Date(booking.start_time).getTime();
      const checkedIn = Boolean(booking.checked_in_at);
      const canCheckIn = booking.status === "Paid" && !checkedIn && !isStaff;
      const minutesToStart = (startMs - nowMs) / 60000;
      const isImminent = !checkedIn && minutesToStart > -5 && minutesToStart <= 15;
      const rowClasses = ["admin-today-row", statusClass];
      if (checkedIn) rowClasses.push("is-checked-in");
      if (isImminent) rowClasses.push("is-imminent");
      const phoneRaw = booking.user_phone || "";
      const phoneHref = phoneRaw ? normalizePhoneHref(phoneRaw) : "";
      const phoneLabel = phoneRaw ? formatPhone(phoneRaw) : "";
      const phoneCell = phoneHref
        ? `<a class="admin-today-phone" href="${escapeAttribute(phoneHref)}">${escapeHtml(phoneLabel)}</a>`
        : '<span class="admin-today-phone admin-today-phone-empty">No phone</span>';
      const noteRow = booking.note
        ? `<span class="admin-today-note">📝 ${escapeHtml(booking.note)}</span>`
        : "";
      const checkInButton = canCheckIn
        ? `<button class="ghost-button admin-today-checkin" type="button" data-admin-action="check-in" data-booking-id="${escapeAttribute(booking.id)}" data-booking-kind="${escapeAttribute(isStaff ? "staff" : "room")}">Check in</button>`
        : "";
      const arrivedSubtitle = checkedIn
        ? `<span class="admin-today-arrived">Arrived ${formatTimeOnly(booking.checked_in_at)}</span>`
        : "";
      const bookingHref = `/booking?id=${encodeURIComponent(booking.id)}${isStaff ? "&kind=staff" : ""}`;
      return `
        <article class="${rowClasses.map((cls) => escapeAttribute(cls)).join(" ")}" data-admin-today-row="${escapeAttribute(booking.id)}">
          <span class="admin-today-time">${formatTimeOnly(booking.start_time)} – ${formatTimeOnly(booking.end_time)}</span>
          <span class="admin-today-venue">${escapeHtml(venue)}</span>
          <span class="admin-today-guest">${escapeHtml(guest)}${arrivedSubtitle}</span>
          ${phoneCell}
          <span class="pill pill-xs ${escapeAttribute(statusClass)}">${escapeHtml(getStatusLabel(booking.status))}</span>
          <span class="admin-today-actions">
            ${checkInButton}
            <a class="admin-today-open" href="${escapeAttribute(bookingHref)}">Open</a>
          </span>
          ${noteRow}
        </article>
      `;
    })
    .join("");
}

function renderAdminUpcomingRoster(currentState) {
  if (!elements.adminUpcomingGlance) {
    return;
  }
  const roster = currentState.adminTodayRoster;
  if (!roster) {
    elements.adminUpcomingGlance.innerHTML = '<div class="empty-state">Loading the week ahead…</div>';
    return;
  }
  const tomorrowCount = roster.tomorrow_count || 0;
  const tomorrowFirstThree = roster.tomorrow_first_three || [];
  const weekCount = roster.next_seven_days_count || 0;
  const tomorrowRows = tomorrowFirstThree.length
    ? tomorrowFirstThree
        .map((booking) => {
          const isStaff = booking.booking_kind === "staff";
          const venue = isStaff
            ? booking.staff_name || "Staff session"
            : booking.room_name || "Room";
          const guest = booking.user_full_name || booking.user_email || "Guest";
          const bookingHref = `/booking?id=${encodeURIComponent(booking.id)}${isStaff ? "&kind=staff" : ""}`;
          return `
            <a class="admin-today-row admin-upcoming-row" href="${escapeAttribute(bookingHref)}">
              <span class="admin-today-time">${formatTimeOnly(booking.start_time)}</span>
              <span class="admin-today-venue">${escapeHtml(venue)}</span>
              <span class="admin-today-guest">${escapeHtml(guest)}</span>
            </a>
          `;
        })
        .join("")
    : '<div class="empty-state">No bookings for tomorrow yet.</div>';
  elements.adminUpcomingGlance.innerHTML = `
    <div class="admin-upcoming-summary">
      <article class="metric-card"><span class="metric-label">Tomorrow</span><strong class="metric-value">${tomorrowCount}</strong></article>
      <article class="metric-card"><span class="metric-label">Next 7 days</span><strong class="metric-value">${weekCount}</strong></article>
    </div>
    <div class="admin-upcoming-list">${tomorrowRows}</div>
  `;
}

// 60s polling of /api/admin/today while Overview > Dashboard is the active
// subpage. Paused while the browser tab is hidden so we're not burning
// quota on a backgrounded tab.
let adminTodayPollHandle = null;
let adminTodayActionsRef = null;
let adminTodayVisibilityBound = false;

function isAdminOverviewDashboardActive() {
  return activeAdminTab === "overview" && activeAdminSubpages.overview === "dashboard";
}

function startAdminTodayPolling(actions) {
  if (actions) adminTodayActionsRef = actions;
  if (adminTodayPollHandle) return;
  if (!adminTodayActionsRef?.refreshAdminToday) return;
  adminTodayPollHandle = window.setInterval(() => {
    if (document.visibilityState !== "visible") return;
    adminTodayActionsRef.refreshAdminToday("");
  }, 60_000);
  if (!adminTodayVisibilityBound) {
    document.addEventListener("visibilitychange", () => {
      if (!isAdminOverviewDashboardActive()) return;
      if (document.visibilityState === "visible") {
        adminTodayActionsRef?.refreshAdminToday?.("");
      }
    });
    adminTodayVisibilityBound = true;
  }
}

function stopAdminTodayPolling() {
  if (!adminTodayPollHandle) return;
  window.clearInterval(adminTodayPollHandle);
  adminTodayPollHandle = null;
}

function syncAdminTodayPollingForActiveTab() {
  if (isAdminOverviewDashboardActive()) {
    startAdminTodayPolling(adminTodayActionsRef);
  } else {
    stopAdminTodayPolling();
  }
}

function renderAdminDashboardMetrics(currentState) {
  if (!elements.adminDashboardMetrics) {
    return;
  }

  const analytics = currentState.adminAnalytics;
  const rooms = currentState.rooms || [];
  const currency = analytics?.currency || "CAD";
  const cards = [
    { label: "Studios", value: analytics?.active_rooms ?? rooms.length, icon: "▦" },
    { label: "Total bookings", value: analytics ? analytics.total_bookings : "Loading", icon: "▣" },
    { label: "Confirmed", value: analytics ? analytics.paid_bookings : "Loading", icon: "♙" },
    {
      label: "Revenue",
      value: analytics ? formatMoney(analytics.net_revenue_cents, currency) : "Loading",
      icon: "$",
    },
  ];

  elements.adminDashboardMetrics.innerHTML = cards
    .map(
      (card) => `
        <article class="admin-kpi-card">
          <div>
            <span>${escapeHtml(card.label)}</span>
            <strong>${escapeHtml(card.value)}</strong>
          </div>
          <span class="admin-kpi-icon" aria-hidden="true">${escapeHtml(card.icon)}</span>
        </article>
      `,
    )
    .join("");
}

function renderAdminRoles(currentState) {
  if (!elements.adminRolesList) {
    return;
  }

  const admins = (currentState.adminUsers || []).filter((account) => account.is_admin);
  if (elements.adminRolesCount) {
    elements.adminRolesCount.textContent = `${admins.length} admin${admins.length === 1 ? "" : "s"}`;
  }
  elements.adminRolesList.innerHTML = admins.length
    ? admins
        .map((account) => {
          const isCurrentUser = String(account.id) === String(currentState.currentUser?.id || "");
          return `
            <article class="admin-role-row">
              <div class="admin-role-identity">
                <span class="admin-role-avatar" aria-hidden="true">${escapeHtml(String(account.full_name || account.email || "A").slice(0, 1).toUpperCase())}</span>
                <div>
                  <strong>${escapeHtml(account.full_name || account.email)}</strong>
                  <p>${escapeHtml(account.id)}</p>
                </div>
              </div>
              <div class="room-meta">
                <span class="pill">${escapeHtml(getAccountRoleLabel(account))}</span>
                ${isCurrentUser ? '<span class="pill">Signed in</span>' : ""}
                <button class="ghost-button" type="button" data-admin-action="select-role-account" data-user-id="${escapeAttribute(account.id)}">
                  Review
                </button>
              </div>
            </article>
          `;
        })
        .join("")
    : '<div class="empty-state">No admin accounts are available yet.</div>';
}

function renderAdminBookingResultsCopy(baseBookings, filteredBookings, filterOptions, searchActive) {
  if (!elements.adminBookingResultsCopy) {
    return;
  }

  if (!baseBookings.length) {
    elements.adminBookingResultsCopy.textContent = searchActive
      ? "Search returned no bookings."
      : "No admin bookings yet. Search by email, booking code, or status.";
    return;
  }

  const activeFilter = filterOptions.find((option) => option.key === selectedAdminBookingQuickFilter) || filterOptions[0];
  const baseLabel = searchActive ? "search result" : "booking";
  elements.adminBookingResultsCopy.textContent = filteredBookings.length
    ? `Showing ${filteredBookings.length} of ${baseBookings.length} ${baseLabel}${baseBookings.length === 1 ? "" : "s"} in ${activeFilter.label.toLowerCase()}.`
    : `No ${baseLabel}${baseBookings.length === 1 ? "" : "s"} match ${activeFilter.label.toLowerCase()}.`;
}

function getAdminBookingUrgencyLabel(booking) {
  if (booking.status === "PendingPayment") {
    return "Needs payment";
  }
  if (booking.status === "Paid" && !booking.checked_in_at) {
    return booking.booking_kind === "staff" ? "Ready for session" : "Ready to check in";
  }
  if (booking.status === "Cancelled" && booking.price_cents > 0) {
    return "Review refund";
  }
  return "";
}

function renderAdminBookingTimelineRow(label, value) {
  return `
    <div class="admin-booking-timeline-row">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function renderAdminBookingGroup(groupMeta, bookings) {
  return `
    <section class="admin-booking-group">
      <header class="admin-booking-group-header">
        <div>
          <h4>${escapeHtml(groupMeta.label)}</h4>
          <p>${escapeHtml(groupMeta.description)}</p>
        </div>
        <span class="pill">${bookings.length} booking${bookings.length === 1 ? "" : "s"}</span>
      </header>
      <div class="admin-booking-group-list">
        ${bookings.map(renderAdminBookingCard).join("")}
      </div>
    </section>
  `;
}

function formatMoney(cents, currency = "CAD") {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format((cents || 0) / 100);
}

function toDateTimeLocalValue(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const localTime = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localTime.toISOString().slice(0, 16);
}

function parseOptionalInteger(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return null;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function getAdminPromoForm() {
  return document.getElementById("admin-promo-form");
}

function getAdminPromoList() {
  return document.getElementById("admin-promo-codes-list");
}

function getAdminPromoIdInput() {
  return document.getElementById("admin-promo-id");
}

function getAdminPromoDiscountTypeSelect() {
  return document.getElementById("admin-promo-discount-type");
}

function getAdminPromoPercentInput() {
  return document.getElementById("admin-promo-percent-off");
}

function getAdminPromoAmountInput() {
  return document.getElementById("admin-promo-amount-off-cents");
}

function formatPromoWindowValue(value) {
  return value ? formatBookingDate(value) : "No limit";
}

function formatPromoDiscountLabel(promoCode) {
  if (promoCode.percent_off) {
    return `${promoCode.percent_off}% off`;
  }
  if (promoCode.amount_off_cents) {
    return `${formatMoney(promoCode.amount_off_cents)} off`;
  }
  return "No discount";
}

function resetAdminPromoForm() {
  const form = getAdminPromoForm();
  if (!form) {
    return;
  }

  form.reset();
  if (getAdminPromoIdInput()) {
    getAdminPromoIdInput().value = "";
  }
  const activeCheckbox = document.getElementById("admin-promo-active");
  if (activeCheckbox) {
    activeCheckbox.checked = true;
  }
  if (getAdminPromoDiscountTypeSelect()) {
    getAdminPromoDiscountTypeSelect().value = "percent";
  }
  syncAdminPromoDiscountFields();
}

function syncAdminPromoDiscountFields() {
  const discountType = getAdminPromoDiscountTypeSelect()?.value || "percent";
  const percentInput = getAdminPromoPercentInput();
  const amountInput = getAdminPromoAmountInput();

  if (percentInput) {
    percentInput.disabled = discountType !== "percent";
  }
  if (amountInput) {
    amountInput.disabled = discountType !== "amount";
  }
}

function populateAdminPromoForm(promoCode) {
  const form = getAdminPromoForm();
  if (!form || !promoCode) {
    return;
  }

  getAdminPromoIdInput().value = promoCode.id;
  document.getElementById("admin-promo-code").value = promoCode.code || "";
  document.getElementById("admin-promo-description").value = promoCode.description || "";
  getAdminPromoDiscountTypeSelect().value = promoCode.percent_off ? "percent" : "amount";
  getAdminPromoPercentInput().value = promoCode.percent_off || "";
  getAdminPromoAmountInput().value = promoCode.amount_off_cents || "";
  document.getElementById("admin-promo-max-redemptions").value = promoCode.max_redemptions || "";
  document.getElementById("admin-promo-starts-at").value = toDateTimeLocalValue(promoCode.starts_at);
  document.getElementById("admin-promo-expires-at").value = toDateTimeLocalValue(promoCode.expires_at);
  document.getElementById("admin-promo-active").checked = Boolean(promoCode.active);
  syncAdminPromoDiscountFields();
}

function buildAdminPromoPayload() {
  const discountType = getAdminPromoDiscountTypeSelect()?.value || "percent";
  const description = document.getElementById("admin-promo-description")?.value?.trim() || null;
  const startsAt = document.getElementById("admin-promo-starts-at")?.value;
  const expiresAt = document.getElementById("admin-promo-expires-at")?.value;

  return {
    code: document.getElementById("admin-promo-code")?.value?.trim(),
    description,
    percent_off: discountType === "percent" ? parseOptionalInteger(getAdminPromoPercentInput()?.value) : null,
    amount_off_cents: discountType === "amount" ? parseOptionalInteger(getAdminPromoAmountInput()?.value) : null,
    active: Boolean(document.getElementById("admin-promo-active")?.checked),
    max_redemptions: parseOptionalInteger(document.getElementById("admin-promo-max-redemptions")?.value),
    starts_at: startsAt ? new Date(startsAt).toISOString() : null,
    expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
  };
}

function renderAdminPromoCodeCard(promoCode) {
  const redemptionsLabel = promoCode.max_redemptions
    ? `${promoCode.active_redemptions} / ${promoCode.max_redemptions} active redemptions`
    : `${promoCode.active_redemptions} active redemption${promoCode.active_redemptions === 1 ? "" : "s"}`;

  return `
    <article class="admin-promo-card ${promoCode.active ? "is-active" : "is-inactive"}">
      <div class="admin-promo-card-header">
        <div>
          <h4>${escapeHtml(promoCode.code)}</h4>
          <p>${escapeHtml(promoCode.description || "No description added yet.")}</p>
        </div>
        <div class="room-meta">
          <span class="pill">${escapeHtml(formatPromoDiscountLabel(promoCode))}</span>
          ${promoCode.member_unique ? '<span class="pill">Personal</span>' : ""}
          ${promoCode.member_category ? `<span class="pill">${escapeHtml(humanizeIntakeKey(promoCode.member_category))}</span>` : ""}
          ${promoCode.valid_month ? `<span class="pill muted">${escapeHtml(promoCode.valid_month)}</span>` : ""}
          <span class="pill ${promoCode.active ? "" : "muted"}">${promoCode.active ? "Active" : "Inactive"}</span>
        </div>
      </div>
      <div class="admin-detail-grid">
        <div class="admin-detail-field">
          <span>Redemptions</span>
          <div class="admin-detail-value">${escapeHtml(redemptionsLabel)}</div>
        </div>
        <div class="admin-detail-field">
          <span>Starts</span>
          <div class="admin-detail-value">${formatPromoWindowValue(promoCode.starts_at)}</div>
        </div>
        <div class="admin-detail-field">
          <span>Expires</span>
          <div class="admin-detail-value">${formatPromoWindowValue(promoCode.expires_at)}</div>
        </div>
      </div>
      <div class="room-actions">
        <button class="ghost-button" type="button" data-admin-action="edit-promo" data-promo-code-id="${escapeAttribute(promoCode.id)}">Edit</button>
        <button class="ghost-button" type="button" data-admin-action="toggle-promo" data-promo-code-id="${escapeAttribute(promoCode.id)}" data-next-active="${promoCode.active ? "false" : "true"}">
          ${promoCode.active ? "Deactivate" : "Activate"}
        </button>
      </div>
    </article>
  `;
}

function renderAdminPromoCodes(currentState) {
  const list = getAdminPromoList();
  if (!list) {
    return;
  }

  const promoCodes = currentState.adminPromoCodes || [];
  list.innerHTML = promoCodes.length
    ? promoCodes.map(renderAdminPromoCodeCard).join("")
    : '<div class="empty-state">No promo codes yet. Create one above to start offering discounts.</div>';
}

const INTAKE_TYPE_LABELS = {
  membership_interest: "Membership interest",
  engineer_application: "Engineer application",
};

function humanizeIntakeKey(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function renderAdminIntakeCard(intake) {
  const typeLabel = INTAKE_TYPE_LABELS[intake.intake_type] || intake.intake_type;
  const created = intake.created_at ? new Date(intake.created_at).toLocaleString() : "";
  const detailRows = Object.entries(intake.details || {})
    .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== "")
    .map(
      ([key, value]) => `
        <div class="admin-detail-field">
          <span>${escapeHtml(humanizeIntakeKey(key))}</span>
          <div class="admin-detail-value">${escapeHtml(String(value))}</div>
        </div>`,
    )
    .join("");

  const statusActions = [];
  if (intake.status !== "reviewed") {
    statusActions.push(
      `<button class="ghost-button" type="button" data-admin-action="set-intake-status" data-intake-id="${escapeAttribute(intake.id)}" data-intake-status="reviewed">Mark reviewed</button>`,
    );
  }
  if (intake.status !== "archived") {
    statusActions.push(
      `<button class="ghost-button" type="button" data-admin-action="set-intake-status" data-intake-id="${escapeAttribute(intake.id)}" data-intake-status="archived">Archive</button>`,
    );
  }
  if (intake.status !== "new") {
    statusActions.push(
      `<button class="ghost-button" type="button" data-admin-action="set-intake-status" data-intake-id="${escapeAttribute(intake.id)}" data-intake-status="new">Reopen</button>`,
    );
  }

  return `
    <article class="admin-intake-card is-status-${escapeAttribute(intake.status)}">
      <div class="admin-intake-card-header">
        <div>
          <h4>${escapeHtml(intake.name)}</h4>
          <p class="admin-intake-contact">
            <a href="mailto:${escapeAttribute(intake.email)}">${escapeHtml(intake.email)}</a>
            &middot; <a href="tel:${escapeAttribute(intake.phone)}">${escapeHtml(intake.phone)}</a>
          </p>
        </div>
        <div class="room-meta">
          <span class="pill">${escapeHtml(typeLabel)}</span>
          <span class="pill admin-intake-status-pill">${escapeHtml(intake.status)}</span>
        </div>
      </div>
      <div class="admin-detail-grid">${detailRows || '<div class="empty-state">No extra details.</div>'}</div>
      <p class="admin-intake-meta">Submitted ${escapeHtml(created)}</p>
      <div class="room-actions">${statusActions.join("")}</div>
    </article>
  `;
}

function renderAdminIntakes(currentState) {
  const list = document.getElementById("admin-intakes-list");
  if (!list) {
    return;
  }

  const typeFilter = document.getElementById("admin-intakes-type-filter")?.value || "";
  const statusFilter = document.getElementById("admin-intakes-status-filter")?.value || "";
  const intakes = (currentState.adminIntakes || []).filter((item) => {
    if (typeFilter && item.intake_type !== typeFilter) return false;
    if (statusFilter && item.status !== statusFilter) return false;
    return true;
  });

  list.innerHTML = intakes.length
    ? intakes.map(renderAdminIntakeCard).join("")
    : '<div class="empty-state">No submissions match these filters yet.</div>';
}

function formatScheduleMinutes(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

function renderAdminStaffSchedule(rows) {
  const list = document.getElementById("admin-schedule-list");
  if (!list) return;
  if (!rows || !rows.length) {
    list.innerHTML = '<div class="empty-state">No active staff for this date.</div>';
    return;
  }
  list.innerHTML = rows
    .map((row) => {
      const windows = (row.windows || [])
        .map((w) => `<span class="pill">${formatScheduleMinutes(w.start_minute)}–${formatScheduleMinutes(w.end_minute)}</span>`)
        .join(" ");
      return `
        <div class="admin-schedule-row">
          <strong>${escapeHtml(row.name)}</strong>
          <div class="admin-schedule-windows">${windows || '<span class="empty-state">Not available</span>'}</div>
        </div>`;
    })
    .join("");
}

async function loadAdminStaffSchedule() {
  const dateInput = document.getElementById("admin-schedule-date");
  if (!dateInput) return;
  if (!dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0, 10);
  }
  try {
    renderAdminStaffSchedule(await api.getAdminStaffSchedule(dateInput.value));
  } catch (error) {
    setState({ message: error.message });
  }
}

function formatActivityAction(action) {
  return action.replaceAll("_", " ");
}

function normalizeTestCaseHealth(health) {
  return String(health || "working")
    .trim()
    .toLowerCase()
    .replaceAll(" ", "_")
    .replaceAll("-", "_");
}

function getTestCaseHealthMeta(health) {
  return TEST_CASE_HEALTH_META[normalizeTestCaseHealth(health)] || TEST_CASE_HEALTH_META.working;
}

function getActiveRooms(rooms) {
  return (rooms || []).filter((room) => room.active);
}

function parseListInput(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderStaffImage(photoUrl, label, className = "staff-avatar") {
  if (photoUrl) {
    return `<img class="${escapeAttribute(className)}" src="${escapeAttribute(photoUrl)}" alt="${escapeAttribute(label)}" loading="lazy" />`;
  }
  return `<div class="${escapeAttribute(className)} staff-avatar-fallback">${escapeHtml(String(label || "").slice(0, 1).toUpperCase())}</div>`;
}

function setStaffPhotoPreview(photoUrl, name = "Staff member") {
  if (!elements.adminStaffPhotoPreview) {
    return;
  }

  elements.adminStaffPhotoPreview.innerHTML = photoUrl
    ? `
        <div class="staff-photo-preview-card">
          ${renderStaffImage(photoUrl, name, "staff-photo-preview-image")}
          <div class="staff-option-copy">
            <strong>${escapeHtml(name)}</strong>
            <span>Current profile image saved for this staff profile.</span>
          </div>
        </div>
      `
    : "Upload a JPG photo to show this staff member on room and booking pages.";
  elements.adminStaffPhotoPreview.classList.toggle("empty-state", !photoUrl);
}

function resetStaffProfileForm() {
  editingStaffProfileId = null;
  elements.adminStaffProfileForm?.reset();
  if (elements.adminStaffProfileId) {
    elements.adminStaffProfileId.value = "";
  }
  if (elements.adminStaffPhotoUrl) {
    elements.adminStaffPhotoUrl.value = "";
  }
  if (elements.adminStaffPhotoFile) {
    elements.adminStaffPhotoFile.value = "";
  }
  const activeCheckbox = elements.adminStaffProfileForm?.querySelector("input[name='active']");
  if (activeCheckbox) {
    activeCheckbox.checked = true;
  }
  setStaffPhotoPreview(null);
}

function populateStaffProfileForm(profile) {
  if (!elements.adminStaffProfileForm) {
    return;
  }

  editingStaffProfileId = profile.id;
  elements.adminStaffProfileForm.elements.name.value = profile.name || "";
  elements.adminStaffProfileForm.elements.description.value = profile.description || "";
  elements.adminStaffProfileForm.elements.skills.value = (profile.skills || []).join(", ");
  elements.adminStaffProfileForm.elements.talents.value = (profile.talents || []).join(", ");
  elements.adminStaffProfileForm.elements.services.value = (profile.services || []).join(", ");
  elements.adminStaffProfileForm.elements.bio.value = profile.bio || "";
  elements.adminStaffProfileForm.elements.portfolio_url.value = profile.portfolio_url || "";
  elements.adminStaffProfileForm.elements.headshot_urls.value = (profile.headshot_urls || []).join("\n");
  elements.adminStaffProfileForm.elements.add_on_price_cents.value = profile.add_on_price_cents || 0;
  elements.adminStaffProfileForm.elements.equipment_rental_cost_cents.value = profile.equipment_rental_cost_cents || 0;
  elements.adminStaffProfileForm.elements.role_title.value = profile.role_title || "";
  elements.adminStaffProfileForm.elements.notification_email.value = profile.notification_email || "";
  elements.adminStaffProfileForm.elements.notification_phone.value = profile.notification_phone || "";
  elements.adminStaffProfileForm.elements.notify_by_email.checked = profile.notify_by_email !== false;
  elements.adminStaffProfileForm.elements.notify_by_sms.checked = Boolean(profile.notify_by_sms);
  elements.adminStaffProfileForm.elements.booking_requires_approval.checked = profile.booking_requires_approval !== false;
  elements.adminStaffProfileForm.elements.linked_user_email.value = "";
  elements.adminStaffProfileForm.elements.active.checked = Boolean(profile.active);
  if (elements.adminStaffProfileId) {
    elements.adminStaffProfileId.value = profile.id;
  }
  if (elements.adminStaffPhotoUrl) {
    elements.adminStaffPhotoUrl.value = profile.photo_url || "";
  }
  if (elements.adminStaffPhotoFile) {
    elements.adminStaffPhotoFile.value = "";
  }
  setStaffPhotoPreview(profile.photo_url, profile.name);
}

function getSelectedManualStaffIds() {
  if (!elements.adminManualStaffOptions) {
    return [];
  }

  return Array.from(
    elements.adminManualStaffOptions.querySelectorAll("input[type='checkbox']:checked"),
  ).map((input) => input.value);
}

function renderStaffTagRow(label, values = []) {
  if (!values.length) {
    return "";
  }

  return `
    <div class="staff-tag-group">
      <span>${escapeHtml(label)}</span>
      <div class="preview-pill-row">
        ${values.map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join("")}
      </div>
    </div>
  `;
}

function formatAddress(address) {
  if (!address) {
    return "No billing address";
  }

  return [
    address.line1,
    address.line2,
    [address.city, address.state].filter(Boolean).join(", "),
    [address.postal_code, address.country].filter(Boolean).join(" "),
  ]
    .filter(Boolean)
    .map(escapeHtml)
    .join("<br />");
}

function renderAccountField(label, value, { mono = false, valueHtml = null } = {}) {
  const renderedValue = valueHtml ?? escapeHtml(value || "Not provided");
  return `
    <div class="admin-detail-field${mono ? " is-mono" : ""}">
      <span>${escapeHtml(label)}</span>
      <div class="admin-detail-value">${renderedValue}</div>
    </div>
  `;
}

function getAccountRole(account) {
  return account?.role || (account?.is_admin ? "Admin" : "Customer");
}

function getAccountRoleLabel(account) {
  const role = getAccountRole(account);
  if (role === "AdminManager") {
    return "Admin Manager";
  }
  return role === "Admin" ? "Admin" : "Customer";
}

function isAdminManagerAccount(account) {
  return getAccountRole(account) === "AdminManager";
}

function renderAccountRolePill(account) {
  return `<span class="pill">${escapeHtml(getAccountRoleLabel(account))}</span>`;
}

function renderAdminAccountListItem(account, isSelected) {
  return `
    <button class="admin-account-list-item${isSelected ? " is-selected" : ""}" type="button" data-admin-action="select-account" data-user-id="${escapeAttribute(account.id)}">
      <div class="admin-account-list-top">
        <strong>${escapeHtml(account.full_name || account.email)}</strong>
        <span>${escapeHtml(account.email)}</span>
      </div>
      <div class="room-meta">
        ${renderAccountRolePill(account)}
        <span class="pill">${escapeHtml(account.booking_count)} booking${account.booking_count === 1 ? "" : "s"}</span>
      </div>
      <p>${escapeHtml(account.phone ? formatPhone(account.phone) : "No phone on file")}</p>
      <p>${account.billing_address ? "Billing address on file" : "No billing address on file"}</p>
    </button>
  `;
}

function renderAdminAccountDetail(account, currentUser) {
  const isCurrentUser = String(account.id) === String(currentUser?.id || "");
  const canManageRoles = isAdminManagerAccount(currentUser);
  const currentRole = getAccountRole(account);
  const deleteControl = isCurrentUser
    ? `
        <button class="ghost-button" type="button" disabled>Signed in on this account</button>
        <p class="field-help">Delete your own profile from the account page so this admin session can close cleanly.</p>
      `
    : `
        <button class="ghost-button room-action-danger" type="button" data-admin-action="delete-user-account" data-user-id="${escapeAttribute(account.id)}" data-user-email="${escapeAttribute(account.email)}">
          Delete account
        </button>
      `;

  return `
    <article class="admin-account-detail-card">
      <div class="admin-account-detail-header">
        <div>
          <h4>${escapeHtml(account.full_name || account.email)}</h4>
          <p>${escapeHtml(account.email)}</p>
        </div>
        <div class="room-meta">
          ${renderAccountRolePill(account)}
          <span class="pill">${account.opt_in_email ? "Email opt-in" : "Email opt-out"}</span>
          <span class="pill">${account.opt_in_sms ? "SMS opt-in" : "SMS opt-out"}</span>
        </div>
      </div>

      <div class="admin-account-stats">
        <article class="metric-card">
          <span class="metric-label">Bookings</span>
          <strong class="metric-value">${escapeHtml(account.booking_count)}</strong>
        </article>
        <article class="metric-card">
          <span class="metric-label">Last booking</span>
          <strong class="metric-value metric-value-small">${escapeHtml(account.last_booking_at ? formatBookingDate(account.last_booking_at) : "No bookings yet")}</strong>
        </article>
      </div>

      <section class="admin-account-section">
        <h4>Personal details</h4>
        <div class="admin-detail-grid">
          ${renderAccountField("Full name", account.full_name || "Not provided")}
          ${renderAccountField("Email", account.email, { mono: true })}
          ${renderAccountField("Phone", account.phone ? formatPhone(account.phone) : "No phone on file")}
          ${renderAccountField("Birthday", account.birthday ? formatDateOnly(account.birthday) : "Not provided")}
        </div>
      </section>

      <section class="admin-account-section">
        <h4>Billing</h4>
        <p class="field-help">Card details are handled by Stripe and are not stored in this app.</p>
        <div class="admin-detail-grid">
          ${renderAccountField("Billing address", null, { valueHtml: formatAddress(account.billing_address) })}
        </div>
      </section>

      <section class="admin-account-section">
        <h4>Role access</h4>
        <p class="field-help">Admin Managers can change account roles. Admins can use the admin tools, but cannot grant or remove roles.</p>
        ${
          canManageRoles
            ? `
              <div class="profile-grid profile-grid-tight">
                <label>
                  <span>Role</span>
                  <select data-admin-role-select data-user-id="${escapeAttribute(account.id)}">
                    <option value="Customer" ${currentRole === "Customer" ? "selected" : ""}>Customer</option>
                    <option value="Admin" ${currentRole === "Admin" ? "selected" : ""}>Admin</option>
                    <option value="AdminManager" ${currentRole === "AdminManager" ? "selected" : ""}>Admin Manager</option>
                  </select>
                </label>
              </div>
              <div class="hero-actions">
                <button class="ghost-button" type="button" data-admin-action="update-user-role" data-user-id="${escapeAttribute(account.id)}" data-user-email="${escapeAttribute(account.email)}">
                  Update role
                </button>
              </div>
            `
            : `<div class="admin-detail-grid">${renderAccountField("Role", getAccountRoleLabel(account))}</div>`
        }
      </section>

      <section class="admin-account-section">
        <h4>Account lifecycle</h4>
        <div class="admin-detail-grid">
          ${renderAccountField("Created", formatBookingDate(account.created_at))}
          ${renderAccountField("Updated", account.updated_at ? formatBookingDate(account.updated_at) : "No later updates")}
        </div>
      </section>

      <div class="room-actions">
        ${deleteControl}
      </div>
    </article>
  `;
}

function renderAdminTestCaseCard(testCase) {
  const healthMeta = getTestCaseHealthMeta(testCase.health);
  const commands = testCase.commands || [];
  return `
    <article class="admin-test-case-card ${healthMeta.className}">
      <div class="admin-test-case-header">
        <div>
          <h4>${escapeHtml(testCase.title)}</h4>
          <p>${escapeHtml(testCase.summary)}</p>
        </div>
        <div class="room-meta">
          <span class="pill test-health-pill ${healthMeta.className}">
            <span class="test-status-light ${healthMeta.className}"></span>
            ${healthMeta.label}
          </span>
          <span class="pill">${escapeHtml(testCase.area)}</span>
          <span class="pill">${escapeHtml(testCase.status)}</span>
        </div>
      </div>
      <div class="admin-detail-grid">
        <div class="admin-detail-field is-mono">
          <span>Source file</span>
          <div class="admin-detail-value">${escapeHtml(testCase.source_file)}</div>
        </div>
        <div class="admin-detail-field is-mono">
          <span>Test id</span>
          <div class="admin-detail-value">${escapeHtml(testCase.source_test)}</div>
        </div>
      </div>
      <div class="admin-test-case-section">
        <span>Covered paths</span>
        <div class="preview-pill-row">
          ${(testCase.covered_paths || []).map((path) => `<span class="pill">${escapeHtml(path)}</span>`).join("")}
        </div>
      </div>
      <div class="admin-test-case-section">
        <span>Run command</span>
        ${commands.length
          ? commands
          .map(
            (command) => `
              <div class="admin-detail-field is-mono">
                <div class="admin-detail-value">${escapeHtml(command)}</div>
              </div>
            `,
          )
          .join("")
          : `
              <div class="admin-detail-field">
                <div class="admin-detail-value">No automated command is registered for this case yet.</div>
              </div>
            `}
      </div>
    </article>
  `;
}

function renderAdminTestCaseSummary(testCases) {
  if (!elements.adminTestCaseSummary) {
    return;
  }

  const counts = {
    working: 0,
    needs_fix: 0,
    not_working: 0,
  };

  for (const testCase of testCases) {
    const health = normalizeTestCaseHealth(testCase.health);
    if (Object.hasOwn(counts, health)) {
      counts[health] += 1;
    }
  }

  const cards = [
    {
      label: "Working",
      value: counts.working,
      className: "test-health-working",
      description: "Covered backend cases that are passing.",
    },
    {
      label: "Needs fix",
      value: counts.needs_fix,
      className: "test-health-needs-fix",
      description: "Cases that still need follow-up work.",
    },
    {
      label: "Not working",
      value: counts.not_working,
      className: "test-health-not-working",
      description: "Cases marked broken or still missing.",
    },
    {
      label: "Total cases",
      value: testCases.length,
      className: "test-health-total",
      description: "All backend test cases tracked in this dashboard.",
    },
  ];

  elements.adminTestCaseSummary.innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card test-status-card ${card.className}">
          <div class="room-meta">
            <span class="test-status-light ${card.className}"></span>
            <span class="metric-label">${escapeHtml(card.label)}</span>
          </div>
          <strong class="metric-value">${escapeHtml(card.value)}</strong>
          <span class="status-detail">${escapeHtml(card.description)}</span>
        </article>
      `,
    )
    .join("");
}

function renderManualBookingStaffOptions(currentState) {
  if (!elements.adminManualStaffSection || !elements.adminManualStaffOptions || !elements.adminRoomSelect) {
    return;
  }

  const room = (currentState.rooms || []).find((item) => String(item.id) === elements.adminRoomSelect.value);
  const staffRoles = room?.staff_roles || [];
  const selectedIds = new Set(getSelectedManualStaffIds());

  if (!staffRoles.length) {
    elements.adminManualStaffOptions.innerHTML = "";
    elements.adminManualStaffSection.classList.add("hidden");
    return;
  }

  elements.adminManualStaffSection.classList.remove("hidden");
  elements.adminManualStaffOptions.innerHTML = staffRoles
    .map(
      (role) => `
        <label class="staff-option-card staff-option-card-compact">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${escapeAttribute(role.id)}" ${selectedIds.has(role.id) ? "checked" : ""} />
          </div>
          ${renderStaffImage(role.photo_url, role.name)}
          <div class="staff-option-copy">
            <strong>${escapeHtml(role.name)}</strong>
            <span>${escapeHtml(role.description || "Optional booking add-on.")}</span>
            ${renderStaffTagRow("Skills", role.skills || [])}
          </div>
          <strong class="staff-option-price">${formatMoney(role.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function renderAdminBookingCompactRow(booking) {
  const isStaffBooking = booking.booking_kind === "staff";
  const bookingKind = booking.booking_kind || "room";
  const statusClass = getStatusClass(booking.status);
  const guestName = booking.user_full_name || booking.user_email || "Guest";
  const venueLabel = isStaffBooking
    ? booking.staff_name || booking.service_type || "Staff booking"
    : booking.room_name || "Room";
  const bookingHref = `/booking?id=${encodeURIComponent(booking.id)}${isStaffBooking ? "&kind=staff" : ""}`;
  const refundButton =
    !isStaffBooking &&
    booking.price_cents > 0 &&
    (booking.status === "Paid" || booking.status === "Cancelled" || booking.status === "Completed")
      ? `<button class="admin-icon-button admin-action-button is-danger" type="button" data-admin-action="refund" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}" data-amount="${escapeAttribute(booking.price_cents)}">Refund</button>`
      : "";
  const manualPaidButton =
    booking.status === "PendingPayment" && booking.price_cents > 0
      ? `<button class="admin-icon-button admin-action-button" type="button" data-admin-action="mark-paid" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Mark paid</button>`
      : "";
  const waivePaymentButton =
    booking.status === "PendingPayment"
      ? `<button class="admin-icon-button admin-action-button" type="button" data-admin-action="waive-payment" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Free</button>`
      : "";
  const checkInButton =
    !isStaffBooking && booking.status === "Paid" && !booking.checked_in_at
      ? `<button class="admin-icon-button admin-action-button is-primary" type="button" data-admin-action="check-in" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Arrived</button>`
      : "";

  return `
    <article class="admin-booking-row is-${escapeAttribute(statusClass)}">
      <div class="admin-booking-row-select" aria-hidden="true"></div>
      <div class="admin-booking-row-cell admin-booking-row-customer">
        <strong>${escapeHtml(guestName)}</strong>
        <span>${escapeHtml(booking.booking_code)}</span>
      </div>
      <div class="admin-booking-row-cell">
        <strong>${escapeHtml(venueLabel)}</strong>
        <span class="pill pill-xs ${isStaffBooking ? "admin-kind-staff" : "admin-kind-room"}">${isStaffBooking ? "Staff" : "Room"}</span>
      </div>
      <div class="admin-booking-row-cell">
        <strong>${escapeHtml(formatDateOnly(booking.start_time))}</strong>
        <span>${escapeHtml(formatTimeOnly(booking.start_time))}</span>
      </div>
      <div class="admin-booking-row-cell">
        <strong>${escapeHtml(formatDuration(booking.duration_minutes))}</strong>
        <span>${escapeHtml(formatMoney(booking.price_cents, booking.currency))}</span>
      </div>
      <div class="admin-booking-row-status">
        <span class="pill ${escapeAttribute(statusClass)}">${escapeHtml(getStatusLabel(booking.status))}</span>
      </div>
      <div class="admin-booking-row-actions">
        <a class="admin-icon-button" href="${escapeAttribute(bookingHref)}" aria-label="Open booking">✎</a>
        ${manualPaidButton}
        ${waivePaymentButton}
        ${checkInButton}
        ${refundButton}
      </div>
    </article>
  `;
}

function renderAdminBookingCard(booking) {
  if (document.body?.dataset.page === "admin") {
    return renderAdminBookingCompactRow(booking);
  }

  const isStaffBooking = booking.booking_kind === "staff";
  const bookingKind = booking.booking_kind || "room";
  const refundButton =
    !isStaffBooking &&
    booking.price_cents > 0 &&
    (booking.status === "Paid" || booking.status === "Cancelled" || booking.status === "Completed")
      ? `<button class="ghost-button admin-booking-action" type="button" data-admin-action="refund" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}" data-amount="${escapeAttribute(booking.price_cents)}">Refund</button>`
      : "";
  const manualPaidButton =
    booking.status === "PendingPayment" && booking.price_cents > 0
      ? `<button class="ghost-button admin-booking-action" type="button" data-admin-action="mark-paid" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Mark paid manually</button>`
      : "";
  const waivePaymentButton =
    booking.status === "PendingPayment"
      ? `<button class="ghost-button admin-booking-action" type="button" data-admin-action="waive-payment" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Skip Stripe and mark free</button>`
      : "";
  const checkInButton =
    !isStaffBooking && booking.status === "Paid" && !booking.checked_in_at
      ? `<button class="primary-button admin-booking-action" type="button" data-admin-action="check-in" data-booking-kind="${escapeAttribute(bookingKind)}" data-booking-id="${escapeAttribute(booking.id)}">Mark arrived</button>`
      : "";
  const staffAssignments = booking.staff_assignments || [];
  const guestName = booking.user_full_name || "Guest name not set";
  const guestPhone = booking.user_phone ? formatPhone(booking.user_phone) : "No phone";
  const phoneHref = normalizePhoneHref(booking.user_phone);
  const urgencyLabel = getAdminBookingUrgencyLabel(booking);
  const bookedAt = booking.created_at ? formatBookingDate(booking.created_at) : "Booking time unavailable";
  const paidAt = booking.confirmed_at ? formatBookingDate(booking.confirmed_at) : "Not paid yet";
  const checkedInAt = booking.checked_in_at ? formatBookingDate(booking.checked_in_at) : "Not checked in";
  const cancelledAt = booking.cancelled_at ? formatBookingDate(booking.cancelled_at) : "Not cancelled";
  const paymentReference = booking.payment_intent_id || "No payment reference yet";
  const originalAmount = booking.original_price_cents ?? booking.price_cents;
  const headingTitle = isStaffBooking
    ? booking.staff_name || booking.service_type || "Staff booking"
    : booking.room_name || "Room";
  const staffMarkup = isStaffBooking
    ? `
        <span class="pill">${escapeHtml(booking.staff_name || "Assigned staff")}</span>
        ${booking.service_type ? `<span class="pill">${escapeHtml(booking.service_type)}</span>` : ""}
      `
    : staffAssignments.length
      ? staffAssignments.map((assignment) => `<span class="pill">${escapeHtml(assignment.name)}</span>`).join("")
      : '<span class="pill muted">No staff attached</span>';

  return `
    <article class="booking-card admin-booking-record ${escapeAttribute(getStatusClass(booking.status))}">
      <div class="admin-booking-header">
        <div class="admin-booking-heading">
          <div class="admin-booking-topline">
            <span class="admin-booking-code">${escapeHtml(booking.booking_code)}</span>
            <span class="pill">${isStaffBooking ? "Staff booking" : "Room booking"}</span>
            ${urgencyLabel ? `<span class="pill admin-booking-urgency">${escapeHtml(urgencyLabel)}</span>` : ""}
          </div>
          <h4>${escapeHtml(headingTitle)}</h4>
          <p>${formatBookingDate(booking.start_time)} to ${formatBookingDate(booking.end_time)}</p>
        </div>
        <div class="room-meta admin-booking-pill-stack">
          <span class="pill ${escapeAttribute(getStatusClass(booking.status))}">${escapeHtml(getStatusLabel(booking.status))}</span>
          <span class="pill">${formatDuration(booking.duration_minutes)}</span>
          <span class="pill">${formatMoney(booking.price_cents, booking.currency)}</span>
        </div>
      </div>
      <div class="admin-booking-primary-grid">
        <div class="availability-preview admin-booking-panel-card">
          <span class="availability-label">Guest</span>
          <p><strong>${escapeHtml(guestName)}</strong></p>
          <div class="admin-booking-contact-links">
            ${booking.user_email ? `<a class="ghost-link" href="${escapeAttribute(`mailto:${String(booking.user_email).replace(/[\r\n]/g, "")}`)}">${escapeHtml(booking.user_email)}</a>` : "<span>No email</span>"}
            ${phoneHref ? `<a class="ghost-link" href="${escapeAttribute(phoneHref)}">${escapeHtml(guestPhone)}</a>` : `<span>${escapeHtml(guestPhone)}</span>`}
          </div>
          <div class="room-meta">
            <span class="pill">${booking.user_id ? "Existing account" : "Snapshot only"}</span>
          </div>
        </div>
        <div class="availability-preview admin-booking-panel-card">
          <span class="availability-label">Timeline</span>
          ${renderAdminBookingTimelineRow("Booked", bookedAt)}
          ${renderAdminBookingTimelineRow("Paid", paidAt)}
          ${!isStaffBooking ? renderAdminBookingTimelineRow("Checked in", checkedInAt) : ""}
          ${renderAdminBookingTimelineRow("Cancelled", cancelledAt)}
        </div>
        <div class="availability-preview admin-booking-panel-card">
          <span class="availability-label">Payment</span>
          ${renderAdminBookingTimelineRow("Status", getStatusLabel(booking.status))}
          ${renderAdminBookingTimelineRow("Original", formatMoney(originalAmount, booking.currency))}
          ${booking.discount_cents ? renderAdminBookingTimelineRow("Discount", `-${formatMoney(booking.discount_cents, booking.currency)}`) : ""}
          ${booking.promo_code ? renderAdminBookingTimelineRow("Promo", booking.promo_code) : ""}
          ${renderAdminBookingTimelineRow("Amount", formatMoney(booking.price_cents, booking.currency))}
          ${renderAdminBookingTimelineRow("Reference", paymentReference)}
        </div>
      </div>
      <div class="admin-booking-secondary-grid">
        <div class="admin-booking-info-block">
          <span class="availability-label">${isStaffBooking ? "Session details" : "Staff"}</span>
          <div class="preview-pill-row">${staffMarkup}</div>
        </div>
        ${booking.location_label ? `<div class="admin-booking-info-block"><span class="availability-label">Location</span><p>${escapeHtml(booking.location_label)}</p></div>` : ""}
        ${booking.note ? `<div class="admin-booking-info-block"><span class="availability-label">Notes</span><p>${escapeHtml(booking.note)}</p></div>` : ""}
        ${booking.cancellation_reason ? `<div class="admin-booking-info-block"><span class="availability-label">Cancellation reason</span><p>${escapeHtml(booking.cancellation_reason)}</p></div>` : ""}
      </div>
      <div class="admin-booking-actions">
        ${manualPaidButton}
        ${waivePaymentButton}
        ${checkInButton}
        ${refundButton}
      </div>
    </article>
  `;
}

function getFilteredScheduleBookings(currentState) {
  return (currentState.adminBookings || [])
    .filter((booking) => booking.booking_kind !== "staff")
    .filter((booking) => getDateKey(booking.start_time) === selectedAdminScheduleDate)
    .filter((booking) => selectedAdminScheduleRoomId === "all" || String(booking.room_id) === selectedAdminScheduleRoomId)
    .sort((left, right) => new Date(left.start_time).getTime() - new Date(right.start_time).getTime());
}

function renderAdminDaySummary(currentState) {
  if (!elements.adminDaySummary) {
    return;
  }

  const bookings = getFilteredScheduleBookings(currentState);
  const activeStatuses = new Set(["PendingPayment", "Paid", "Completed"]);
  const activeCount = bookings.filter((booking) => activeStatuses.has(booking.status)).length;
  const cancelledCount = bookings.filter((booking) => ["Cancelled", "Refunded"].includes(booking.status)).length;
  const guestCount = new Set(bookings.map((booking) => booking.user_email || booking.user_id || booking.id)).size;
  const revenue = bookings
    .filter((booking) => ["Paid", "Completed", "Refunded"].includes(booking.status))
    .reduce((total, booking) => total + (booking.price_cents || 0), 0);
  const cards = [
    { label: "Bookings on this day", value: bookings.length },
    { label: "Active sessions", value: activeCount },
    { label: "Cancelled or refunded", value: cancelledCount },
    { label: "Guests", value: guestCount },
    { label: "Booked revenue", value: formatMoney(revenue) },
  ];

  elements.adminDaySummary.innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card">
          <span class="metric-label">${escapeHtml(card.label)}</span>
          <strong class="metric-value">${escapeHtml(card.value)}</strong>
        </article>
      `,
    )
    .join("");
}

function renderScheduleBlocks(bookings) {
  return bookings
    .map((booking) => {
      const start = new Date(booking.start_time);
      const end = new Date(booking.end_time);
      const startMinutes = start.getHours() * 60 + start.getMinutes();
      const endMinutes = end.getHours() * 60 + end.getMinutes();
      const businessStart = 12 * 60;
      const businessEnd = 20 * 60;
      const clampedStart = Math.max(startMinutes, businessStart);
      const clampedEnd = Math.min(endMinutes, businessEnd);
      const width = Math.max(((clampedEnd - clampedStart) / (businessEnd - businessStart)) * 100, 10);
      const left = ((clampedStart - businessStart) / (businessEnd - businessStart)) * 100;
      const guestLabel = booking.user_full_name || booking.user_email || "Guest";
      return `
        <article class="admin-schedule-block ${escapeAttribute(getStatusClass(booking.status))}" style="left:${left}%;width:${width}%;" title="${escapeAttribute(`${guestLabel} • ${booking.booking_code}`)}">
          <strong>${formatTimeOnly(booking.start_time)} to ${formatTimeOnly(booking.end_time)}</strong>
          <span>${escapeHtml(guestLabel)}</span>
          <span>${escapeHtml(booking.booking_code)}</span>
        </article>
      `;
    })
    .join("");
}

function getLocalDateString(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function renderAdminDaySchedule(currentState) {
  if (!elements.adminDaySchedule) {
    return;
  }

  const allRoomBookings = (currentState.adminBookings || []).filter((b) => b.booking_kind !== "staff");

  if (!selectedAdminScheduleDate || !getFilteredScheduleBookings(currentState).length) {
    const nextBookingDate = allRoomBookings
      .map((b) => getDateKey(b.start_time))
      .filter((d) => d >= getLocalDateString(new Date()))
      .sort()[0];
    if (nextBookingDate && nextBookingDate !== selectedAdminScheduleDate) {
      selectedAdminScheduleDate = nextBookingDate;
      if (elements.adminScheduleDate) {
        elements.adminScheduleDate.value = selectedAdminScheduleDate;
      }
    }
  }

  const bookings = getFilteredScheduleBookings(currentState);
  const rooms = (currentState.rooms || [])
    .filter((room) => selectedAdminScheduleRoomId === "all" || String(room.id) === selectedAdminScheduleRoomId)
    .sort((left, right) => left.name.localeCompare(right.name));
  const hourLabels = Array.from({ length: 8 }, (_value, index) => 12 + index);

  if (!rooms.length) {
    elements.adminDaySchedule.innerHTML = '<div class="empty-state">No rooms match the selected filter.</div>';
    return;
  }

  const activeStatuses = new Set(["PendingPayment", "Paid", "Completed"]);
  elements.adminDaySchedule.innerHTML = `
    <div class="admin-schedule-hours">
      <div></div>
      <div class="admin-schedule-hour-track">
        ${hourLabels
          .map((hour) => `<span>${new Intl.DateTimeFormat("en-US", { hour: "numeric" }).format(new Date(`2026-04-01T${String(hour).padStart(2, "0")}:00:00`))}</span>`)
          .join("")}
      </div>
    </div>
    ${
      rooms
        .map((room) => {
          const roomBookings = bookings.filter((booking) => String(booking.room_id) === String(room.id));
          const activeCount = roomBookings.filter((booking) => activeStatuses.has(booking.status)).length;
          const roomStatusClass = !room.active ? "muted" : activeCount > 0 ? "is-booked" : "is-available";
          return `
            <article class="admin-day-row">
              <div class="admin-day-room">
                <strong>${escapeHtml(room.name)}</strong>
                <span class="pill pill-xs ${roomStatusClass}">${activeCount > 0 ? `${activeCount} booking${activeCount === 1 ? "" : "s"}` : "Open"}</span>
              </div>
              <div class="admin-day-track">
                <div class="admin-day-grid">
                  ${hourLabels.map(() => '<span></span>').join("")}
                </div>
                ${roomBookings.length ? renderScheduleBlocks(roomBookings) : '<div class="admin-day-empty">Available all day</div>'}
              </div>
            </article>
          `;
        })
        .join("")
    }
  `;
}

function getFilteredRoomCalendarBookings(currentState) {
  const monthValue = safeMonthValue(selectedAdminCalendarMonth);
  return (currentState.adminBookings || [])
    .filter((booking) => booking.booking_kind !== "staff")
    .filter((booking) => getDateKey(booking.start_time).startsWith(monthValue))
    .filter((booking) => selectedAdminCalendarRoomId === "all" || String(booking.room_id) === selectedAdminCalendarRoomId)
    .sort((left, right) => new Date(left.start_time).getTime() - new Date(right.start_time).getTime());
}

function renderAdminRoomCalendarSummary(currentState) {
  const summaryElement = getAdminRoomCalendarSummaryElement();
  if (!summaryElement) {
    return;
  }

  const bookings = getFilteredRoomCalendarBookings(currentState);
  const bookedDays = new Set(bookings.map((booking) => getDateKey(booking.start_time))).size;
  const pendingCount = bookings.filter((booking) => booking.status === "PendingPayment").length;
  const settledCount = bookings.filter((booking) => ["Paid", "Completed"].includes(booking.status)).length;
  const revenue = bookings
    .filter((booking) => ["Paid", "Completed", "Refunded"].includes(booking.status))
    .reduce((total, booking) => total + (booking.price_cents || 0), 0);
  const cards = [
    { label: "Month", value: formatMonthHeading(selectedAdminCalendarMonth) },
    { label: "Room focus", value: getAdminRoomCalendarLabel(currentState) },
    { label: "Booked days", value: bookedDays },
    { label: "Sessions", value: bookings.length },
    { label: "Pending", value: pendingCount },
    { label: "Paid / completed", value: settledCount },
    { label: "Booked revenue", value: formatMoney(revenue) },
  ];

  summaryElement.innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card">
          <span class="metric-label">${escapeHtml(card.label)}</span>
          <strong class="metric-value">${escapeHtml(card.value)}</strong>
        </article>
      `,
    )
    .join("");
}

function renderAdminRoomCalendar(currentState) {
  const gridElement = getAdminRoomCalendarGridElement();
  if (!gridElement) {
    return;
  }

  const rooms = currentState.rooms || [];
  if (!rooms.length) {
    gridElement.innerHTML = '<div class="empty-state">Create a room first so the admin calendar has something to show.</div>';
    return;
  }

  const bookings = getFilteredRoomCalendarBookings(currentState);
  const bookingsByDate = bookings.reduce((accumulator, booking) => {
    const key = getDateKey(booking.start_time);
    accumulator[key] = accumulator[key] || [];
    accumulator[key].push(booking);
    return accumulator;
  }, {});
  const offset = getMonthStartOffset(selectedAdminCalendarMonth);
  const dayCount = getMonthDayCount(selectedAdminCalendarMonth);
  const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const roomLabel = getAdminRoomCalendarLabel(currentState);

  const cells = Array.from({ length: offset }, () => '<div class="admin-room-calendar-spacer" aria-hidden="true"></div>');

  for (let dayNumber = 1; dayNumber <= dayCount; dayNumber += 1) {
    const dayKey = getMonthDateKey(selectedAdminCalendarMonth, dayNumber);
    const dayBookings = bookingsByDate[dayKey] || [];
    const pendingCount = dayBookings.filter((booking) => booking.status === "PendingPayment").length;
    const activeCount = dayBookings.filter((booking) => ["PendingPayment", "Paid", "Completed"].includes(booking.status)).length;
    const revenue = dayBookings
      .filter((booking) => ["Paid", "Completed", "Refunded"].includes(booking.status))
      .reduce((total, booking) => total + (booking.price_cents || 0), 0);
    const roomHints = Array.from(new Set(dayBookings.map((booking) => booking.room_name).filter(Boolean))).slice(0, 2);
    const classNames = ["admin-room-calendar-day"];
    if (dayBookings.length) {
      classNames.push("is-busy");
    } else {
      classNames.push("is-open");
    }
    if (pendingCount) {
      classNames.push("is-pending");
    }
    if (dayBookings.length && dayBookings.every((booking) => ["Cancelled", "Refunded"].includes(booking.status))) {
      classNames.push("is-closed");
    }
    if (dayKey === todayString()) {
      classNames.push("is-today");
    }
    if (dayKey === selectedAdminScheduleDate) {
      classNames.push("is-selected");
    }

    const metaLine = dayBookings.length
      ? `${dayBookings.length} booking${dayBookings.length === 1 ? "" : "s"}`
      : "Open day";
    const supportLine = pendingCount
      ? `${pendingCount} pending payment`
      : activeCount
        ? `${activeCount} active session${activeCount === 1 ? "" : "s"}`
        : roomHints.join(" • ") || "No bookings yet";

    cells.push(`
      <button
        class="${classNames.join(" ")}"
        type="button"
        data-admin-calendar-date="${dayKey}"
        title="Open day board for ${dayKey}"
      >
        <strong>${dayNumber}</strong>
        <span>${escapeHtml(metaLine)}</span>
        <small>${escapeHtml(supportLine)}</small>
        ${revenue ? `<small>${formatMoney(revenue)}</small>` : '<small>Tap to open day board</small>'}
      </button>
    `);
  }

  gridElement.innerHTML = `
    <div class="admin-room-calendar-header">
      <div>
        <h4>${formatMonthHeading(selectedAdminCalendarMonth)}</h4>
        <p>${escapeHtml(roomLabel)}. Click any day to jump into the detailed day board.</p>
      </div>
      <div class="room-meta">
        <span class="pill">${escapeHtml(roomLabel)}</span>
        <span class="pill">${bookings.length} booking${bookings.length === 1 ? "" : "s"} this month</span>
      </div>
    </div>
    <div class="admin-room-calendar-weekdays">
      ${weekdayLabels.map((label) => `<span>${label}</span>`).join("")}
    </div>
    <div class="admin-room-calendar-cells">
      ${cells.join("")}
    </div>
  `;
}

function renderStaffCatalogCard(profile) {
  return `
    <article class="staff-profile-card">
      <div class="staff-profile-card-top">
        ${renderStaffImage(profile.photo_url, profile.name, "staff-profile-image")}
        <div class="staff-option-copy">
          <strong>${escapeHtml(profile.name)}</strong>
          <span>${escapeHtml(profile.description || "No profile summary added yet.")}</span>
        </div>
      </div>
      <div class="room-meta">
        <span class="pill">${formatMoney(profile.add_on_price_cents)}</span>
        <span class="pill ${profile.active ? "" : "muted"}">${profile.active ? "Active" : "Inactive"}</span>
      </div>
      ${renderStaffTagRow("Skills", profile.skills || [])}
      ${renderStaffTagRow("Talents", profile.talents || [])}
      <div class="room-actions">
        <button class="ghost-button" type="button" data-admin-action="edit-staff-profile" data-staff-profile-id="${escapeAttribute(profile.id)}">Edit profile</button>
        <button class="ghost-button" type="button" data-admin-action="toggle-staff-profile" data-staff-profile-id="${escapeAttribute(profile.id)}" data-next-active="${profile.active ? "false" : "true"}">${profile.active ? "Deactivate" : "Activate"}</button>
        <button class="ghost-button room-action-danger" type="button" data-admin-action="delete-staff-profile" data-staff-profile-id="${escapeAttribute(profile.id)}" data-staff-profile-name="${escapeAttribute(profile.name)}">Delete</button>
      </div>
    </article>
  `;
}

function renderRoomStaffAssignmentCard(room, staffProfiles) {
  const assignedIds = new Set((room.staff_roles || []).map((role) => role.id));
  const availableProfiles = (staffProfiles || []).filter((profile) => profile.active || assignedIds.has(profile.id));

  return `
    <article class="admin-room-staff-card" data-room-card data-room-id="${escapeAttribute(room.id)}">
      <header class="admin-room-staff-header">
        <div>
          <h4>${escapeHtml(room.name)}</h4>
          <p>${escapeHtml(room.description || "No description")}</p>
        </div>
        <div class="room-meta">
          <span class="pill">${formatMoney(room.hourly_rate_cents)}/hour</span>
          <span class="pill">${assignedIds.size} assigned staff profile${assignedIds.size === 1 ? "" : "s"}</span>
        </div>
      </header>
      <div class="staff-assignment-grid">
        ${availableProfiles.length
          ? availableProfiles
              .map(
                (profile) => `
                  <label class="staff-option-card staff-option-card-compact">
                    <div class="staff-option-toggle">
                      <input type="checkbox" value="${escapeAttribute(profile.id)}" ${assignedIds.has(profile.id) ? "checked" : ""} />
                    </div>
                    ${renderStaffImage(profile.photo_url, profile.name)}
                    <div class="staff-option-copy">
                      <strong>${escapeHtml(profile.name)}</strong>
                      <span>${escapeHtml(profile.description || "No summary added yet.")}</span>
                    </div>
                    <strong class="staff-option-price">${formatMoney(profile.add_on_price_cents)}</strong>
                  </label>
                `,
              )
              .join("")
          : '<div class="empty-state">Create staff profiles above before assigning anyone to a room.</div>'}
      </div>
      <div class="room-actions">
        <button class="primary-button" type="button" data-admin-action="save-room-staff" data-room-id="${escapeAttribute(room.id)}">Save room staff</button>
      </div>
    </article>
  `;
}

function collectRoomStaffPayload(roomCard, staffProfiles) {
  const selectedIds = Array.from(
    roomCard.querySelectorAll("input[type='checkbox']:checked"),
  ).map((input) => input.value);
  const byId = new Map((staffProfiles || []).map((profile) => [String(profile.id), profile]));

  return selectedIds.flatMap((staffProfileId) => {
    const profile = byId.get(staffProfileId);
    if (!profile) {
      return [];
    }
    return [
      {
        id: String(profile.id),
        name: profile.name,
        description: profile.description || null,
        add_on_price_cents: profile.add_on_price_cents || 0,
        photo_url: profile.photo_url || null,
        skills: profile.skills || [],
        talents: profile.talents || [],
      },
    ];
  });
}

export function initAdminView(actions) {
  if (
    !elements.adminEmpty ||
    !elements.adminBookingLookupForm ||
    !elements.adminBookingResults ||
    !elements.adminManualBookingForm ||
    !elements.adminRoomSelect
  ) {
    return;
  }

  // Capture actions for the polling lifecycle (Today live ops dashboard).
  adminTodayActionsRef = actions;

  elements.adminTodayPrintButton?.addEventListener("click", () => {
    document.body.classList.add("admin-printing-today");
    window.print();
    window.setTimeout(() => document.body.classList.remove("admin-printing-today"), 200);
  });

  // Inline Check-in button inside the Today's live roster. Reuses the existing
  // admin check-in endpoint but DOESN'T pull the admin off the Overview tab.
  elements.adminTodayGlance?.addEventListener("click", async (event) => {
    const button = event.target.closest('[data-admin-action="check-in"]');
    if (!button) return;
    event.preventDefault();
    try {
      setState({ message: "Marking guest as arrived..." });
      await api.adminCheckInBooking(button.dataset.bookingId);
      await actions.refreshAdminToday?.("Guest checked in.");
      // Also refresh the bookings list so the queue tab stays in sync.
      await actions.refreshAll?.("");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminBookingLookupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.adminBookingLookupForm);
    try {
      setState({ message: "Searching bookings..." });
      adminSearchResults = await api.adminLookupBookings({
        email: form.get("email"),
        booking_code: form.get("booking_code"),
        status: form.get("status"),
      });
      setActiveAdminSubpage("bookings", "queue");
      renderAdminView(actions.getState());
      setState({ message: "Admin booking results loaded." });
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminBookingClearButton?.addEventListener("click", () => {
      adminSearchResults = null;
      selectedAdminBookingQuickFilter = "all";
      setActiveAdminSubpage("bookings", "queue");
      elements.adminBookingLookupForm?.reset();
      renderAdminView(actions.getState());
      setState({ message: "Booking filters cleared." });
  });

  elements.adminRoomSelect?.addEventListener("change", () => {
    renderManualDurationOptions(actions.getState());
    renderManualBookingStaffOptions(actions.getState());
  });

  getAdminPromoDiscountTypeSelect()?.addEventListener("change", () => {
    syncAdminPromoDiscountFields();
  });

  document.getElementById("admin-promo-cancel-edit")?.addEventListener("click", () => {
    resetAdminPromoForm();
  });

  elements.adminScheduleDate?.addEventListener("change", () => {
    selectedAdminScheduleDate = elements.adminScheduleDate.value || todayString();
    renderAdminView(actions.getState());
  });

  elements.adminScheduleRoomFilter?.addEventListener("change", () => {
    selectedAdminScheduleRoomId = elements.adminScheduleRoomFilter.value || "all";
    renderAdminView(actions.getState());
  });

  getAdminCalendarMonthInput()?.addEventListener("change", () => {
    selectedAdminCalendarMonth = safeMonthValue(getAdminCalendarMonthInput()?.value);
    renderAdminView(actions.getState());
  });

  getAdminCalendarRoomFilter()?.addEventListener("change", () => {
    selectedAdminCalendarRoomId = getAdminCalendarRoomFilter()?.value || "all";
    renderAdminView(actions.getState());
  });

  const applyAdminBookingQuickFilter = (filterKey) => {
    selectedAdminBookingQuickFilter = filterKey || "all";
    renderAdminView(actions.getState());
  };

  elements.adminBookingQuickSummary?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-booking-filter]");
    if (!button) {
      return;
    }
    applyAdminBookingQuickFilter(button.dataset.adminBookingFilter);
  });

  elements.adminBookingQuickFilters?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-booking-filter]");
    if (!button) {
      return;
    }
    applyAdminBookingQuickFilter(button.dataset.adminBookingFilter);
  });

  elements.adminClearDayButton?.addEventListener("click", async () => {
    const targetDate = elements.adminScheduleDate?.value || selectedAdminScheduleDate;
    if (!targetDate) {
      setState({ message: "Choose a day first." });
      return;
    }
    const confirmed = window.confirm(`Delete all bookings on ${targetDate}? This permanently removes them.`);
    if (!confirmed) {
      return;
    }

    try {
      setState({ message: "Clearing bookings for selected day..." });
      const result = await api.adminClearBookingsForDay({ date: targetDate });
      adminSearchResults = null;
      setActiveAdminSubpage("bookings", "schedule");
      await actions.refreshAll(`${result.deleted_count} booking${result.deleted_count === 1 ? "" : "s"} cleared for ${targetDate}.`);
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminClearPastButton?.addEventListener("click", async () => {
    const confirmed = window.confirm("Delete all past bookings? This permanently removes every booking before now.");
    if (!confirmed) {
      return;
    }

    try {
      setState({ message: "Clearing past bookings..." });
      const result = await api.adminClearPastBookings();
      adminSearchResults = null;
      setActiveAdminSubpage("bookings", "cleanup");
      await actions.refreshAll(`${result.deleted_count} past booking${result.deleted_count === 1 ? "" : "s"} cleared.`);
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminTabs?.forEach((button) => {
    button.addEventListener("click", () => {
      setActiveAdminTab(button.dataset.adminTab);
    });
  });

  document.querySelectorAll("[data-admin-subpage-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = button.dataset.adminSubpageButton;
      const subpage = button.dataset.adminSubpage;
      if (group === "rooms" && subpage === "editor") {
        adminRoomEditorOpen = true;
      }
      setActiveAdminSubpage(group, subpage);
    });
  });

  document.querySelectorAll("[data-admin-subpage-select]").forEach((select) => {
    select.addEventListener("change", () => {
      if (select.dataset.adminSubpageSelect === "rooms" && select.value === "editor") {
        adminRoomEditorOpen = true;
      }
      setActiveAdminSubpage(select.dataset.adminSubpageSelect, select.value);
    });
  });

  elements.adminWorkspaceSelect?.addEventListener("change", () => {
    setActiveAdminTab(elements.adminWorkspaceSelect.value || "overview");
  });

  document.querySelectorAll("[data-admin-focus-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.adminFocusTab || "overview";
      const subpage = button.dataset.adminFocusSubpage || DEFAULT_ADMIN_SUBPAGES[tab] || "overview";
      if (button.dataset.adminCreateRoom === "true") {
        adminRoomEditorOpen = true;
        window.dispatchEvent(new CustomEvent("admin-room-create-request"));
      }
      if (tab === "rooms" && subpage === "editor") {
        adminRoomEditorOpen = true;
      }
      setActiveAdminTab(tab);
      setActiveAdminSubpage(tab, subpage);
    });
  });

  elements.adminAccountsList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-action='select-account']");
    if (!button) {
      return;
    }

    selectedAdminAccountId = button.dataset.userId;
    setActiveAdminSubpage("accounts", "detail");
    renderAdminView(actions.getState());
  });

  elements.adminAccountDetail?.addEventListener("click", async (event) => {
    const roleButton = event.target.closest("[data-admin-action='update-user-role']");
    if (roleButton) {
      const roleSelect = elements.adminAccountDetail.querySelector(
        `[data-admin-role-select][data-user-id="${CSS.escape(roleButton.dataset.userId)}"]`,
      );
      const nextRole = roleSelect?.value;
      if (!nextRole) {
        setState({ message: "Choose a role before updating access." });
        return;
      }
      const accountEmail = roleButton.dataset.userEmail || "this account";
      const confirmed = window.confirm(`Update ${accountEmail} to ${roleSelect.options[roleSelect.selectedIndex].text}?`);
      if (!confirmed) {
        return;
      }
      const adminPassword = window.prompt("Enter your Admin Manager password to change this role.");
      if (!adminPassword) {
        setState({ message: "Role update cancelled." });
        return;
      }
      try {
        setState({ message: "Updating role..." });
        const updatedAccount = await api.adminUpdateUserRole(roleButton.dataset.userId, {
          role: nextRole,
          admin_password: adminPassword,
        });
        const currentState = actions.getState();
        if (String(updatedAccount.id) === String(currentState.currentUser?.id || "")) {
          setState({
            currentUser: {
              ...currentState.currentUser,
              ...updatedAccount,
            },
            message: "Role updated.",
          });
        }
        await actions.refreshAll("Role updated.");
      } catch (error) {
        setState({ message: error.message });
      }
      return;
    }

    const button = event.target.closest("[data-admin-action='delete-user-account']");
    if (!button) {
      return;
    }

    const accountEmail = button.dataset.userEmail || "this account";
    const confirmed = window.confirm(`Delete ${accountEmail}? This removes the profile from the system.`);
    if (!confirmed) {
      return;
    }

    const adminPassword = window.prompt("Enter your admin password to delete this account.");
    if (!adminPassword) {
      setState({ message: "Account deletion cancelled." });
      return;
    }

    try {
      setState({ message: "Deleting account..." });
      await api.adminDeleteUser(button.dataset.userId, { admin_password: adminPassword });
      if (selectedAdminAccountId === button.dataset.userId) {
        selectedAdminAccountId = null;
      }
      await actions.refreshAll("Account deleted.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminRolesList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-action='select-role-account']");
    if (!button) {
      return;
    }

    selectedAdminAccountId = button.dataset.userId;
    setActiveAdminTab("accounts");
    setActiveAdminSubpage("accounts", "detail");
    renderAdminView(actions.getState());
  });

  elements.adminStaffPhotoFile?.addEventListener("change", () => {
    const file = elements.adminStaffPhotoFile.files?.[0];
    if (!file) {
      const name = elements.adminStaffProfileForm?.elements?.name?.value || "Staff member";
      setStaffPhotoPreview(elements.adminStaffPhotoUrl?.value || null, name);
      return;
    }
    setStaffPhotoPreview(URL.createObjectURL(file), elements.adminStaffProfileForm?.elements?.name?.value || file.name);
  });

  elements.adminStaffCancelEdit?.addEventListener("click", () => {
    resetStaffProfileForm();
  });

  elements.adminStaffProfileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = elements.adminStaffProfileForm;
    const file = elements.adminStaffPhotoFile?.files?.[0];

    try {
      setState({ message: editingStaffProfileId ? "Updating staff profile..." : "Creating staff profile..." });
      let photoUrl = elements.adminStaffPhotoUrl?.value || null;
      if (file) {
        const upload = await api.adminUploadStaffPhoto(file);
        photoUrl = upload.photo_url;
      }

      const payload = {
        name: form.elements.name.value.trim(),
        description: form.elements.description.value.trim() || null,
        bio: form.elements.bio.value.trim() || null,
        skills: parseListInput(form.elements.skills.value),
        talents: parseListInput(form.elements.talents.value),
        services: parseListInput(form.elements.services.value),
        photo_url: photoUrl,
        headshot_urls: parseListInput(form.elements.headshot_urls.value),
        portfolio_url: form.elements.portfolio_url.value.trim() || null,
        add_on_price_cents: Number(form.elements.add_on_price_cents.value || 0),
        equipment_rental_cost_cents: Number(form.elements.equipment_rental_cost_cents.value || 0),
        role_title: form.elements.role_title.value.trim() || null,
        notification_email: form.elements.notification_email.value.trim() || null,
        notification_phone: form.elements.notification_phone.value.trim() || null,
        notify_by_email: form.elements.notify_by_email.checked,
        notify_by_sms: form.elements.notify_by_sms.checked,
        booking_requires_approval: form.elements.booking_requires_approval.checked,
        linked_user_email: form.elements.linked_user_email.value.trim() || null,
        active: form.elements.active.checked,
      };

      if (editingStaffProfileId) {
        await api.adminUpdateStaffProfile(editingStaffProfileId, payload);
      } else {
        await api.adminCreateStaffProfile(payload);
      }

      resetStaffProfileForm();
      setActiveAdminSubpage("staff", "editor");
      await actions.refreshAll("Staff profile saved.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminManualBookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.adminManualBookingForm);
    try {
      setState({ message: "Creating manual booking..." });
      await api.adminCreateManualBooking({
        user_email: form.get("user_email"),
        full_name: form.get("full_name") || null,
        room_id: form.get("room_id"),
        start_time: toIsoStringFromLocal(form.get("start_time")),
        duration_minutes: Number(form.get("duration_minutes")),
        promo_code: String(form.get("promo_code") || "").trim() || null,
        note: form.get("note") || null,
        staff_assignments: getSelectedManualStaffIds(),
      });
      elements.adminManualBookingForm.reset();
      if (elements.adminBookingStart) {
        elements.adminBookingStart.value = "";
      }
      adminSearchResults = null;
      renderManualBookingStaffOptions(actions.getState());
      setActiveAdminSubpage("bookings", "queue");
      await actions.refreshAll("Manual booking created.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  getAdminPromoForm()?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const promoCodeId = getAdminPromoIdInput()?.value || "";

    try {
      setState({ message: promoCodeId ? "Updating promo code..." : "Creating promo code..." });
      const payload = buildAdminPromoPayload();
      if (promoCodeId) {
        await api.adminUpdatePromoCode(promoCodeId, payload);
      } else {
        await api.adminCreatePromoCode(payload);
      }
      resetAdminPromoForm();
      setActiveAdminSubpage("bookings", "promos");
      await actions.refreshAll("Promo code saved.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminBookingResults.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action]");
    if (!button) {
      return;
    }

    try {
      if (button.dataset.adminAction === "waive-payment") {
        const confirmed = window.confirm("Skip Stripe and mark this booking free?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Marking booking free..." });
        if (button.dataset.bookingKind === "staff") {
          await api.adminWaiveStaffBookingPayment(button.dataset.bookingId);
        } else {
          await api.adminWaiveBookingPayment(button.dataset.bookingId);
        }
        adminSearchResults = null;
        setActiveAdminSubpage("bookings", "queue");
        await actions.refreshAll("Booking marked paid without Stripe.");
        return;
      }

      if (button.dataset.adminAction === "mark-paid") {
        const confirmed = window.confirm("Mark this booking paid manually?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Marking booking paid manually..." });
        if (button.dataset.bookingKind === "staff") {
          await api.adminMarkStaffBookingPaid(button.dataset.bookingId);
        } else {
          await api.adminMarkBookingPaid(button.dataset.bookingId);
        }
        adminSearchResults = null;
        setActiveAdminSubpage("bookings", "queue");
        await actions.refreshAll("Booking marked paid manually.");
        return;
      }

      if (button.dataset.adminAction === "refund") {
        const amountLabel = formatMoney(Number(button.dataset.amount || 0));
        const confirmed = window.confirm(`Process a ${amountLabel} refund? This changes payment records.`);
        if (!confirmed) {
          return;
        }
        setState({ message: "Processing refund..." });
        await api.adminRefundBooking(button.dataset.bookingId, {
          amount_cents: Number(button.dataset.amount),
          reason: "Admin refund",
        });
        adminSearchResults = null;
        setActiveAdminSubpage("bookings", "queue");
        await actions.refreshAll("Refund processed.");
        return;
      }

      if (button.dataset.adminAction === "check-in") {
        setState({ message: "Marking guest as arrived..." });
        await api.adminCheckInBooking(button.dataset.bookingId);
        adminSearchResults = null;
        setActiveAdminSubpage("bookings", "queue");
        await actions.refreshAll("Guest checked in.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.adminStaffCatalogList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action]");
    if (!button) {
      return;
    }

    const currentState = actions.getState();
    const profile = (currentState.adminStaffProfiles || []).find((item) => String(item.id) === button.dataset.staffProfileId);

    try {
      if (button.dataset.adminAction === "edit-staff-profile") {
        if (!profile) {
          setState({ message: "Staff profile not found." });
          return;
        }
        populateStaffProfileForm(profile);
        setActiveAdminSubpage("staff", "editor");
        setState({ message: `Editing ${profile.name}.` });
        return;
      }

      if (button.dataset.adminAction === "toggle-staff-profile") {
        if (!profile) {
          setState({ message: "Staff profile not found." });
          return;
        }
        const nextActive = button.dataset.nextActive === "true";
        setState({ message: nextActive ? "Activating staff profile..." : "Deactivating staff profile..." });
        await api.adminUpdateStaffProfile(profile.id, { active: nextActive });
        await actions.refreshAll(nextActive ? "Staff profile activated." : "Staff profile deactivated.");
        return;
      }

      if (button.dataset.adminAction === "delete-staff-profile") {
        const profileName = button.dataset.staffProfileName || "this staff profile";
        const confirmed = window.confirm(`Delete ${profileName}? This will also remove the profile from any rooms.`);
        if (!confirmed) {
          return;
        }
        setState({ message: "Deleting staff profile..." });
        await api.adminDeleteStaffProfile(button.dataset.staffProfileId);
        resetStaffProfileForm();
        await actions.refreshAll("Staff profile deleted.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });

  getAdminPromoList()?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action]");
    if (!button) {
      return;
    }

    const currentState = actions.getState();
    const promoCode = (currentState.adminPromoCodes || []).find(
      (item) => String(item.id) === button.dataset.promoCodeId,
    );
    if (!promoCode) {
      setState({ message: "Promo code not found." });
      return;
    }

    try {
      if (button.dataset.adminAction === "edit-promo") {
        populateAdminPromoForm(promoCode);
        setActiveAdminSubpage("bookings", "promos");
        setState({ message: `Editing ${promoCode.code}.` });
        return;
      }

      if (button.dataset.adminAction === "toggle-promo") {
        setState({ message: promoCode.active ? "Deactivating promo code..." : "Activating promo code..." });
        await api.adminUpdatePromoCode(promoCode.id, {
          active: button.dataset.nextActive === "true",
        });
        await actions.refreshAll(promoCode.active ? "Promo code deactivated." : "Promo code activated.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });

  // Intakes (membership interest + engineer applications): client-side filters,
  // refresh through the umbrella reload, and inline status changes.
  ["admin-intakes-type-filter", "admin-intakes-status-filter"].forEach((selectId) => {
    document.getElementById(selectId)?.addEventListener("change", () => {
      renderAdminIntakes(actions.getState());
    });
  });

  document.getElementById("admin-intakes-refresh")?.addEventListener("click", () => {
    actions.refreshAll("Refreshing leads…");
  });

  document.getElementById("admin-intakes-list")?.addEventListener("click", async (event) => {
    const button = event.target.closest('[data-admin-action="set-intake-status"]');
    if (!button) {
      return;
    }
    try {
      button.disabled = true;
      setState({ message: "Updating submission…" });
      await api.adminUpdateIntakeStatus(button.dataset.intakeId, button.dataset.intakeStatus);
      await actions.refreshAll(`Submission marked ${button.dataset.intakeStatus}.`);
    } catch (error) {
      setState({ message: error.message });
    }
  });

  document.getElementById("admin-schedule-date")?.addEventListener("change", () => loadAdminStaffSchedule());
  document.getElementById("admin-schedule-refresh")?.addEventListener("click", () => loadAdminStaffSchedule());
  document.getElementById("admin-tab-schedule")?.addEventListener("click", () => loadAdminStaffSchedule());

  document.getElementById("admin-monthly-codes-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = document.getElementById("admin-monthly-codes-feedback");
    const submitButton = form.querySelector('button[type="submit"]');
    const originalLabel = submitButton ? submitButton.textContent : "";
    const payload = {
      month: form.elements.month.value,
      member_category: form.elements.member_category.value,
      percent_off: Number(form.elements.percent_off.value || 50),
    };
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Generating…";
    }
    if (feedback) feedback.classList.add("hidden");
    try {
      const result = await api.adminGenerateMonthlyMemberCodes(payload);
      if (feedback) {
        feedback.textContent = `Created ${result.created} new code${result.created === 1 ? "" : "s"}, skipped ${result.skipped} existing.`;
        feedback.classList.remove("hidden", "is-error");
        feedback.classList.add("is-success");
      }
      await actions.refreshAll("Monthly member codes generated.");
    } catch (error) {
      if (feedback) {
        feedback.textContent = error?.message ? String(error.message) : "Could not generate codes.";
        feedback.classList.remove("hidden", "is-success");
        feedback.classList.add("is-error");
      }
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalLabel;
      }
    }
  });

  elements.adminRoomStaffList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-admin-action='save-room-staff']");
    if (!button) {
      return;
    }

    const roomCard = button.closest("[data-room-card]");
    if (!roomCard) {
      return;
    }

    try {
      const currentState = actions.getState();
      const roomId = button.dataset.roomId;
      const staffRoles = collectRoomStaffPayload(roomCard, currentState.adminStaffProfiles);
      setState({ message: "Saving room staff..." });
      await api.adminUpdateRoom(roomId, { staff_roles: staffRoles });
      await actions.refreshAll("Room staff updated.");
    } catch (error) {
      setState({ message: error.message });
    }
  });

  getAdminRoomCalendarGridElement()?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-admin-calendar-date]");
    if (!button) {
      return;
    }

    selectedAdminScheduleDate = button.dataset.adminCalendarDate || todayString();
    selectedAdminScheduleRoomId = selectedAdminCalendarRoomId || "all";
    if (elements.adminScheduleDate) {
      elements.adminScheduleDate.value = selectedAdminScheduleDate;
    }
    if (elements.adminScheduleRoomFilter) {
      elements.adminScheduleRoomFilter.value = selectedAdminScheduleRoomId;
    }
    setActiveAdminSubpage("bookings", "schedule");
    renderAdminView(actions.getState());
    setState({ message: `Showing day board for ${selectedAdminScheduleDate}.` });
  });

  window.addEventListener("admin-subpage-request", (event) => {
    const detail = event.detail || {};
    if (!detail.group || !detail.subpage) {
      return;
    }
    if (detail.group === "rooms" && detail.subpage === "editor") {
      adminRoomEditorOpen = true;
    }
    setActiveAdminTab(detail.group);
    setActiveAdminSubpage(detail.group, detail.subpage);
  });
}

export function renderAdminView(currentState) {
  if (
    !elements.adminEmpty ||
    !elements.adminBookingLookupForm ||
    !elements.adminBookingResults ||
    !elements.adminManualBookingForm ||
    !elements.adminRoomSelect
  ) {
    return;
  }

  const isAdmin = Boolean(currentState.currentUser?.is_admin);
  elements.adminEmpty.classList.toggle("hidden", isAdmin);
  elements.adminWorkspaceShell?.classList.toggle("hidden", !isAdmin);
  elements.adminAnalyticsPanel?.classList.toggle("hidden", !isAdmin);
  elements.adminActivityPanel?.classList.toggle("hidden", !isAdmin);
  elements.adminBookingLookupForm.classList.toggle("hidden", !isAdmin);
  elements.adminManualBookingForm.classList.toggle("hidden", !isAdmin);
  elements.adminStaffProfileForm?.classList.toggle("hidden", !isAdmin);
  elements.adminBookingResults.classList.toggle("hidden", !isAdmin);
  elements.adminRoomManagementPanel?.classList.toggle("hidden", !isAdmin);

  const activeRooms = getActiveRooms(currentState.rooms);
  const roomOptions = activeRooms.map(
    (room) => `<option value="${escapeAttribute(room.id)}">${escapeHtml(room.name)}</option>`,
  );
  const previousRoomId = elements.adminRoomSelect.value;
  const previousScheduleRoomId = elements.adminScheduleRoomFilter?.value || selectedAdminScheduleRoomId;
  const calendarRoomFilter = getAdminCalendarRoomFilter();
  const previousCalendarRoomId = calendarRoomFilter?.value || selectedAdminCalendarRoomId;
  const calendarMonthInput = getAdminCalendarMonthInput();
  elements.adminRoomSelect.innerHTML = roomOptions.length
    ? roomOptions.join("")
    : '<option value="">No active rooms</option>';
  if (roomOptions.length) {
    elements.adminRoomSelect.value =
      activeRooms.some((room) => String(room.id) === previousRoomId)
        ? previousRoomId
        : activeRooms[0].id;
  }
  renderManualDurationOptions(currentState);
  if (elements.adminScheduleRoomFilter) {
    const scheduleRoomOptions = ['<option value="all">All rooms</option>'].concat(
      (currentState.rooms || []).map((room) => `<option value="${escapeAttribute(room.id)}">${escapeHtml(room.name)}</option>`),
    );
    elements.adminScheduleRoomFilter.innerHTML = scheduleRoomOptions.join("");
    selectedAdminScheduleRoomId = (currentState.rooms || []).some((room) => String(room.id) === previousScheduleRoomId)
      ? previousScheduleRoomId
      : "all";
    elements.adminScheduleRoomFilter.value = selectedAdminScheduleRoomId;
  }
  if (elements.adminScheduleDate && elements.adminScheduleDate.value !== selectedAdminScheduleDate) {
    elements.adminScheduleDate.value = selectedAdminScheduleDate;
  }
  if (calendarRoomFilter) {
    const calendarRoomOptions = ['<option value="all">All rooms</option>'].concat(
      (currentState.rooms || []).map((room) => `<option value="${escapeAttribute(room.id)}">${escapeHtml(room.name)}</option>`),
    );
    calendarRoomFilter.innerHTML = calendarRoomOptions.join("");
    selectedAdminCalendarRoomId = (currentState.rooms || []).some((room) => String(room.id) === previousCalendarRoomId)
      ? previousCalendarRoomId
      : "all";
    calendarRoomFilter.value = selectedAdminCalendarRoomId;
  }
  if (calendarMonthInput && calendarMonthInput.value !== selectedAdminCalendarMonth) {
    calendarMonthInput.value = safeMonthValue(selectedAdminCalendarMonth);
  }

  if (!isAdmin) {
    setActiveAdminTab("rooms");
    Object.assign(activeAdminSubpages, DEFAULT_ADMIN_SUBPAGES);
    adminSearchResults = null;
    elements.adminDashboardMetrics && (elements.adminDashboardMetrics.innerHTML = "");
    elements.adminAnalyticsGrid && (elements.adminAnalyticsGrid.innerHTML = "");
    elements.adminRoomBreakdown && (elements.adminRoomBreakdown.innerHTML = "");
    elements.adminStaffBreakdown && (elements.adminStaffBreakdown.innerHTML = "");
    elements.adminActivityList && (elements.adminActivityList.innerHTML = "");
    elements.adminRoomStaffList && (elements.adminRoomStaffList.innerHTML = "");
    elements.adminStaffCatalogList && (elements.adminStaffCatalogList.innerHTML = "");
    elements.adminAccountsList && (elements.adminAccountsList.innerHTML = "");
    elements.adminAccountDetail && (elements.adminAccountDetail.innerHTML = "");
    elements.adminRolesList && (elements.adminRolesList.innerHTML = "");
    if (elements.adminRolesCount) {
      elements.adminRolesCount.textContent = "0 admins";
    }
    elements.adminTestCaseSummary && (elements.adminTestCaseSummary.innerHTML = "");
    elements.adminTestCasesList && (elements.adminTestCasesList.innerHTML = "");
    elements.adminManualStaffOptions && (elements.adminManualStaffOptions.innerHTML = "");
    elements.adminDaySummary && (elements.adminDaySummary.innerHTML = "");
    elements.adminDaySchedule && (elements.adminDaySchedule.innerHTML = "");
    getAdminPromoList() && (getAdminPromoList().innerHTML = "");
    getAdminRoomCalendarSummaryElement() && (getAdminRoomCalendarSummaryElement().innerHTML = "");
    getAdminRoomCalendarGridElement() && (getAdminRoomCalendarGridElement().innerHTML = "");
    elements.adminBookingResults.innerHTML = "";
    elements.adminBookingQuickSummary && (elements.adminBookingQuickSummary.innerHTML = "");
    elements.adminBookingQuickFilters && (elements.adminBookingQuickFilters.innerHTML = "");
    if (elements.adminBookingResultsCopy) {
      elements.adminBookingResultsCopy.textContent =
        "See who booked, who cancelled, room details, staff add-ons, and booking notes in one organized list.";
    }
    selectedAdminAccountId = null;
    return;
  }

  setActiveAdminTab(activeAdminTab);
  Object.entries(activeAdminSubpages).forEach(([group, subpage]) => {
    setActiveAdminSubpage(group, subpage);
  });
  renderAdminDashboardMetrics(currentState);
  renderAdminRoles(currentState);
  renderAdminDaySummary(currentState);
  renderAdminDaySchedule(currentState);
  renderAdminRoomCalendarSummary(currentState);
  renderAdminRoomCalendar(currentState);
  renderAdminPromoCodes(currentState);
  renderAdminIntakes(currentState);
  syncAdminPromoDiscountFields();

  if (elements.adminAnalyticsGrid) {
    const analytics = currentState.adminAnalytics;
    const triage = getAdminTriageMetrics(currentState);
    const cards = analytics
      ? [
          { label: "Needs attention", value: triage.needsAttention },
          { label: "Pending payment", value: triage.pendingPayment },
          { label: "Ready for arrival", value: triage.readyForArrival },
          { label: "Today", value: triage.todayCount },
          { label: "Active rooms", value: analytics.active_rooms },
          { label: "Staff add-ons booked", value: analytics.staff_assignment_count },
          {
            label: "Net revenue",
            value: formatMoney(analytics.net_revenue_cents, analytics.currency),
          },
        ]
      : [];

    elements.adminAnalyticsGrid.innerHTML = cards.length
      ? cards
          .map(
            (card) => `
              <article class="metric-card">
                <span class="metric-label">${escapeHtml(card.label)}</span>
                <strong class="metric-value">${escapeHtml(card.value)}</strong>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">Analytics will appear once booking data is available.</div>';
  }

  renderAdminTodayCounters(currentState);
  renderAdminTodayRoster(currentState);
  renderAdminUpcomingRoster(currentState);
  syncAdminTodayPollingForActiveTab();

  if (elements.adminRoomBreakdown) {
    const roomSummaries = currentState.adminAnalytics?.room_summaries || [];
    elements.adminRoomBreakdown.innerHTML = roomSummaries.length
      ? roomSummaries
          .map(
            (room) => `
              <article class="admin-room-card">
                <header>
                  <h4>${escapeHtml(room.room_name)}</h4>
                  <strong>${formatMoney(room.revenue_cents, currentState.adminAnalytics.currency)}</strong>
                </header>
                <p>${escapeHtml(room.total_bookings)} booking${room.total_bookings === 1 ? "" : "s"} recorded</p>
                <div class="room-meta">
                  <span class="pill">${escapeHtml(room.paid_bookings)} paid or refunded</span>
                  <span class="pill">${escapeHtml(room.total_bookings - room.paid_bookings)} unpaid or cancelled</span>
                </div>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No room activity yet.</div>';
  }

  if (elements.adminStaffBreakdown) {
    const staffSummaries = currentState.adminAnalytics?.staff_summaries || [];
    elements.adminStaffBreakdown.innerHTML = staffSummaries.length
      ? staffSummaries
          .map(
            (staff) => `
              <article class="admin-room-card">
                <header>
                  <h4>${escapeHtml(staff.staff_name)}</h4>
                  <strong>${formatMoney(staff.revenue_cents, currentState.adminAnalytics.currency)}</strong>
                </header>
                <p>${escapeHtml(staff.total_bookings)} booking${staff.total_bookings === 1 ? "" : "s"} with this staff profile</p>
                <div class="room-meta">
                  <span class="pill">${escapeHtml(staff.assigned_rooms)} assigned room${staff.assigned_rooms === 1 ? "" : "s"}</span>
                  <span class="pill ${staff.active ? "" : "muted"}">${staff.active ? "Active" : "Inactive"}</span>
                </div>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No staff utilization data yet.</div>';
  }

  if (elements.adminActivityList) {
    const activity = currentState.adminActivity || [];
    elements.adminActivityList.innerHTML = activity.length
      ? activity
          .map(
            (item) => `
              <article class="admin-activity-card">
                <header>
                  <strong>${escapeHtml(formatActivityAction(item.action))}</strong>
                  <span>${formatBookingDate(item.created_at)}</span>
                </header>
                <p>${escapeHtml(item.actor_email || "System")}${item.booking_id ? ` • Booking ${escapeHtml(item.booking_id)}` : ""}</p>
                <p>${escapeHtml(item.details ? JSON.stringify(item.details) : "No extra details recorded.")}</p>
              </article>
            `,
          )
          .join("")
      : '<div class="empty-state">No activity recorded yet.</div>';
  }

  if (elements.adminAccountsList && elements.adminAccountDetail) {
    const accounts = currentState.adminUsers || [];
    if (!accounts.length) {
      selectedAdminAccountId = null;
      elements.adminAccountsList.innerHTML = '<div class="empty-state">No accounts are available yet.</div>';
      elements.adminAccountDetail.innerHTML = '<div class="empty-state">Select an account once profiles exist.</div>';
    } else {
      if (!accounts.some((account) => String(account.id) === String(selectedAdminAccountId))) {
        selectedAdminAccountId = accounts[0].id;
      }
      const selectedAccount =
        accounts.find((account) => String(account.id) === String(selectedAdminAccountId)) || accounts[0];
      elements.adminAccountsList.innerHTML = accounts
        .map((account) => renderAdminAccountListItem(account, String(account.id) === String(selectedAccount.id)))
        .join("");
      elements.adminAccountDetail.innerHTML = renderAdminAccountDetail(selectedAccount, currentState.currentUser);
    }
  }

  if (elements.adminTestCasesList) {
    const testCases = [...(currentState.adminTestCases || [])].sort((left, right) => {
      const leftMeta = getTestCaseHealthMeta(left.health);
      const rightMeta = getTestCaseHealthMeta(right.health);
      if (leftMeta.sortOrder !== rightMeta.sortOrder) {
        return leftMeta.sortOrder - rightMeta.sortOrder;
      }
      return left.title.localeCompare(right.title);
    });
    renderAdminTestCaseSummary(testCases);
    elements.adminTestCasesList.innerHTML = testCases.length
      ? testCases.map(renderAdminTestCaseCard).join("")
      : '<div class="empty-state">No backend test cases are registered yet.</div>';
  }

  const { baseBookings, filteredBookings, filterOptions, searchActive } = getAdminBookingCollections(currentState);
  renderAdminBookingQuickSummary(baseBookings, filterOptions);
  renderAdminBookingQuickFilters(filterOptions);
  renderAdminBookingResultsCopy(baseBookings, filteredBookings, filterOptions, searchActive);

  const groupedBookings = ADMIN_BOOKING_GROUPS
    .map((group) => ({
      ...group,
      bookings: filteredBookings.filter((booking) => booking.status === group.key),
    }))
    .filter((group) => group.bookings.length);

  elements.adminBookingResults.innerHTML = filteredBookings.length
    ? groupedBookings.map((group) => renderAdminBookingGroup(group, group.bookings)).join("")
    : `
        <div class="empty-state">
          ${searchActive ? "No bookings matched your search and quick filter." : "No bookings match the current quick filter yet."}
        </div>
      `;

  if (elements.adminStaffCatalogList) {
    const profiles = currentState.adminStaffProfiles || [];
    elements.adminStaffCatalogList.innerHTML = profiles.length
      ? profiles.map(renderStaffCatalogCard).join("")
      : '<div class="empty-state">Create your first staff profile to start assigning people to rooms.</div>';
  }

  if (elements.adminRoomStaffList) {
    const rooms = currentState.rooms || [];
    elements.adminRoomStaffList.innerHTML = rooms.length
      ? rooms.map((room) => renderRoomStaffAssignmentCard(room, currentState.adminStaffProfiles)).join("")
      : '<div class="empty-state">No rooms available for staff assignment.</div>';
  }

  renderManualBookingStaffOptions(currentState);
}
