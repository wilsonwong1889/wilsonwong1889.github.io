import { api } from "../api.js";
import { elements, toggleHidden } from "../dom.js";
import { persistCheckoutDraft, persistLastBookingId, persistToken, setState, state } from "../state.js";
const ROOM_CATEGORY_VISUALS = {
  recording: "/assets/media/studio-room-2.png",
  podcast: "/assets/media/studio-lobby-2.png",
  production: "/assets/media/studio-room-2.png",
  photography: "/assets/media/studio-room-2.png",
  dance: "/assets/media/studio-exterior-2.png",
  film: "/assets/media/studio-exterior-2.png",
};

const MIN_DURATION_MINUTES = 60;
const MAX_DURATION_MINUTES = 300;

const MEMBER_CATEGORY_LABELS = {
  artist_member: "Artist Member",
  fellowship_artist: "Fellowship Artist",
  artist_in_residence: "Artist in Residence",
  service_engineer: "Service Engineer",
  bipoc_community_member: "BIPOC Community Member",
  venture_member: "Venture Member",
  organizational_member: "Organizational Member",
};

function getRoomHourlyRate(room) {
  return room?.hourly_rate_cents ?? 0;
}

function getMemberCategoryLabel(category) {
  return MEMBER_CATEGORY_LABELS[category] || null;
}

let selectedDate = null;
let displayedMonth = null;
let dayAvailability = null;
let selectedStart = "";
let lastRoomId = null;
let monthAvailability = {};
let loadingDay = false;
let loadingMonth = false;
let dayAvailabilityRequestToken = 0;
let monthAvailabilityRequestToken = 0;
let selectedStaffIds = new Set();
let reservePromoPreview = null;
let reservePromoMessage = "";

function getReserveGuestFields() {
  return document.getElementById("reserve-guest-fields");
}

function getReserveGuestNameInput() {
  return document.getElementById("reserve-guest-name");
}

function getReserveGuestPhoneInput() {
  return document.getElementById("reserve-guest-phone");
}

function getReservePolicyCheckbox() {
  return document.getElementById("reserve-policy-checkbox");
}

function buildSessionNote() {
  const purpose = document.getElementById("reserve-session-purpose")?.value?.trim();
  const attendees = document.getElementById("reserve-attendees")?.value?.trim();
  const equipment = document.getElementById("reserve-equipment-needs")?.value?.trim();
  const baseNote = elements.reserveNoteInput?.value?.trim();
  const parts = [];
  if (purpose) parts.push(`Purpose: ${purpose}`);
  if (attendees) parts.push(`Attendees: ${attendees}`);
  if (equipment) parts.push(`Equipment: ${equipment}`);
  if (baseNote) parts.push(baseNote);
  return parts.join("\n") || null;
}


function getReserveStepList() {
  return document.getElementById("reserve-step-list");
}

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function todayString() {
  return localDateString();
}

function isDateBeforeToday(value) {
  return Boolean(value && value < todayString());
}

function clampBookingDate(value) {
  return isDateBeforeToday(value) ? todayString() : value || todayString();
}

function firstOfMonth(value) {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(1);
  return date.toISOString().slice(0, 10);
}

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format((cents || 0) / 100);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDateLabel(value) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
  }).format(new Date(`${value}T00:00:00`));
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatTime(value) {
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function buildAmenityList(room) {
  const amenities = [];
  if ((room.capacity || 0) >= 4) {
    amenities.push("High-Speed WiFi");
  }
  if ((room.staff_roles || []).length) {
    amenities.push("Pro Monitors");
  }
  if ((room.photos || []).length > 1) {
    amenities.push("Premium Mics");
  }
  amenities.push("Central Location");
  return amenities.slice(0, 4);
}

function getRoomCategory(room) {
  const text = `${room.name || ""} ${room.description || ""}`.toLowerCase();
  if (text.includes("podcast")) {
    return "podcast";
  }
  if (text.includes("production")) {
    return "production";
  }
  if (text.includes("photo")) {
    return "photography";
  }
  if (text.includes("dance")) {
    return "dance";
  }
  if (text.includes("film") || text.includes("video")) {
    return "film";
  }
  return "recording";
}

function getReserveGallery(room) {
  const rawPhotos = Array.isArray(room.photos) ? room.photos : [];
  const usablePhotos = rawPhotos.filter((photo) => photo && !String(photo).includes("/assets/media/rooms/"));
  if (usablePhotos.length) {
    return usablePhotos;
  }

  const category = getRoomCategory(room);
  const fallback = ROOM_CATEGORY_VISUALS[category] || "/assets/media/studio-room-2.png";
  if (category === "podcast") {
    return [
      "/assets/media/studio-lobby-2.png",
      "/assets/media/studio-exterior-2.png",
      "/assets/media/studio-room-2.png",
    ];
  }
  return [
    fallback,
    "/assets/media/studio-lobby-2.png",
    "/assets/media/studio-exterior-2.png",
  ];
}

function buildDurationValues(limitMinutes = MAX_DURATION_MINUTES) {
  const safeLimit = Math.max(MIN_DURATION_MINUTES, Math.min(limitMinutes, MAX_DURATION_MINUTES));
  const values = [];
  for (let duration = MIN_DURATION_MINUTES; duration <= safeLimit; duration += MIN_DURATION_MINUTES) {
    values.push(duration);
  }
  return values;
}

function getReservePromoCodeInput() {
  return document.getElementById("reserve-promo-code-input");
}

function getReservePromoFeedback() {
  return document.getElementById("reserve-promo-feedback");
}

function getReservePromoInputValue() {
  return getReservePromoCodeInput()?.value?.trim()?.toUpperCase() || "";
}

function getReservePromoSelectionKey(roomId, durationMinutes, amountCents) {
  return JSON.stringify({
    roomId: String(roomId || ""),
    durationMinutes: Number(durationMinutes || 0),
    amountCents: Number(amountCents || 0),
    staffIds: [...selectedStaffIds].sort(),
  });
}

function getReservePromoContext(room) {
  if (!room) {
    return null;
  }

  const amountCents = calculateEstimatedTotal(room);
  return {
    amountCents,
    selectionKey: getReservePromoSelectionKey(room.id, getSelectedDurationMinutes(), amountCents),
  };
}

function clearReservePromoState(message = "") {
  reservePromoPreview = null;
  reservePromoMessage = message;
}

function invalidateReservePromoIfNeeded(room) {
  if (!reservePromoPreview || !room) {
    return;
  }

  const context = getReservePromoContext(room);
  if (!context || reservePromoPreview.selectionKey !== context.selectionKey) {
    clearReservePromoState("Selection changed. Apply promo again to refresh the total.");
  }
}

function renderReservePromoFeedback() {
  const feedback = getReservePromoFeedback();
  if (!feedback) {
    return;
  }

  if (reservePromoPreview) {
    feedback.classList.remove("hidden");
    feedback.className = "empty-state booking-promo-feedback booking-promo-feedback-success";
    feedback.innerHTML = `
      <strong>${escapeHtml(reservePromoPreview.code)} applied</strong>
      <span>Discount ${formatCurrency(reservePromoPreview.discount_cents)}. New estimated total ${formatCurrency(reservePromoPreview.final_amount_cents)}.</span>
    `;
    return;
  }

  if (reservePromoMessage) {
    feedback.classList.remove("hidden");
    feedback.className = "empty-state booking-promo-feedback booking-promo-feedback-error";
    feedback.innerHTML = `<strong>Promo update</strong><span>${escapeHtml(reservePromoMessage)}</span>`;
    return;
  }

  feedback.className = "empty-state booking-promo-feedback hidden";
  feedback.innerHTML = "";
}

async function applyReservePromoPreview(currentState) {
  const room = currentState.selectedRoom;
  const code = getReservePromoInputValue();
  const context = getReservePromoContext(room);

  if (!room || !context) {
    clearReservePromoState("Choose a room and duration before applying a promo code.");
    renderReservePromoFeedback();
    renderSummary(currentState);
    return;
  }

  if (!code) {
    clearReservePromoState("Enter a promo code first.");
    renderReservePromoFeedback();
    renderSummary(currentState);
    return;
  }

  try {
    setState({ message: "Checking promo code..." });
    const preview = await api.previewPromoCode(code, context.amountCents);
    reservePromoPreview = {
      ...preview,
      selectionKey: context.selectionKey,
    };
    reservePromoMessage = "";
    setState({ message: `${preview.code} applied.` });
  } catch (error) {
    clearReservePromoState(error.message);
    setState({ message: error.message });
  }

  renderReservePromoFeedback();
  renderSummary(currentState);
}

function getSelectedDurationMinutes() {
  const value = Number(elements.reserveDurationSelect?.value);
  return Number.isFinite(value) && value >= MIN_DURATION_MINUTES ? value : MIN_DURATION_MINUTES;
}

function hasCurrentDayAvailability() {
  return Boolean(
    !loadingDay &&
      dayAvailability &&
      selectedDate &&
      String(dayAvailability.date || "") === String(selectedDate),
  );
}

function getCurrentDayStarts() {
  return hasCurrentDayAvailability() && Array.isArray(dayAvailability.available_start_times)
    ? dayAvailability.available_start_times
    : [];
}

function getStartMaxDuration(startTime) {
  if (!startTime || !hasCurrentDayAvailability()) {
    return 0;
  }

  const maxDuration = Number(dayAvailability?.max_duration_minutes_by_start?.[startTime]);
  if (!Number.isFinite(maxDuration) || maxDuration < MIN_DURATION_MINUTES) {
    return 0;
  }
  return Math.min(maxDuration, MAX_DURATION_MINUTES);
}

function getAllowedDurationsForStart(startTime) {
  const maxDuration = getStartMaxDuration(startTime);
  return maxDuration >= MIN_DURATION_MINUTES ? buildDurationValues(maxDuration) : [];
}

function syncReserveDurationToSelectedStart(room = state.selectedRoom) {
  if (!elements.reserveDurationSelect) {
    return false;
  }

  const previousValue = getSelectedDurationMinutes();
  const allowedDurations = getAllowedDurationsForStart(selectedStart);
  elements.reserveDurationSelect.disabled = !allowedDurations.length;
  elements.reserveDurationSelect.innerHTML = allowedDurations
    .map((duration) => `<option value="${escapeHtml(duration)}">${formatDuration(duration)}</option>`)
    .join("");

  if (!allowedDurations.length) {
    elements.reserveDurationSelect.value = "";
    return false;
  }

  const nextValue = allowedDurations.includes(previousValue)
    ? previousValue
    : allowedDurations.filter((duration) => duration <= previousValue).pop() || allowedDurations[0];
  elements.reserveDurationSelect.value = String(nextValue);

  const changed = nextValue !== previousValue;
  if (changed) {
    invalidateReservePromoIfNeeded(room);
  }
  return changed;
}

function getCurrentSelectionValidity() {
  const starts = getCurrentDayStarts();
  const maxDuration = getStartMaxDuration(selectedStart);
  const duration = getSelectedDurationMinutes();
  const valid = Boolean(
    starts.includes(selectedStart) &&
      maxDuration >= MIN_DURATION_MINUTES &&
      duration >= MIN_DURATION_MINUTES &&
      duration <= maxDuration &&
      duration % MIN_DURATION_MINUTES === 0,
  );

  return {
    valid,
    duration,
    maxDuration,
  };
}

function renderStaffImage(photoUrl, label) {
  const safeLabel = escapeHtml(label);
  if (photoUrl) {
    return `<img class="staff-avatar" src="${escapeHtml(photoUrl)}" alt="${safeLabel}" loading="lazy" />`;
  }
  return `<div class="staff-avatar staff-avatar-fallback">${escapeHtml(label.slice(0, 1).toUpperCase())}</div>`;
}

function renderRoomVisuals(room) {
  if (elements.reserveRoomMeta) {
    elements.reserveRoomMeta.innerHTML = `
      <span class="pill reserve-room-pill">${escapeHtml(room.name.split(" ")[0])}</span>
      <span class="pill reserve-room-pill ${room.active ? "" : "muted"}">${room.active ? ({ available: "Available", in_progress: "In Progress", tbc: "TBC" }[room.status] || "Available") : "Inactive"}</span>
      <span class="pill reserve-room-pill">Up to ${escapeHtml(room.capacity || "n/a")} people</span>
      <span class="pill reserve-room-pill">★ 4.9 rating</span>
      <span class="pill reserve-room-pill">Min 1 hour</span>
    `;
  }

  if (elements.reserveRoomAmenities) {
    elements.reserveRoomAmenities.innerHTML = buildAmenityList(room)
      .map((item) => `<span class="room-detail-amenity">${escapeHtml(item)}</span>`)
      .join("");
  }
}

function renderTagGroup(label, values = []) {
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

function daysInMonth(monthValue) {
  const base = new Date(`${monthValue}T00:00:00`);
  const year = base.getFullYear();
  const month = base.getMonth();
  return new Date(year, month + 1, 0).getDate();
}

function getSelectedStaffOptions(room) {
  const roles = room?.staff_roles || [];
  return roles.filter((role) => selectedStaffIds.has(role.id));
}

function calculateEstimatedTotal(room) {
  const hourlyRate = getRoomHourlyRate(room);
  const baseRate = hourlyRate * (getSelectedDurationMinutes() / 60);
  const staffTotal = getSelectedStaffOptions(room).reduce(
    (total, role) => total + (role.add_on_price_cents || 0),
    0,
  );
  return baseRate + staffTotal;
}

function getDepositCents(room) {
  const hasEngineer = getSelectedStaffOptions(room).some((role) =>
    /engineer/i.test(role.name || ""),
  );
  return hasEngineer ? 2000 : 1000;
}

function renderSelectedStaffBreakdown(room) {
  const selectedStaff = getSelectedStaffOptions(room);
  if (!selectedStaff.length) {
    return '<div class="summary-line"><span>Staff add-ons</span><strong>None selected</strong></div>';
  }

  return selectedStaff
    .map(
      (role) => `
        <div class="summary-line">
          <span>${escapeHtml(role.name)}</span>
          <strong>${formatCurrency(role.add_on_price_cents)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderReserveStepStatus(currentState) {
  const stepList = getReserveStepList();
  if (!stepList) {
    return;
  }

  const guestName = getReserveGuestNameInput()?.value?.trim() || "";
  const guestPhone = getReserveGuestPhoneInput()?.value?.trim() || "";
  const hasContact = Boolean(currentState.currentUser || (guestName && guestPhone));
  const completeSteps = new Set();
  if (selectedDate) {
    completeSteps.add("date");
  }
  if (selectedStart) {
    completeSteps.add("time");
  }
  if (hasContact) {
    completeSteps.add("details");
  }

  const activeStep = !selectedDate
    ? "date"
    : !selectedStart
      ? "time"
      : !hasContact
        ? "details"
        : "checkout";

  stepList.querySelectorAll("[data-reserve-step]").forEach((step) => {
    const key = step.dataset.reserveStep;
    step.classList.toggle("is-complete", completeSteps.has(key));
    step.classList.toggle("is-active", key === activeStep);
  });
}

async function loadDayAvailability(roomId, date) {
  if (!roomId || !date) {
    return;
  }

  const safeDate = clampBookingDate(date);
  if (safeDate !== date) {
    selectedDate = safeDate;
    date = safeDate;
  }

  const requestToken = dayAvailabilityRequestToken + 1;
  dayAvailabilityRequestToken = requestToken;
  loadingDay = true;
  dayAvailability = null;
  selectedStart = "";
  renderRoomBookingView(state);
  try {
    const availability = await api.getAvailability(roomId, date);
    if (requestToken !== dayAvailabilityRequestToken || String(lastRoomId) !== String(roomId) || selectedDate !== date) {
      return;
    }

    dayAvailability = availability;
    const starts = availability.available_start_times || [];
    selectedStart = starts[0] || "";
    syncReserveDurationToSelectedStart(state.selectedRoom);
    clearReservePromoState("");
    setState({ message: "Day availability loaded." });
  } catch (error) {
    if (requestToken !== dayAvailabilityRequestToken) {
      return;
    }

    dayAvailability = null;
    selectedStart = "";
    setState({ message: error.message });
  } finally {
    if (requestToken === dayAvailabilityRequestToken) {
      loadingDay = false;
      renderRoomBookingView(state);
    }
  }
}

async function loadMonthAvailability(roomId, monthValue) {
  if (!roomId || !monthValue) {
    return;
  }

  const requestToken = monthAvailabilityRequestToken + 1;
  monthAvailabilityRequestToken = requestToken;
  loadingMonth = true;
  renderRoomBookingView(state);
  try {
    const totalDays = daysInMonth(monthValue);
    const entries = await Promise.all(
      Array.from({ length: totalDays }, async (_value, index) => {
        const date = new Date(`${monthValue}T00:00:00`);
        date.setDate(index + 1);
        const isoDate = date.toISOString().slice(0, 10);
        if (isDateBeforeToday(isoDate)) {
          return [isoDate, 0];
        }
        const availability = await api.getAvailability(roomId, isoDate);
        return [isoDate, availability.available_start_times.length];
      }),
    );
    if (requestToken !== monthAvailabilityRequestToken || String(lastRoomId) !== String(roomId) || displayedMonth !== monthValue) {
      return;
    }

    monthAvailability = Object.fromEntries(entries);
    setState({ message: "Month calendar loaded." });
  } catch (error) {
    if (requestToken !== monthAvailabilityRequestToken) {
      return;
    }

    monthAvailability = {};
    setState({ message: error.message });
  } finally {
    if (requestToken === monthAvailabilityRequestToken) {
      loadingMonth = false;
      renderRoomBookingView(state);
    }
  }
}

function renderDaySummary(currentState) {
  if (!elements.reserveAvailabilitySummary) {
    return;
  }

  if (!currentState.selectedRoom || !selectedDate) {
    elements.reserveAvailabilitySummary.innerHTML = `
      <strong>Select a room and date</strong>
      <span>Load a day to see its available start times.</span>
    `;
    return;
  }

  if (loadingDay) {
    elements.reserveAvailabilitySummary.innerHTML = `
      <strong>Loading times...</strong>
      <span>Checking ${escapeHtml(formatDateLabel(selectedDate))} for ${escapeHtml(currentState.selectedRoom.name)}.</span>
    `;
    return;
  }

  if (!dayAvailability) {
    elements.reserveAvailabilitySummary.innerHTML = `
      <strong>Availability unavailable</strong>
      <span>Try another day.</span>
    `;
    return;
  }

  const count = dayAvailability.available_start_times.length;
  elements.reserveAvailabilitySummary.innerHTML = count
    ? `
      <strong>${count} start times available</strong>
      <span>${escapeHtml(currentState.selectedRoom.name)} on ${escapeHtml(dayAvailability.date)} in ${escapeHtml(dayAvailability.timezone)}.</span>
    `
    : `
      <strong>No openings found</strong>
      <span>${escapeHtml(currentState.selectedRoom.name)} is fully booked on ${escapeHtml(dayAvailability.date)}.</span>
    `;
}

function renderSlotList() {
  if (!elements.reserveSlotList || !elements.reserveStartSelect || !elements.reserveDurationSelect) {
    return;
  }

  if (loadingDay) {
    selectedStart = "";
    elements.reserveStartSelect.innerHTML = "";
    syncReserveDurationToSelectedStart(state.selectedRoom);
    toggleHidden(elements.reserveSlotList, false);
    elements.reserveSlotList.innerHTML = `
      <div class="empty-state reserve-slot-empty">
        Loading openings for ${escapeHtml(selectedDate ? formatDateLabel(selectedDate) : "the selected day")}...
      </div>
    `;
    return;
  }

  if (!hasCurrentDayAvailability()) {
    selectedStart = "";
    elements.reserveStartSelect.innerHTML = "";
    syncReserveDurationToSelectedStart(state.selectedRoom);
    toggleHidden(elements.reserveSlotList, false);
    elements.reserveSlotList.innerHTML = `
      <div class="empty-state reserve-slot-empty">
        Pick a date to load current openings.
      </div>
    `;
    return;
  }

  const starts = getCurrentDayStarts();
  elements.reserveStartSelect.innerHTML = starts
    .map((startTime) => `<option value="${escapeHtml(startTime)}">${escapeHtml(formatDateTime(startTime))}</option>`)
    .join("");

  if (starts.includes(selectedStart)) {
    elements.reserveStartSelect.value = selectedStart;
  } else {
    elements.reserveStartSelect.value = starts[0] || "";
    selectedStart = elements.reserveStartSelect.value;
  }

  syncReserveDurationToSelectedStart(state.selectedRoom);

  if (!starts.length) {
    selectedStart = "";
    syncReserveDurationToSelectedStart(state.selectedRoom);
    toggleHidden(elements.reserveSlotList, false);
    elements.reserveSlotList.innerHTML = `
      <div class="empty-state reserve-slot-empty">
        No start times are open for this day. Pick another date from the calendar.
      </div>
    `;
    return;
  }

  toggleHidden(elements.reserveSlotList, false);
  elements.reserveSlotList.innerHTML = starts
    .map((startTime) => {
      const maxDuration = getStartMaxDuration(startTime);
      return `
        <button
          class="slot-card ${startTime === selectedStart ? "is-selected" : ""}"
          type="button"
          data-reserve-slot="${escapeHtml(startTime)}"
          aria-pressed="${startTime === selectedStart ? "true" : "false"}"
        >
          <strong>${escapeHtml(formatTime(startTime))}</strong>
          <span>${maxDuration ? `Up to ${formatDuration(maxDuration)}` : "Unavailable"}</span>
        </button>
      `;
    })
    .join("");
}

function renderStaffOptions(currentState) {
  if (!elements.reserveStaffSection || !elements.reserveStaffOptions) {
    return;
  }

  const room = currentState.selectedRoom;
  const staffRoles = room?.staff_roles || [];
  if (!staffRoles.length) {
    selectedStaffIds = new Set();
    toggleHidden(elements.reserveStaffSection, true);
    elements.reserveStaffOptions.innerHTML = "";
    return;
  }

  const availableIds = new Set(staffRoles.map((role) => role.id));
  selectedStaffIds = new Set([...selectedStaffIds].filter((roleId) => availableIds.has(roleId)));

  toggleHidden(elements.reserveStaffSection, false);
  elements.reserveStaffOptions.innerHTML = staffRoles
    .map(
      (role) => `
        <label class="staff-option-card">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${escapeHtml(role.id)}" ${selectedStaffIds.has(role.id) ? "checked" : ""} />
          </div>
          ${renderStaffImage(role.photo_url, role.name)}
          <div class="staff-option-copy">
            <strong>${escapeHtml(role.name)}</strong>
            <span>${escapeHtml(role.description || "Optional staff support for this session.")}</span>
            ${renderTagGroup("Skills", role.skills || [])}
            ${renderTagGroup("Talents", role.talents || [])}
          </div>
          <strong class="staff-option-price">${formatCurrency(role.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function renderSummary(currentState) {
  if (!elements.reserveSummaryMeta) {
    return;
  }

  const room = currentState.selectedRoom;
  if (!room) {
    elements.reserveSummaryMeta.innerHTML = '<div class="empty-state">Choose a room from the catalog first.</div>';
    return;
  }

  const currentUser = currentState.currentUser;
  const estimatedTotal = calculateEstimatedTotal(room);
  const promoSelectionKey = getReservePromoSelectionKey(room.id, getSelectedDurationMinutes(), estimatedTotal);
  const activePromo =
    reservePromoPreview &&
    reservePromoPreview.selectionKey === promoSelectionKey &&
    reservePromoPreview.code === getReservePromoInputValue()
      ? reservePromoPreview
      : null;
  const categoryLabel = getMemberCategoryLabel(currentUser?.user_category);
  const memberBadge = categoryLabel
    ? `<div class="reserve-member-badge"><span class="reserve-member-badge-dot"></span>Booking as: ${escapeHtml(categoryLabel)}</div>`
    : "";
  const hourlyRate = getRoomHourlyRate(room);
  const rateLabel = `${formatCurrency(hourlyRate)} x ${formatDuration(getSelectedDurationMinutes())}`;

  if (!selectedStart) {
    elements.reserveSummaryMeta.innerHTML = `
      <div class="reserve-summary-context">
        <strong>${escapeHtml(room.name)}</strong>
        <span>${escapeHtml(selectedDate ? formatDateLabel(selectedDate) : "Choose a date")}</span>
      </div>
      ${memberBadge}
      <div class="reserve-price-line"><span>Date</span><strong>${escapeHtml(selectedDate ? formatDateLabel(selectedDate) : "Not selected")}</strong></div>
      <div class="reserve-price-line"><span>Start time</span><strong>Not selected</strong></div>
      <div class="reserve-price-line"><span>Duration</span><strong>${formatDuration(getSelectedDurationMinutes())}</strong></div>
      <div class="reserve-price-line"><span>${rateLabel}</span><strong>${formatCurrency(estimatedTotal)}</strong></div>
      <div class="reserve-price-line"><span>Service fee</span><strong class="reserve-price-free">Free</strong></div>
      ${
        activePromo
          ? `<div class="reserve-price-line"><span>Promo ${escapeHtml(activePromo.code)}</span><strong>-${formatCurrency(activePromo.discount_cents)}</strong></div>`
          : ""
      }
      ${(() => {
        const subtotal = activePromo ? activePromo.final_amount_cents : estimatedTotal;
        const gst = Math.floor(subtotal * 0.05);
        const deposit = getDepositCents(room);
        return `<div class="reserve-price-line"><span>GST (5%)</span><strong>${formatCurrency(gst)}</strong></div>
      <div class="reserve-price-total"><span>Total</span><strong>${formatCurrency(subtotal + gst)}</strong></div>
      <div class="reserve-price-line reserve-deposit-note"><span>Deposit due now</span><strong>${formatCurrency(deposit)}</strong></div>`;
      })()}
      <div class="reserve-helper-copy reserve-helper-copy-strong">Pick an available time to continue.</div>
    `;
    return;
  }

  elements.reserveSummaryMeta.innerHTML = `
    <div class="reserve-summary-context">
      <strong>${escapeHtml(room.name)}</strong>
      <span>${escapeHtml(formatDateTime(selectedStart))}</span>
    </div>
    ${memberBadge}
    <div class="reserve-price-line"><span>Date</span><strong>${escapeHtml(formatDateLabel(selectedDate))}</strong></div>
    <div class="reserve-price-line"><span>Start time</span><strong>${escapeHtml(formatTime(selectedStart))}</strong></div>
    <div class="reserve-price-line"><span>Duration</span><strong>${formatDuration(getSelectedDurationMinutes())}</strong></div>
    <div class="reserve-price-line"><span>${rateLabel}</span><strong>${formatCurrency(estimatedTotal)}</strong></div>
    <div class="reserve-price-line"><span>Service fee</span><strong class="reserve-price-free">Free</strong></div>
    ${
      activePromo
        ? `<div class="reserve-price-line"><span>Promo ${escapeHtml(activePromo.code)}</span><strong>-${formatCurrency(activePromo.discount_cents)}</strong></div>`
        : ""
    }
    ${renderSelectedStaffBreakdown(room)
      .replaceAll('class="summary-line"', 'class="reserve-price-line reserve-price-line-staff"')}
    ${(() => {
      const subtotal = activePromo ? activePromo.final_amount_cents : estimatedTotal;
      const gst = Math.floor(subtotal * 0.05);
      const deposit = getDepositCents(room);
      return `<div class="reserve-price-line"><span>GST (5%)</span><strong>${formatCurrency(gst)}</strong></div>
    <div class="reserve-price-total"><span>Total</span><strong>${formatCurrency(subtotal + gst)}</strong></div>
    <div class="reserve-price-line reserve-deposit-note"><span>Deposit due now</span><strong>${formatCurrency(deposit)}</strong></div>`;
    })()}
    <div class="reserve-helper-copy reserve-helper-copy-strong">${escapeHtml(formatDateTime(selectedStart))}</div>
  `;
}

function renderSubmitButton(currentState) {
  if (!elements.reserveSubmitButton) {
    return;
  }

  if (!currentState.selectedRoom) {
    elements.reserveSubmitButton.disabled = true;
    elements.reserveSubmitButton.textContent = "Choose a room first";
    return;
  }

  const guestName = getReserveGuestNameInput()?.value?.trim() || "";
  const guestPhone = getReserveGuestPhoneInput()?.value?.trim() || "";
  const hasContact = Boolean(currentState.currentUser || (guestName && guestPhone));
  const policyChecked = Boolean(getReservePolicyCheckbox()?.checked);
  const selection = getCurrentSelectionValidity();
  const canSubmit = Boolean(selection.valid && hasContact && policyChecked);
  const estimatedTotal = calculateEstimatedTotal(currentState.selectedRoom);
  const promoSelectionKey = getReservePromoSelectionKey(
    currentState.selectedRoom.id,
    selection.duration,
    estimatedTotal,
  );
  const activePromo =
    reservePromoPreview &&
    reservePromoPreview.selectionKey === promoSelectionKey &&
    reservePromoPreview.code === getReservePromoInputValue()
      ? reservePromoPreview
      : null;
  const totalLabel = formatCurrency(activePromo ? activePromo.final_amount_cents : estimatedTotal);
  elements.reserveSubmitButton.disabled = !canSubmit;
  elements.reserveSubmitButton.textContent = canSubmit
    ? `Continue to checkout ${totalLabel}`
    : !selection.valid
      ? loadingDay
        ? "Loading times..."
        : "Choose a valid time"
      : currentState.currentUser
        ? "Review details to continue"
        : "Add contact details to continue";
}

function renderCalendar() {
  if (!elements.reserveMonthGrid || !elements.reserveCalendarTitle || !displayedMonth) {
    return;
  }

  const monthDate = new Date(`${displayedMonth}T00:00:00`);
  elements.reserveCalendarTitle.textContent = new Intl.DateTimeFormat("en-CA", {
    month: "long",
    year: "numeric",
  }).format(monthDate);
  if (elements.reservePrevMonth) {
    elements.reservePrevMonth.disabled = displayedMonth <= firstOfMonth(todayString());
  }

  const firstDay = new Date(`${displayedMonth}T00:00:00`);
  const startOffset = firstDay.getDay();
  const totalDays = daysInMonth(displayedMonth);
  const cells = [];

  for (let index = 0; index < startOffset; index += 1) {
    cells.push('<div class="calendar-cell calendar-cell-empty"></div>');
  }

  for (let day = 1; day <= totalDays; day += 1) {
    const date = new Date(`${displayedMonth}T00:00:00`);
    date.setDate(day);
    const isoDate = date.toISOString().slice(0, 10);
    const isPast = isDateBeforeToday(isoDate);
    const count = isPast ? 0 : monthAvailability[isoDate];
    const isSelected = isoDate === selectedDate;
    const label = isPast ? "Past" : loadingMonth && count === undefined ? "checking" : `${count || 0} slots`;
    const ariaLabel = `${formatDateLabel(isoDate)}: ${label}${isSelected ? ", selected" : ""}`;
    cells.push(`
      <button
        class="calendar-cell ${isSelected ? "is-selected" : ""} ${count ? "is-open" : "is-closed"} ${isPast ? "is-past" : ""}"
        type="button"
        data-reserve-date="${escapeHtml(isoDate)}"
        aria-label="${escapeHtml(ariaLabel)}"
        ${isPast ? "disabled" : ""}
      >
        <strong>${day}</strong>
        <span>${escapeHtml(label)}</span>
      </button>
    `);
  }

  elements.reserveMonthGrid.innerHTML = cells.join("");
}

async function selectDate(roomId, date) {
  selectedDate = clampBookingDate(date);
  selectedStart = "";
  dayAvailability = null;
  clearReservePromoState("");
  if (elements.reserveDateInput) {
    elements.reserveDateInput.value = selectedDate;
  }
  renderRoomBookingView(state);
  await loadDayAvailability(roomId, selectedDate);
}

export function initRoomBookingView() {
  if (!elements.reserveBookingForm || !elements.reserveMonthGrid) {
    return;
  }

  elements.reserveDateButton?.addEventListener("click", async () => {
    if (!state.selectedRoom || !elements.reserveDateInput.value) {
      return;
    }
    await selectDate(String(state.selectedRoom.id), elements.reserveDateInput.value);
  });

  elements.reserveStartSelect?.addEventListener("change", () => {
    selectedStart = elements.reserveStartSelect.value;
    renderSlotList();
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
    updateDurationDisplay();
  });

  elements.reserveDurationSelect?.addEventListener("change", () => {
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
    updateDurationDisplay();
  });

  elements.reserveDurationDecrease?.addEventListener("click", () => {
    if (!elements.reserveDurationSelect) {
      return;
    }
    const values = Array.from(elements.reserveDurationSelect.options).map((option) => Number(option.value));
    const current = getSelectedDurationMinutes();
    const next = values.filter((value) => value < current).pop();
    if (!next) {
      return;
    }
    elements.reserveDurationSelect.value = String(next);
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
    updateDurationDisplay();
  });

  elements.reserveDurationIncrease?.addEventListener("click", () => {
    if (!elements.reserveDurationSelect) {
      return;
    }
    const values = Array.from(elements.reserveDurationSelect.options).map((option) => Number(option.value));
    const current = getSelectedDurationMinutes();
    const next = values.find((value) => value > current);
    if (!next) {
      return;
    }
    elements.reserveDurationSelect.value = String(next);
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
    updateDurationDisplay();
  });

  elements.reserveSlotList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-reserve-slot]");
    if (!button || !elements.reserveStartSelect) {
      return;
    }
    selectedStart = button.dataset.reserveSlot;
    elements.reserveStartSelect.value = selectedStart;
    renderSlotList();
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
    updateDurationDisplay();
  });

  elements.reserveMonthGrid.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-reserve-date]");
    if (!button || button.disabled || !state.selectedRoom) {
      return;
    }
    await selectDate(String(state.selectedRoom.id), button.dataset.reserveDate);
  });

  elements.reservePrevMonth?.addEventListener("click", async () => {
    if (!state.selectedRoom || !displayedMonth) {
      return;
    }
    const date = new Date(`${displayedMonth}T00:00:00`);
    date.setMonth(date.getMonth() - 1);
    const previousMonth = `${date.toISOString().slice(0, 7)}-01`;
    displayedMonth = previousMonth < firstOfMonth(todayString()) ? firstOfMonth(todayString()) : previousMonth;
    renderCalendar();
    await loadMonthAvailability(String(state.selectedRoom.id), displayedMonth);
  });

  elements.reserveNextMonth?.addEventListener("click", async () => {
    if (!state.selectedRoom || !displayedMonth) {
      return;
    }
    const date = new Date(`${displayedMonth}T00:00:00`);
    date.setMonth(date.getMonth() + 1);
    displayedMonth = `${date.toISOString().slice(0, 7)}-01`;
    renderCalendar();
    await loadMonthAvailability(String(state.selectedRoom.id), displayedMonth);
  });

  elements.reserveStaffOptions?.addEventListener("change", (event) => {
    const input = event.target.closest("input[type='checkbox']");
    if (!input) {
      return;
    }

    if (input.checked) {
      selectedStaffIds.add(input.value);
    } else {
      selectedStaffIds.delete(input.value);
    }
    invalidateReservePromoIfNeeded(state.selectedRoom);
    renderReservePromoFeedback();
    renderSummary(state);
    renderSubmitButton(state);
    renderReserveStepStatus(state);
  });

  [getReserveGuestNameInput(), getReserveGuestPhoneInput()].forEach((input) => {
    input?.addEventListener("input", () => {
      renderReserveStepStatus(state);
      renderSubmitButton(state);
    });
  });

  getReservePolicyCheckbox()?.addEventListener("change", () => {
    renderSubmitButton(state);
  });

  document.getElementById("reserve-promo-preview-button")?.addEventListener("click", async () => {
    await applyReservePromoPreview(state);
  });

  getReservePromoCodeInput()?.addEventListener("input", () => {
    if (!getReservePromoInputValue()) {
      clearReservePromoState("");
      renderReservePromoFeedback();
      renderSummary(state);
      return;
    }

    if (reservePromoPreview && reservePromoPreview.code !== getReservePromoInputValue()) {
      clearReservePromoState("Promo code changed. Apply again to refresh the total.");
      renderReservePromoFeedback();
      renderSummary(state);
    }
  });

  elements.reserveBookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    syncReserveDurationToSelectedStart(state.selectedRoom);
    const selection = getCurrentSelectionValidity();
    if (!state.selectedRoom || !selection.valid || !elements.reserveDurationSelect.value) {
      setState({ message: "Choose a valid day, slot, and duration first." });
      renderSlotList();
      renderSummary(state);
      renderSubmitButton(state);
      updateDurationDisplay();
      return;
    }
    if (isDateBeforeToday(selectedDate)) {
      await selectDate(String(state.selectedRoom.id), todayString());
      setState({ message: "Choose today or a future date." });
      return;
    }

    try {
      setState({ message: "Creating booking..." });
      const payload = {
        room_id: state.selectedRoom.id,
        start_time: selectedStart,
        duration_minutes: selection.duration,
        promo_code: getReservePromoInputValue() || null,
        note: buildSessionNote(),
        staff_assignments: [...selectedStaffIds],
      };
      let booking = null;
      if (state.currentUser) {
        booking = await api.createBooking(payload);
      } else {
        const guestName = getReserveGuestNameInput()?.value?.trim() || "";
        const guestPhone = getReserveGuestPhoneInput()?.value?.trim() || "";
        if (!guestName || !guestPhone) {
          setState({ message: "Enter your name and phone number to continue as guest." });
          return;
        }
        const guestSession = await api.createGuestBooking({
          ...payload,
          guest_name: guestName,
          guest_phone: guestPhone,
        });
        booking = guestSession.booking;
        persistToken(guestSession.access_token);
      }
      if (elements.reserveNoteInput) {
        elements.reserveNoteInput.value = "";
      }
      ["reserve-session-purpose", "reserve-attendees", "reserve-equipment-needs"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = "";
      });
      if (getReserveGuestNameInput()) {
        getReserveGuestNameInput().value = "";
      }
      if (getReserveGuestPhoneInput()) {
        getReserveGuestPhoneInput().value = "";
      }
      if (getReservePromoCodeInput()) {
        getReservePromoCodeInput().value = "";
      }
      clearReservePromoState("");
      await loadDayAvailability(String(state.selectedRoom.id), selectedDate);
      await loadMonthAvailability(String(state.selectedRoom.id), displayedMonth);
      persistLastBookingId(booking.id);
      persistCheckoutDraft({ booking });
      window.location.href = `/booking?id=${booking.id}`;
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

function updateDurationDisplay() {
  if (!elements.reserveDurationDisplay || !elements.reserveDurationUnit) {
    return;
  }
  const hours = getSelectedDurationMinutes() / 60;
  elements.reserveDurationDisplay.textContent = String(hours);
  elements.reserveDurationUnit.textContent = hours === 1 ? "hour" : "hours";
  const values = Array.from(elements.reserveDurationSelect?.options || []).map((option) => Number(option.value));
  if (elements.reserveDurationDecrease) {
    elements.reserveDurationDecrease.disabled = values.length ? getSelectedDurationMinutes() <= Math.min(...values) : true;
  }
  if (elements.reserveDurationIncrease) {
    elements.reserveDurationIncrease.disabled = values.length ? getSelectedDurationMinutes() >= Math.max(...values) : true;
  }
}

export function renderRoomBookingView(currentState) {
  if (!elements.reserveEmpty || !elements.reservePlannerPanel || !elements.reserveCalendarPanel) {
    return;
  }

  const room = currentState.selectedRoom;
  const hasRoom = Boolean(room);

  // Hard block: coming-soon and inactive rooms are not bookable
  if (room && (!room.active || room.coming_soon)) {
    window.location.replace(`/room?id=${room.id}`);
    return;
  }

  toggleHidden(elements.reserveEmpty, hasRoom);
  toggleHidden(elements.reservePlannerPanel, !hasRoom);
  toggleHidden(elements.reserveSummaryPanel, !hasRoom);
  toggleHidden(elements.reserveCalendarPanel, !hasRoom);

  if (!room) {
    return;
  }

  if (String(room.id) !== lastRoomId) {
    lastRoomId = String(room.id);
    selectedDate = todayString();
    displayedMonth = firstOfMonth(selectedDate);
    dayAvailability = null;
    monthAvailability = {};
    selectedStart = "";
    selectedStaffIds = new Set();
    clearReservePromoState("");
    if (elements.reserveDateInput) {
      elements.reserveDateInput.min = todayString();
      elements.reserveDateInput.value = selectedDate;
    }
    if (elements.reserveNoteInput) {
      elements.reserveNoteInput.value = "";
    }
    if (elements.reserveStartSelect) {
      elements.reserveStartSelect.innerHTML = "";
    }
    void loadDayAvailability(lastRoomId, selectedDate);
    void loadMonthAvailability(lastRoomId, displayedMonth);
  }

  renderRoomVisuals(room);
  if (elements.reserveRoomTitle) {
    elements.reserveRoomTitle.textContent = room.name;
  }
  getReserveGuestFields()?.classList.toggle("hidden", Boolean(currentState.currentUser));
  if (elements.reserveRoomCopy) {
    const bookingPrompt = currentState.currentUser
      ? "Pick a date and start time, then complete your session details below."
      : "Pick a date and start time, then enter your contact info to continue.";
    elements.reserveRoomCopy.textContent = `${room.description || "Review available times for this room."} ${bookingPrompt}`;
  }

  if (elements.reserveDateInput && selectedDate && elements.reserveDateInput.value !== selectedDate) {
    elements.reserveDateInput.min = todayString();
    elements.reserveDateInput.value = selectedDate;
  }

  renderDaySummary(currentState);
  renderSlotList();
  renderStaffOptions(currentState);
  invalidateReservePromoIfNeeded(currentState.selectedRoom);
  renderReservePromoFeedback();
  renderSummary(currentState);
  renderCalendar();
  renderSubmitButton(currentState);
  renderReserveStepStatus(currentState);
  updateDurationDisplay();
}
