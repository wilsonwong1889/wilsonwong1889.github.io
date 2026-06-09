import { API_BASE_URL, getSearchParam } from "../config.js";
import { elements } from "../dom.js";
import {
  persistCheckoutDraft,
  persistLastBookingId,
  persistToken,
  setState,
  state,
} from "../state.js";

const STAFF_PLACEHOLDER_IMAGE = "/assets/media/staff/staff-placeholder.svg";

let staffProfilesCache = [];
let selectedStaffId = getSearchParam("staff_id") || "";
let selectedDate = todayString();
let selectedTime = "";
let selectedDuration = 60;
let selectedAvailability = null;
let loadingAvailability = false;
let lastAvailabilityKey = "";
let availabilityRequestToken = 0;
let displayedStaffMonth = firstOfMonth(selectedDate);
let staffMonthAvailability = {};
let loadingStaffMonth = false;
let staffMonthAvailabilityRequestToken = 0;
let viewBound = false;
let staffSearchQuery = "";
let staffCategoryFilter = "all";
let staffSortMode = "recommended";
let staffPromoPreview = null;

const STAFF_DURATION_OPTIONS = [60, 120, 180, 240, 300];

function todayString() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isDateBeforeToday(value) {
  return Boolean(value && value < todayString());
}

function clampBookingDate(value) {
  return isDateBeforeToday(value) ? todayString() : value || todayString();
}

function firstOfMonth(value) {
  return `${String(value || todayString()).slice(0, 7)}-01`;
}

function daysInMonth(monthValue) {
  const base = new Date(`${monthValue}T00:00:00`);
  const year = base.getFullYear();
  const month = base.getMonth();
  return new Date(year, month + 1, 0).getDate();
}

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format((Number(cents) || 0) / 100);
}

function formatDateLabel(value) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
  }).format(new Date(`${value}T00:00:00`));
}

function formatTimeLabel(value) {
  if (!value) {
    return "";
  }

  if (String(value).includes("T")) {
    return new Intl.DateTimeFormat("en-CA", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  }

  const normalized = String(value).padStart(5, "0");
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(`1970-01-01T${normalized}:00`));
}

function formatDuration(minutes) {
  const hours = Number(minutes || 0) / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStaffImage(photoUrl, label) {
  const source = photoUrl || STAFF_PLACEHOLDER_IMAGE;
  return `<img class="staff-profile-image" src="${escapeHtml(source)}" alt="${escapeHtml(label)}" loading="lazy" />`;
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

function getStaffRateCents(profile) {
  return Number(
    profile?.booking_rate_cents ??
    profile?.hourly_rate_cents ??
    profile?.session_rate_cents ??
    profile?.add_on_price_cents ??
    0,
  );
}

function getStaffRateLabel(profile) {
  // Booking a staff member on their own is request-based: the customer sends a
  // request and the staff member confirms the rate. (Staff added to a room
  // booking are charged there.) Shown as "Request" — never "Free".
  return "Request";
}

function getStaffRating(profile) {
  const seed = String(profile?.id || profile?.name || "")
    .split("")
    .reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return 4.6 + (seed % 4) / 10;
}

function getStaffPrimaryCategory(profile) {
  return (
    (profile?.skills || []).find(Boolean) ||
    (profile?.talents || []).find(Boolean) ||
    (profile?.service_types || []).find(Boolean) ||
    "Creative"
  );
}

function getStaffSearchText(profile) {
  return [
    profile?.name,
    profile?.description,
    getStaffPrimaryCategory(profile),
    ...(profile?.skills || []),
    ...(profile?.talents || []),
    ...(profile?.service_types || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function getSelectedStaffProfile() {
  return staffProfilesCache.find((profile) => String(profile.id) === String(selectedStaffId)) || null;
}

function getStaffServiceOptions(profile) {
  const values = new Set(
    (profile?.service_types || []).length
      ? profile.service_types
      : ["Creative session", "Recording support", "Podcast support", "Production help", "Consultation"],
  );
  (profile?.skills || []).slice(0, 3).forEach((value) => values.add(value));
  (profile?.talents || []).slice(0, 3).forEach((value) => values.add(value));
  return Array.from(values);
}

function parseAvailabilitySlots(payload) {
  const rawSlots =
    payload?.available_start_times ||
    payload?.available_slots ||
    payload?.slots ||
    payload?.times ||
    [];
  const durationMap = payload?.max_duration_minutes_by_start || {};

  return rawSlots
    .map((slot) => {
      if (typeof slot === "string") {
        return {
          value: slot,
          label: formatTimeLabel(slot),
          available: true,
          maxDurationMinutes: durationMap[slot] || null,
        };
      }

      const value = slot.value || slot.start_time || slot.start || slot.time || "";
      if (!value) {
        return null;
      }

      return {
        value,
        label: slot.label || slot.text || formatTimeLabel(value),
        available: slot.available !== false,
        maxDurationMinutes: slot.max_duration_minutes || slot.maxDurationMinutes || durationMap[value] || null,
      };
    })
    .filter(Boolean);
}

function buildTimeValue(slotValue) {
  if (!slotValue) {
    return "";
  }

  if (String(slotValue).includes("T")) {
    return slotValue;
  }

  const normalized = String(slotValue).length === 5 ? `${slotValue}:00` : String(slotValue);
  return new Date(`${selectedDate}T${normalized}`).toISOString();
}

function getTimeGrid() {
  return document.getElementById("staff-booking-time-grid");
}

function getSelectedCard() {
  return document.getElementById("staff-booking-selected-card");
}

function getAvailabilitySummary() {
  return document.getElementById("staff-booking-availability");
}

function getBookingStatus() {
  return document.getElementById("staff-booking-status");
}

function getSummaryCard() {
  return document.getElementById("staff-booking-summary-card");
}

function getSummaryDate() {
  return document.getElementById("staff-booking-summary-date");
}

function getSummaryTime() {
  return document.getElementById("staff-booking-summary-time");
}

function getSummaryDuration() {
  return document.getElementById("staff-booking-summary-duration");
}

function getSummaryTotal() {
  return document.getElementById("staff-booking-summary-total");
}

function getSubmitButton() {
  return document.getElementById("staff-booking-submit");
}

function getBookingDateInput() {
  return document.getElementById("staff-booking-date");
}

function getStaffBookingMonthGrid() {
  return document.getElementById("staff-booking-month-grid");
}

function getStaffBookingCalendarTitle() {
  return document.getElementById("staff-booking-calendar-title");
}

function getStaffBookingPrevMonth() {
  return document.getElementById("staff-booking-prev-month");
}

function getStaffBookingNextMonth() {
  return document.getElementById("staff-booking-next-month");
}

function getBookingDurationSelect() {
  return document.getElementById("staff-booking-duration");
}

function getBookingServiceSelect() {
  return document.getElementById("staff-booking-service");
}

function getBookingNameInput() {
  return document.getElementById("staff-booking-name");
}

function getBookingPhoneInput() {
  return document.getElementById("staff-booking-phone");
}

function getBookingEmailInput() {
  return document.getElementById("staff-booking-email");
}

function getBookingNotesInput() {
  return document.getElementById("staff-booking-notes");
}

function getStaffPromoCodeInput() {
  return document.getElementById("staff-booking-promo-code");
}

function getStaffPromoPreviewButton() {
  return document.getElementById("staff-booking-promo-preview-button");
}

function getStaffPromoFeedback() {
  return document.getElementById("staff-booking-promo-feedback");
}

function getBookingShell() {
  return document.getElementById("staff-booking-shell");
}

function getStaffSearchInput() {
  return document.getElementById("staff-search-text");
}

function getStaffCategoryBar() {
  return document.getElementById("staff-role-bar");
}

function getStaffResultsCount() {
  return document.getElementById("staff-results-count");
}

function getStaffFilterToggle() {
  return document.getElementById("staff-filter-toggle");
}

function getStaffFilterPanel() {
  return document.getElementById("staff-filter-panel");
}

function getStaffSortSelect() {
  return document.getElementById("staff-sort-select");
}

function getStaffStepList() {
  return document.getElementById("staff-booking-step-list");
}

function getDurationDecreaseButton() {
  return document.getElementById("staff-booking-duration-decrease");
}

function getDurationIncreaseButton() {
  return document.getElementById("staff-booking-duration-increase");
}

function getDurationDisplay() {
  return document.getElementById("staff-booking-duration-display");
}

function getDurationUnit() {
  return document.getElementById("staff-booking-duration-unit");
}

function buildRequestHeaders(hasBody = false) {
  const headers = new Headers();
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: buildRequestHeaders(Boolean(options.body)),
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = typeof data === "object" && data !== null && "detail" in data ? data.detail : "Request failed";
    throw new Error(detail);
  }

  return data;
}

function setStatus(message, isError = false) {
  const status = getBookingStatus();
  if (status) {
    status.textContent = message;
    status.classList.toggle("staff-booking-status-error", Boolean(isError));
  }
  setState({ message });
}

function getStaffPromoInputValue() {
  return (getStaffPromoCodeInput()?.value || "").trim().toUpperCase();
}

function getEstimatedStaffTotal(profile, durationMinutes = getSelectedDurationMinutes()) {
  // Direct staff bookings are free requests — no charge.
  return 0;
}

function getStaffPromoSelectionKey(profile, durationMinutes, amountCents) {
  return [profile?.id || "", durationMinutes || 0, amountCents || 0].join(":");
}

function getCurrentStaffPromoPreview(profile, durationMinutes, amountCents) {
  const code = getStaffPromoInputValue();
  if (!code || !staffPromoPreview) {
    return null;
  }
  const selectionKey = getStaffPromoSelectionKey(profile, durationMinutes, amountCents);
  if (staffPromoPreview.code !== code || staffPromoPreview.selectionKey !== selectionKey) {
    return null;
  }
  return staffPromoPreview;
}

function clearStaffPromoState() {
  staffPromoPreview = null;
}

function renderStaffPromoFeedback(profile) {
  const feedback = getStaffPromoFeedback();
  if (!feedback) {
    return;
  }

  const code = getStaffPromoInputValue();
  const durationMinutes = getSelectedDurationMinutes();
  const amountCents = getEstimatedStaffTotal(profile, durationMinutes);
  const appliedPromo = getCurrentStaffPromoPreview(profile, durationMinutes, amountCents);

  if (!code && !appliedPromo) {
    feedback.className = "empty-state booking-promo-feedback hidden";
    feedback.textContent = "";
    return;
  }

  if (appliedPromo) {
    feedback.className = "empty-state booking-promo-feedback booking-promo-feedback-success";
    feedback.innerHTML = `<strong>${escapeHtml(appliedPromo.code)}</strong> saves ${formatCurrency(appliedPromo.discount_cents)}. New total: ${formatCurrency(appliedPromo.final_amount_cents)}.`;
    return;
  }

  feedback.className = "empty-state booking-promo-feedback";
  feedback.textContent = "Apply the promo code to preview the staff booking total.";
}

async function applyStaffPromoPreview() {
  const profile = getSelectedStaffProfile();
  const code = getStaffPromoInputValue();
  const durationMinutes = getSelectedDurationMinutes();
  const amountCents = getEstimatedStaffTotal(profile, durationMinutes);
  const feedback = getStaffPromoFeedback();

  if (!profile || amountCents <= 0) {
    clearStaffPromoState();
    renderStaffPromoFeedback(profile);
    setStatus("Choose staff and duration before applying a promo code.", true);
    return;
  }
  if (!code) {
    clearStaffPromoState();
    renderStaffPromoFeedback(profile);
    setStatus("Enter a promo code first.", true);
    return;
  }

  try {
    setStatus("Checking promo code...");
    const preview = await request("/api/public/promo-codes/preview", {
      method: "POST",
      body: JSON.stringify({
        code,
        amount_cents: amountCents,
      }),
    });
    staffPromoPreview = {
      ...preview,
      code: preview.code || code,
      selectionKey: getStaffPromoSelectionKey(profile, durationMinutes, amountCents),
    };
    renderStaffBookingShell({ currentUser: state.currentUser });
    setStatus(`${staffPromoPreview.code} applied.`);
  } catch (error) {
    clearStaffPromoState();
    if (feedback) {
      feedback.className = "empty-state booking-promo-feedback booking-promo-feedback-error";
      feedback.textContent = error.message || "Promo code could not be applied.";
    }
    renderSummary(profile);
    setStatus(error.message || "Promo code could not be applied.", true);
  }
}

function syncSelectionUrl(staffId) {
  const url = new URL(window.location.href);
  if (staffId) {
    url.searchParams.set("staff_id", staffId);
    url.hash = "staff-booking-shell";
  } else {
    url.searchParams.delete("staff_id");
  }
  window.history.replaceState({}, "", url.toString());
}

function getStaffCategories(profiles) {
  const counts = new Map();
  profiles.forEach((profile) => {
    const values = [...(profile.skills || []), ...(profile.talents || []), ...(profile.service_types || [])]
      .filter(Boolean)
      .slice(0, 5);
    values.forEach((value) => {
      counts.set(value, (counts.get(value) || 0) + 1);
    });
  });
  return Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 6)
    .map(([value]) => value);
}

function renderStaffCategoryBar(profiles) {
  const bar = document.getElementById("staff-role-bar");
  if (!bar) return;

  const ROLES = [
    { value: "all", label: "All" },
    { value: "photographer", label: "Photographer" },
    { value: "videographer", label: "Videographer" },
    { value: "sound-engineer", label: "Sound Engineer" },
    { value: "music-producer", label: "Music Producer" },
    { value: "podcast-producer", label: "Podcast Producer" },
  ];

  bar.innerHTML = ROLES.map((role) => {
    const isActive = staffCategoryFilter === role.value;
    return `<button class="staff-role-pill${isActive ? " is-active" : ""}" type="button" data-staff-role="${escapeHtml(role.value)}">${escapeHtml(role.label)}</button>`;
  }).join("");

  bar.querySelectorAll(".staff-role-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      staffCategoryFilter = btn.dataset.staffRole || "all";
      renderStaffCategoryBar(profiles);
      renderStaffCatalog(staffProfilesCache);
    });
  });
}

function getVisibleStaffProfiles(profiles) {
  const query = staffSearchQuery.trim().toLowerCase();
  const filtered = profiles.filter((profile) => {
    const matchesQuery = !query || getStaffSearchText(profile).includes(query);
    const matchesCategory =
      staffCategoryFilter === "all" ||
      getStaffSearchText(profile).includes(staffCategoryFilter.replace(/-/g, " "));
    return matchesQuery && matchesCategory;
  });

  return filtered.sort((left, right) => {
    if (staffSortMode === "rate-low") {
      return getStaffRateCents(left) - getStaffRateCents(right);
    }
    if (staffSortMode === "rate-high") {
      return getStaffRateCents(right) - getStaffRateCents(left);
    }
    if (staffSortMode === "name") {
      return String(left.name || "").localeCompare(String(right.name || ""));
    }
    return getStaffRating(right) - getStaffRating(left);
  });
}

function renderSelectedCard(profile) {
  const target = document.getElementById("staff-booking-selected-card");
  const profileCard = document.getElementById("staff-profile-card");

  if (!profile) {
    if (target) {
      target.className = "staff-booking-selected-card empty-state";
      target.innerHTML = "Choose a staff member from the catalog above.";
    }
    if (profileCard) profileCard.innerHTML = "";
    return;
  }

  // Small summary in booking sidebar
  if (target) {
    target.className = "staff-booking-selected-card staff-reserve-profile-card";
    target.innerHTML = `
      <div class="staff-booking-summary-top">
        ${renderStaffImage(profile.photo_url, profile.name)}
        <div class="staff-option-copy">
          <strong>${escapeHtml(profile.name)}</strong>
          <span>${escapeHtml(getStaffPrimaryCategory(profile))} · ${escapeHtml(getStaffRateLabel(profile))}</span>
        </div>
      </div>
    `;
  }

  // Rich profile in left column
  if (profileCard) {
    const name = escapeHtml(profile.name || "Team Member");
    const role = escapeHtml(getStaffPrimaryCategory(profile));
    const tagline = (profile.description || "").trim();
    const bioBody = (profile.bio || "").trim();
    const bioText = escapeHtml(bioBody || tagline || "Arts Marvels creative professional.");
    // Show the short description as a lead line only when there is also a longer bio.
    const taglineHtml = bioBody && tagline && tagline !== bioBody
      ? `<p class="staff-profile-bio-lead">${escapeHtml(tagline)}</p>`
      : "";
    const rate = escapeHtml(getStaffRateLabel(profile));
    const skills = (profile.skills || []);
    const talents = (profile.talents || []);
    const services = Array.from(
      new Set([...(profile.service_types || []), ...(profile.services || [])].filter(Boolean)),
    );
    const gear = (profile.gear || "").trim();
    const photoSrc = profile.photo_url || STAFF_PLACEHOLDER_IMAGE;

    const skillTags = skills.map((s) => `<span class="staff-profile-tag">${escapeHtml(s)}</span>`).join("") || '<span class="staff-profile-tag">Creative</span>';
    const talentTags = talents.map((t) => `<span class="staff-profile-tag">${escapeHtml(t)}</span>`).join("") || '<span class="staff-profile-tag">Production</span>';
    const serviceTags = services.map((s) => `<span class="staff-profile-tag">${escapeHtml(s)}</span>`).join("");
    const servicesHtml = services.length
      ? `<div>
          <p class="staff-profile-section-label">Services offered</p>
          <div class="staff-profile-tags">${serviceTags}</div>
        </div>`
      : "";
    const gearHtml = gear
      ? `<div>
          <p class="staff-profile-section-label">Gear &amp; equipment</p>
          <p class="staff-profile-bio-text staff-profile-gear-text">${escapeHtml(gear)}</p>
        </div>`
      : "";
    const portfolioPhotos = (Array.isArray(profile.headshot_urls) ? profile.headshot_urls : []).filter(Boolean);
    const portfolioHtml = portfolioPhotos.length
      ? `<div class="staff-profile-portfolio">
          <p class="staff-profile-section-label">Portfolio</p>
          <div class="staff-portfolio-gallery">
            ${portfolioPhotos
              .map(
                (url, index) => `
              <a class="staff-portfolio-item" href="${escapeHtml(url)}" target="_blank" rel="noreferrer" aria-label="Open portfolio image ${index + 1} for ${name}">
                <img src="${escapeHtml(url)}" alt="${name} portfolio ${index + 1}" loading="lazy" />
              </a>`,
              )
              .join("")}
          </div>
        </div>`
      : "";
    const instagramHtml = profile.instagram_url
      ? `<a class="staff-profile-instagram" href="${escapeHtml(profile.instagram_url)}" target="_blank" rel="noreferrer" aria-label="${name} on Instagram">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>
          <span>Instagram</span>
        </a>`
      : "";

    profileCard.innerHTML = `
      <div class="staff-profile-photo-block">
        <img class="staff-profile-photo" src="${escapeHtml(photoSrc)}" alt="${name}" loading="lazy" onerror="this.onerror=null;this.src='${escapeHtml(STAFF_PLACEHOLDER_IMAGE)}';" />
        <div class="staff-profile-photo-overlay"></div>
        <div class="staff-profile-photo-info">
          <h2 class="staff-profile-photo-name">${name}</h2>
          <p class="staff-profile-photo-role">${role}</p>
          <span class="staff-profile-availability-badge">
            <span class="staff-profile-availability-dot"></span>
            Available to book
          </span>
        </div>
      </div>
      <div class="staff-profile-body">
        ${instagramHtml}
        <div>
          <p class="staff-profile-section-label">About</p>
          ${taglineHtml}
          <p class="staff-profile-bio-text">${bioText}</p>
        </div>
        <div class="staff-profile-skills-grid">
          <div class="staff-profile-tag-group">
            <p class="staff-profile-section-label">Skills</p>
            <div class="staff-profile-tags">${skillTags}</div>
          </div>
          <div class="staff-profile-tag-group">
            <p class="staff-profile-section-label">Specialties</p>
            <div class="staff-profile-tags">${talentTags}</div>
          </div>
        </div>
        ${servicesHtml}
        ${gearHtml}
        <div class="staff-profile-meta-row">
          <div class="staff-profile-meta-block">
            <span class="staff-profile-meta-label">Rate</span>
            <span class="staff-profile-meta-value">${rate}</span>
            <span class="staff-profile-meta-sub">Guest checkout available</span>
          </div>
          <div class="staff-profile-meta-block">
            <span class="staff-profile-meta-label">Hours</span>
            <span class="staff-profile-meta-value">Wed – Sat</span>
            <span class="staff-profile-meta-sub">12:00 PM – 8:00 PM</span>
          </div>
        </div>
        ${portfolioHtml}
      </div>
    `;
  }
}

function renderSummaryCard(profile) {
  const target = getSummaryCard();
  if (!target) {
    return;
  }

  if (!profile) {
    target.className = "staff-booking-summary-card empty-state";
    target.innerHTML = "Choose a staff member to see their summary here.";
    return;
  }

  target.className = "staff-booking-summary-card";
  target.innerHTML = `
    <div class="staff-booking-summary-top">
      ${renderStaffImage(profile.photo_url, profile.name)}
      <div class="staff-option-copy">
        <strong>${escapeHtml(profile.name)}</strong>
        <span>${escapeHtml(profile.description || "Public staff profile.")}</span>
      </div>
    </div>
    <div class="room-meta">
      <span class="pill">${escapeHtml(getStaffRateLabel(profile))}</span>
      <span class="pill">${escapeHtml(getStaffPrimaryCategory(profile))}</span>
    </div>
  `;
}

function renderServiceOptions(profile) {
  const select = getBookingServiceSelect();
  if (!select) {
    return;
  }

  const options = getStaffServiceOptions(profile);
  select.innerHTML = options.map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join("");
  if (!options.includes(select.value)) {
    select.value = options[0] || "Creative session";
  }
}

function getSelectedSlot() {
  const slots = Array.isArray(selectedAvailability?.slots) ? selectedAvailability.slots : [];
  return slots.find((slot) => String(slot.value) === String(selectedTime)) || null;
}

function availabilityMatchesSelection(profile) {
  if (!profile || !selectedAvailability) {
    return false;
  }

  const availabilityDate = selectedAvailability.date ? String(selectedAvailability.date) : selectedDate;
  const availabilityStaffId = selectedAvailability.staff_profile_id
    ? String(selectedAvailability.staff_profile_id)
    : String(profile.id);
  return availabilityDate === selectedDate && availabilityStaffId === String(profile.id);
}

function getSlotMaxDuration(slot) {
  const maxDuration = Number(slot?.maxDurationMinutes || 300);
  return Number.isFinite(maxDuration) && maxDuration >= 60 ? Math.min(maxDuration, 300) : 0;
}

function getAllowedStaffDurations() {
  const selectedSlot = getSelectedSlot();
  if (!selectedSlot || selectedSlot.available === false) {
    return [60];
  }

  const maxDuration = getSlotMaxDuration(selectedSlot);
  return STAFF_DURATION_OPTIONS.filter((minutes) => minutes <= maxDuration);
}

function getSelectedDurationMinutes() {
  const allowedDurations = getAllowedStaffDurations();
  if (!allowedDurations.includes(Number(selectedDuration))) {
    selectedDuration = allowedDurations[0] || 60;
  }
  return selectedDuration;
}

function syncDurationControls() {
  const durationSelect = getBookingDurationSelect();
  const display = getDurationDisplay();
  const unit = getDurationUnit();
  const decreaseButton = getDurationDecreaseButton();
  const increaseButton = getDurationIncreaseButton();
  const allowedDurations = getAllowedStaffDurations();
  const durationMinutes = getSelectedDurationMinutes();
  const currentIndex = allowedDurations.indexOf(durationMinutes);
  const hasActiveSlot = Boolean(getSelectedSlot() && !loadingAvailability);

  if (durationSelect) {
    durationSelect.innerHTML = allowedDurations
      .map((minutes) => `<option value="${minutes}">${formatDuration(minutes)}</option>`)
      .join("");
    durationSelect.value = String(durationMinutes);
    durationSelect.disabled = !hasActiveSlot;
  }
  if (display) {
    display.textContent = String(durationMinutes / 60);
  }
  if (unit) {
    unit.textContent = durationMinutes === 60 ? "hour" : "hours";
  }
  if (decreaseButton) {
    decreaseButton.disabled = !hasActiveSlot || currentIndex <= 0;
  }
  if (increaseButton) {
    increaseButton.disabled = !hasActiveSlot || currentIndex < 0 || currentIndex >= allowedDurations.length - 1;
  }
}

function getStaffSelectionValidity(profile) {
  const selectedSlot = getSelectedSlot();
  const durationMinutes = getSelectedDurationMinutes();
  const maxDuration = getSlotMaxDuration(selectedSlot);
  const valid = Boolean(
    profile &&
      !loadingAvailability &&
      availabilityMatchesSelection(profile) &&
      selectedSlot &&
      selectedSlot.available !== false &&
      durationMinutes >= 60 &&
      durationMinutes <= maxDuration,
  );

  return {
    valid,
    selectedSlot,
    durationMinutes,
    maxDuration,
  };
}

function renderStaffBookingCalendar(profile) {
  const grid = getStaffBookingMonthGrid();
  const title = getStaffBookingCalendarTitle();
  if (!grid || !title || !displayedStaffMonth) {
    return;
  }

  const monthDate = new Date(`${displayedStaffMonth}T00:00:00`);
  title.textContent = new Intl.DateTimeFormat("en-CA", {
    month: "long",
    year: "numeric",
  }).format(monthDate);

  const prev = getStaffBookingPrevMonth();
  if (prev) {
    prev.disabled = displayedStaffMonth <= firstOfMonth(todayString()) || !profile;
  }
  const next = getStaffBookingNextMonth();
  if (next) {
    next.disabled = !profile;
  }

  if (!profile) {
    grid.innerHTML = '<div class="empty-state staff-calendar-empty">Choose a staff member first.</div>';
    return;
  }

  const firstDay = new Date(`${displayedStaffMonth}T00:00:00`);
  const startOffset = firstDay.getDay();
  const totalDays = daysInMonth(displayedStaffMonth);
  const cells = [];

  for (let index = 0; index < startOffset; index += 1) {
    cells.push('<div class="calendar-cell calendar-cell-empty"></div>');
  }

  for (let day = 1; day <= totalDays; day += 1) {
    const date = new Date(`${displayedStaffMonth}T00:00:00`);
    date.setDate(day);
    const isoDate = date.toISOString().slice(0, 10);
    const isPast = isDateBeforeToday(isoDate);
    const count = isPast ? 0 : staffMonthAvailability[isoDate];
    const isSelected = isoDate === selectedDate;
    const label = isPast
      ? "Past"
      : loadingStaffMonth && count === undefined
        ? "checking"
        : count
          ? `${count} slots`
          : "Unavailable";
    const ariaLabel = `${formatDateLabel(isoDate)}: ${label}${isSelected ? ", selected" : ""}`;
    cells.push(`
      <button
        class="calendar-cell ${isSelected ? "is-selected" : ""} ${count ? "is-open" : "is-closed"} ${isPast ? "is-past" : ""}"
        type="button"
        data-staff-booking-date="${escapeHtml(isoDate)}"
        aria-label="${escapeHtml(ariaLabel)}"
        ${isPast ? "disabled" : ""}
      >
        <strong>${day}</strong>
        <span>${escapeHtml(label)}</span>
      </button>
    `);
  }

  grid.innerHTML = cells.join("");
}

function hasContactDetails() {
  return Boolean(getBookingNameInput()?.value.trim() && getBookingPhoneInput()?.value.trim());
}

function renderStaffBookingSteps(profile) {
  const stepList = getStaffStepList();
  if (!stepList) {
    return;
  }

  const hasStaff = Boolean(profile);
  const hasTime = getStaffSelectionValidity(profile).valid;
  const hasDetails = Boolean(hasTime && hasContactDetails());
  const activeStep = !hasStaff ? "staff" : !hasTime ? "time" : !hasDetails ? "details" : "checkout";
  const completeSteps = {
    staff: hasStaff,
    time: hasTime,
    details: hasDetails,
    checkout: hasDetails,
  };

  stepList.querySelectorAll("[data-staff-step]").forEach((step) => {
    const key = step.dataset.staffStep;
    step.classList.toggle("is-active", key === activeStep);
    step.classList.toggle("is-complete", Boolean(completeSteps[key]) && key !== activeStep);
  });
}

function renderAvailability(profile) {
  const target = getTimeGrid();
  const summary = getAvailabilitySummary();
  const currentDate = getBookingDateInput()?.value || selectedDate;

  if (!target || !summary) {
    return;
  }

  if (!profile) {
    target.innerHTML = "";
    summary.className = "reserve-helper-copy staff-booking-availability";
    summary.innerHTML = "Pick a staff member and date to see openings.";
    return;
  }

  if (loadingAvailability) {
    summary.className = "reserve-helper-copy staff-booking-availability";
    summary.innerHTML = `Loading openings for ${formatDateLabel(currentDate)}...`;
    target.innerHTML = "";
    return;
  }

  const slots = availabilityMatchesSelection(profile) && Array.isArray(selectedAvailability?.slots) ? selectedAvailability.slots : [];
  if (!slots.length) {
    target.innerHTML = "";
    summary.className = "reserve-helper-copy staff-booking-availability";
    summary.innerHTML = `No openings were returned for ${formatDateLabel(currentDate)}.`;
    return;
  }

  summary.className = "reserve-helper-copy staff-booking-availability reserve-helper-copy-strong";
  summary.innerHTML = `${slots.length} opening${slots.length === 1 ? "" : "s"} on ${formatDateLabel(currentDate)}`;
  target.innerHTML = slots
    .map((slot) => {
      const selected = selectedTime === slot.value;
      const disabled = slot.available === false ? "disabled" : "";
      return `
        <button
          class="slot-card ${selected ? "is-selected" : ""}"
          type="button"
          data-staff-time="${escapeHtml(slot.value)}"
          ${disabled}
        >
          <strong>${escapeHtml(slot.label || formatTimeLabel(slot.value))}</strong>
          <span>${slot.maxDurationMinutes ? `Up to ${formatDuration(slot.maxDurationMinutes)}` : "Tap to select"}</span>
        </button>
      `;
    })
    .join("");
}

function renderSummary(profile) {
  const dateNode = getSummaryDate();
  const timeNode = getSummaryTime();
  const durationNode = getSummaryDuration();
  const totalNode = getSummaryTotal();
  const submitButton = getSubmitButton();
  const selection = getStaffSelectionValidity(profile);
  const formReady = Boolean(selection.valid && selectedDate && hasContactDetails());
  const durationMinutes = selection.durationMinutes;
  const estimatedTotal = getEstimatedStaffTotal(profile, durationMinutes);
  const appliedPromo = getCurrentStaffPromoPreview(profile, durationMinutes, estimatedTotal);
  const checkoutTotal = appliedPromo ? appliedPromo.final_amount_cents : estimatedTotal;

  if (dateNode) {
    dateNode.textContent = selectedDate ? formatDateLabel(selectedDate) : "Select a date";
  }
  if (timeNode) {
    timeNode.textContent = selectedTime ? formatTimeLabel(selectedTime) : "Choose an opening";
  }
  if (durationNode) {
    durationNode.textContent = formatDuration(durationMinutes);
  }
  if (totalNode) {
    totalNode.textContent = "Request";
  }
  if (submitButton) {
    submitButton.disabled = !formReady;
    submitButton.textContent = formReady ? "Send booking request" : "Send booking request";
  }
}

function fillSignedInFields(currentState) {
  if (!currentState.currentUser) {
    return;
  }

  const nameInput = getBookingNameInput();
  const emailInput = getBookingEmailInput();
  const phoneInput = getBookingPhoneInput();
  if (nameInput && !nameInput.value) {
    nameInput.value = currentState.currentUser.full_name || currentState.currentUser.name || "";
  }
  if (emailInput && !emailInput.value) {
    emailInput.value = currentState.currentUser.email || "";
  }
  if (phoneInput && !phoneInput.value) {
    phoneInput.value = currentState.currentUser.phone || currentState.currentUser.phone_number || "";
  }
}

function renderStaffBookingShell(currentState) {
  const profile = getSelectedStaffProfile();
  const shell = getBookingShell();
  const dateInput = getBookingDateInput();
  const durationSelect = getBookingDurationSelect();

  if (!shell) {
    return;
  }

  shell.classList.toggle("is-ready", Boolean(profile));
  shell.classList.toggle("hidden", !profile);
  renderSelectedCard(profile);
  renderSummaryCard(profile);

  if (dateInput) {
    dateInput.min = todayString();
    selectedDate = clampBookingDate(selectedDate);
    if (dateInput.value !== selectedDate) {
      dateInput.value = selectedDate;
    }
  }
  if (durationSelect && durationSelect.value !== String(selectedDuration)) {
    durationSelect.value = String(selectedDuration);
  }

  if (profile) {
    renderServiceOptions(profile);
    fillSignedInFields(currentState);
    if (!selectedTime) {
      const firstSlot =
        availabilityMatchesSelection(profile) && Array.isArray(selectedAvailability?.slots)
          ? selectedAvailability.slots.find((slot) => slot.available !== false)
          : null;
      if (firstSlot) {
        selectedTime = firstSlot.value;
      }
    }
  }

  renderAvailability(profile);
  renderStaffBookingCalendar(profile);
  syncDurationControls();
  renderSummary(profile);
  renderStaffPromoFeedback(profile);
  renderStaffBookingSteps(profile);

  const status = getBookingStatus();
  if (status) {
    if (profile) {
      const rate = getStaffRateLabel(profile);
      status.textContent = selectedTime
        ? hasContactDetails()
          ? `Ready for checkout with ${profile.name}.`
          : "Enter your name and phone number to continue."
        : `Selected ${profile.name}. ${rate} starting rate. Choose a time to continue.`;
      status.classList.remove("staff-booking-status-error");
    } else {
      status.textContent = "Select a staff member above to start a booking.";
      status.classList.remove("staff-booking-status-error");
    }
  }
}

async function loadAvailabilityForSelectedStaff() {
  const profile = getSelectedStaffProfile();
  if (!profile) {
    availabilityRequestToken += 1;
    selectedAvailability = null;
    selectedTime = "";
    renderStaffBookingShell({ currentUser: state.currentUser });
    return;
  }

  const staffId = String(profile.id);
  const targetDate = clampBookingDate(selectedDate);
  selectedDate = targetDate;
  const requestKey = `${staffId}:${targetDate}`;
  if (lastAvailabilityKey === requestKey && selectedAvailability) {
    renderStaffBookingShell({ currentUser: state.currentUser });
    return;
  }

  const requestToken = availabilityRequestToken + 1;
  availabilityRequestToken = requestToken;
  lastAvailabilityKey = requestKey;
  loadingAvailability = true;
  selectedAvailability = null;
  selectedTime = "";
  setStatus(`Loading openings for ${profile.name}...`);
  renderStaffBookingShell({ currentUser: state.currentUser });

  try {
    const payload = await request(`/api/staff/${staffId}/availability?date=${targetDate}`);
    if (
      requestToken !== availabilityRequestToken ||
      lastAvailabilityKey !== requestKey ||
      selectedDate !== targetDate ||
      String(selectedStaffId) !== staffId
    ) {
      return;
    }

    selectedAvailability = {
      ...payload,
      slots: parseAvailabilitySlots(payload),
    };
    selectedTime = selectedAvailability.slots.find((slot) => slot.available !== false)?.value || "";
    getSelectedDurationMinutes();
    setStatus(`Openings loaded for ${profile.name}.`);
  } catch (error) {
    if (requestToken !== availabilityRequestToken) {
      return;
    }

    selectedAvailability = { slots: [] };
    selectedTime = "";
    setStatus(error.message, true);
  } finally {
    if (requestToken === availabilityRequestToken) {
      loadingAvailability = false;
      renderStaffBookingShell({ currentUser: state.currentUser });
    }
  }
}

async function loadStaffMonthAvailability() {
  const profile = getSelectedStaffProfile();
  if (!profile || !displayedStaffMonth) {
    staffMonthAvailability = {};
    renderStaffBookingShell({ currentUser: state.currentUser });
    return;
  }

  const staffId = String(profile.id);
  const monthValue = displayedStaffMonth;
  const requestToken = staffMonthAvailabilityRequestToken + 1;
  staffMonthAvailabilityRequestToken = requestToken;
  loadingStaffMonth = true;
  staffMonthAvailability = {};
  renderStaffBookingShell({ currentUser: state.currentUser });

  try {
    const payload = await request(`/api/staff/${staffId}/availability/monthly?month=${encodeURIComponent(monthValue.slice(0, 7))}`);
    if (
      requestToken !== staffMonthAvailabilityRequestToken ||
      displayedStaffMonth !== monthValue ||
      String(selectedStaffId) !== staffId
    ) {
      return;
    }
    staffMonthAvailability = payload.days || {};
    setStatus(`Calendar loaded for ${profile.name}.`);
  } catch (error) {
    if (requestToken !== staffMonthAvailabilityRequestToken) {
      return;
    }
    staffMonthAvailability = {};
    setStatus(error.message || "Could not load this staff calendar.", true);
  } finally {
    if (requestToken === staffMonthAvailabilityRequestToken) {
      loadingStaffMonth = false;
      renderStaffBookingShell({ currentUser: state.currentUser });
    }
  }
}

async function selectStaffBooking(staffId, { syncUrl = true, scroll = true } = {}) {
  const nextId = String(staffId || "");
  if (!nextId) {
    return;
  }

  selectedStaffId = nextId;
  selectedTime = "";
  selectedAvailability = null;
  lastAvailabilityKey = "";
  displayedStaffMonth = firstOfMonth(selectedDate);
  staffMonthAvailability = {};
  if (syncUrl) {
    syncSelectionUrl(nextId);
  }
  setStatus("Staff selected. Loading availability...");
  const shell = getBookingShell();
  if (shell) {
    shell.classList.remove("hidden");
  }
  renderStaffBookingShell({ currentUser: state.currentUser });
  if (scroll) {
    shell?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  await Promise.all([loadStaffMonthAvailability(), loadAvailabilityForSelectedStaff()]);
}

function handleTeamGridClick(event) {
  const button = event.target.closest("[data-staff-book], [data-staff-view], [data-staff-book-button], [data-staff-details-button]");
  if (!button) {
    return;
  }

  event.preventDefault();
  const staffId = button.dataset.staffBook || button.dataset.staffView || button.dataset.staffBookButton || button.dataset.staffDetailsButton;
  void selectStaffBooking(staffId);
}

function handleTimeGridClick(event) {
  const button = event.target.closest("[data-staff-time]");
  if (!button) {
    return;
  }

  selectedTime = button.dataset.staffTime || "";
  renderStaffBookingShell({ currentUser: state.currentUser });
}

async function handleBookingSubmit(event) {
  event.preventDefault();

  const profile = getSelectedStaffProfile();
  if (!profile) {
    setStatus("Select a staff member first.", true);
    return;
  }

  const name = getBookingNameInput()?.value.trim() || "";
  const phone = getBookingPhoneInput()?.value.trim() || "";
  const email = getBookingEmailInput()?.value.trim() || "";
  const notes = getBookingNotesInput()?.value.trim() || "";
  const selection = getStaffSelectionValidity(profile);
  const durationMinutes = selection.durationMinutes;
  const serviceType = getBookingServiceSelect()?.value || profile.skills?.[0] || "Creative session";

  if (!selection.valid) {
    setStatus("Choose an available time first.", true);
    renderStaffBookingShell({ currentUser: state.currentUser });
    return;
  }
  if (!name || !phone) {
    setStatus("Enter your name and phone number to continue.", true);
    return;
  }
  if (isDateBeforeToday(selectedDate)) {
    selectedDate = todayString();
    selectedAvailability = null;
    selectedTime = "";
    lastAvailabilityKey = "";
    setStatus("Choose today or a future date.", true);
    renderStaffBookingShell({ currentUser: state.currentUser });
    await loadAvailabilityForSelectedStaff();
    return;
  }

  const payload = {
    staff_profile_id: profile.id,
    service_type: serviceType,
    start_time: buildTimeValue(selection.selectedSlot.value),
    duration_minutes: durationMinutes,
    promo_code: getStaffPromoInputValue() || null,
    guest_name: name,
    guest_phone: phone,
    guest_email: email || null,
    notes: notes || null,
  };

  try {
    setStatus("Creating staff booking...");
    const endpoint = state.token ? "/api/staff-bookings" : "/api/staff-bookings/guest";
    const response = await request(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const booking = response.booking || response;
    const bookingId = booking.id || booking.booking_id || booking.uuid;

    if (!bookingId) {
      throw new Error("The booking service returned no booking id.");
    }

    if (response.access_token) {
      persistToken(response.access_token);
    }

    persistLastBookingId(bookingId);
    persistCheckoutDraft({
      kind: "staff",
      booking,
      staff_profile_id: profile.id,
      staff_profile_name: profile.name,
      selected_date: selectedDate,
      selected_start_time: selectedTime,
      duration_minutes: durationMinutes,
      service_type: serviceType,
      payment_client_secret: response.payment_client_secret || booking.payment_client_secret || null,
    });

    setStatus("Time held — review and confirm your request...");
    window.location.href = `/booking?id=${bookingId}&kind=staff`;
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderStaffCatalogCard(profile) {
  const name = escapeHtml(profile.name || "Team Member");
  const role = escapeHtml(getStaffPrimaryCategory(profile));
  const bio = escapeHtml(profile.description || "Arts Marvels creative professional.");
  const rate = escapeHtml(getStaffRateLabel(profile));
  const skills = (profile.skills || []).slice(0, 3);
  const id = escapeHtml(String(profile.id || ""));
  const photoSrc = profile.photo_url || STAFF_PLACEHOLDER_IMAGE;
  const photoHtml = `<img class="staff-card-photo" src="${escapeHtml(photoSrc)}" alt="${name}" loading="lazy" onerror="this.onerror=null;this.src='${escapeHtml(STAFF_PLACEHOLDER_IMAGE)}';" />`;
  const skillTags = skills.map((s) => `<span class="staff-card-skill-tag">${escapeHtml(s)}</span>`).join("");

  return `
    <article class="staff-card" data-staff-id="${id}" role="button" tabindex="0" aria-label="View profile for ${name}">
      <div class="staff-card-media">
        ${photoHtml}
        <div class="staff-card-badges">
          <span class="staff-card-badge staff-card-badge-role">${role}</span>
          <span class="staff-card-badge staff-card-badge-available">Available</span>
        </div>
      </div>
      <div class="staff-card-content">
        <div class="staff-card-name-row">
          <h3 class="staff-card-name">${name}</h3>
          <span class="staff-card-rating">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
            4.9
          </span>
        </div>
        <p class="staff-card-role">${role}</p>
        <p class="staff-card-bio">${bio}</p>
        <div class="staff-card-skills">${skillTags}</div>
        <div class="staff-card-footer">
          <div class="staff-card-rate">${rate}</div>
          <div class="staff-card-actions">
            <button class="staff-card-view-btn" type="button" data-staff-view="${id}">Profile</button>
            <button class="staff-card-book-btn" type="button" data-staff-book="${id}">Book →</button>
          </div>
        </div>
      </div>
    </article>
  `;
}

// Keep legacy name as alias so any external callers still work
const renderStaffCard = renderStaffCatalogCard;

function initCarousel() {
  const AUTOPLAY_INTERVAL_MS = 6000;
  const carousel = document.querySelector("[data-home-carousel]");
  if (!carousel || carousel.dataset.initialized === "true") {
    return;
  }
  const slides = Array.from(carousel.querySelectorAll("[data-home-slide]"));
  const dotsContainer = carousel.querySelector(".home-carousel-dots");
  if (dotsContainer) {
    dotsContainer.innerHTML = slides
      .map(
        (_, index) =>
          `<button class="home-carousel-dot${index === 0 ? " is-active" : ""}" type="button" data-home-dot aria-current="${index === 0 ? "true" : "false"}"></button>`,
      )
      .join("");
  }
  const dots = Array.from(carousel.querySelectorAll("[data-home-dot]"));
  const previousButton = carousel.querySelector("[data-home-prev]");
  const nextButton = carousel.querySelector("[data-home-next]");
  if (!slides.length) return;
  carousel.dataset.initialized = "true";
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeIndex = Math.max(0, slides.findIndex((s) => s.classList.contains("is-active")));
  let autoPlayTimer = null;
  const clearAutoPlay = () => { if (autoPlayTimer) { window.clearInterval(autoPlayTimer); autoPlayTimer = null; } };
  const normalizeIndex = (i, total) => (!total ? 0 : (i + total) % total);
  const render = (nextIndex, { restartAutoPlay = true } = {}) => {
    activeIndex = normalizeIndex(nextIndex, slides.length);
    slides.forEach((slide, i) => { slide.classList.toggle("is-active", i === activeIndex); slide.setAttribute("aria-hidden", String(i !== activeIndex)); });
    dots.forEach((dot, i) => { dot.classList.toggle("is-active", i === activeIndex); dot.setAttribute("aria-current", i === activeIndex ? "true" : "false"); });
    if (restartAutoPlay) {
      clearAutoPlay();
      if (!prefersReducedMotion.matches) {
        autoPlayTimer = window.setInterval(() => render(activeIndex + 1, { restartAutoPlay: false }), AUTOPLAY_INTERVAL_MS);
      }
    }
  };
  previousButton?.addEventListener("click", () => render(activeIndex - 1));
  nextButton?.addEventListener("click", () => render(activeIndex + 1));
  dots.forEach((dot, i) => dot.addEventListener("click", () => render(i)));
  carousel.addEventListener("mouseenter", clearAutoPlay);
  carousel.addEventListener("mouseleave", () => render(activeIndex));
  carousel.addEventListener("focusin", clearAutoPlay);
  carousel.addEventListener("focusout", (e) => { if (!carousel.contains(e.relatedTarget)) render(activeIndex); });
  document.addEventListener("visibilitychange", () => { document.hidden ? clearAutoPlay() : render(activeIndex); });
  render(activeIndex);
}

export function initStaffDirectoryView() {
  if (viewBound) {
    return;
  }

  viewBound = true;

  initCarousel();
  elements.staffTeamGrid?.addEventListener("click", handleTeamGridClick);
  getStaffSearchInput()?.addEventListener("input", (event) => {
    staffSearchQuery = event.target.value || "";
    renderStaffDirectoryView(state);
  });
  getStaffCategoryBar()?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-staff-role], [data-staff-category]");
    if (!button) {
      return;
    }
    staffCategoryFilter = button.dataset.staffRole || button.dataset.staffCategory || "all";
    renderStaffDirectoryView(state);
  });
  getStaffFilterToggle()?.addEventListener("click", () => {
    getStaffFilterPanel()?.classList.toggle("hidden");
  });
  getStaffSortSelect()?.addEventListener("change", (event) => {
    staffSortMode = event.target.value || "recommended";
    renderStaffDirectoryView(state);
  });
  getTimeGrid()?.addEventListener("click", handleTimeGridClick);
  getStaffBookingMonthGrid()?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-staff-booking-date]");
    if (!button || button.disabled) {
      return;
    }
    selectedDate = clampBookingDate(button.dataset.staffBookingDate || selectedDate);
    selectedAvailability = null;
    selectedTime = "";
    lastAvailabilityKey = "";
    displayedStaffMonth = firstOfMonth(selectedDate);
    renderStaffBookingShell({ currentUser: state.currentUser });
    await loadAvailabilityForSelectedStaff();
  });
  getBookingDateInput()?.addEventListener("change", async (event) => {
    selectedDate = clampBookingDate(event.target.value || selectedDate);
    event.target.value = selectedDate;
    selectedAvailability = null;
    selectedTime = "";
    lastAvailabilityKey = "";
    const nextMonth = firstOfMonth(selectedDate);
    const monthChanged = nextMonth !== displayedStaffMonth;
    displayedStaffMonth = nextMonth;
    renderStaffBookingShell({ currentUser: state.currentUser });
    await Promise.all([
      loadAvailabilityForSelectedStaff(),
      monthChanged ? loadStaffMonthAvailability() : Promise.resolve(),
    ]);
  });
  getStaffBookingPrevMonth()?.addEventListener("click", async () => {
    if (!getSelectedStaffProfile() || !displayedStaffMonth) {
      return;
    }
    const date = new Date(`${displayedStaffMonth}T00:00:00`);
    date.setMonth(date.getMonth() - 1);
    const previousMonth = `${date.toISOString().slice(0, 7)}-01`;
    displayedStaffMonth = previousMonth < firstOfMonth(todayString()) ? firstOfMonth(todayString()) : previousMonth;
    renderStaffBookingShell({ currentUser: state.currentUser });
    await loadStaffMonthAvailability();
  });
  getStaffBookingNextMonth()?.addEventListener("click", async () => {
    if (!getSelectedStaffProfile() || !displayedStaffMonth) {
      return;
    }
    const date = new Date(`${displayedStaffMonth}T00:00:00`);
    date.setMonth(date.getMonth() + 1);
    displayedStaffMonth = `${date.toISOString().slice(0, 7)}-01`;
    renderStaffBookingShell({ currentUser: state.currentUser });
    await loadStaffMonthAvailability();
  });
  getBookingDurationSelect()?.addEventListener("change", () => {
    selectedDuration = Number(getBookingDurationSelect()?.value || 60);
    renderStaffBookingShell({ currentUser: state.currentUser });
  });
  getDurationDecreaseButton()?.addEventListener("click", () => {
    const allowedDurations = getAllowedStaffDurations();
    const currentIndex = allowedDurations.indexOf(getSelectedDurationMinutes());
    selectedDuration = allowedDurations[Math.max(0, currentIndex - 1)] || selectedDuration;
    renderStaffBookingShell({ currentUser: state.currentUser });
  });
  getDurationIncreaseButton()?.addEventListener("click", () => {
    const allowedDurations = getAllowedStaffDurations();
    const currentIndex = allowedDurations.indexOf(getSelectedDurationMinutes());
    selectedDuration = allowedDurations[Math.min(allowedDurations.length - 1, currentIndex + 1)] || selectedDuration;
    renderStaffBookingShell({ currentUser: state.currentUser });
  });
  getBookingServiceSelect()?.addEventListener("change", () => {
    renderStaffBookingShell({ currentUser: state.currentUser });
  });
  getStaffPromoPreviewButton()?.addEventListener("click", async () => {
    await applyStaffPromoPreview();
  });
  getStaffPromoCodeInput()?.addEventListener("input", () => {
    if (!getStaffPromoInputValue()) {
      clearStaffPromoState();
    } else if (staffPromoPreview && staffPromoPreview.code !== getStaffPromoInputValue()) {
      clearStaffPromoState();
    }
    renderStaffBookingShell({ currentUser: state.currentUser });
  });
  [getBookingNameInput(), getBookingPhoneInput(), getBookingEmailInput(), getBookingNotesInput()]
    .filter(Boolean)
    .forEach((input) => {
      input.addEventListener("input", () => {
        renderStaffBookingShell({ currentUser: state.currentUser });
      });
    });
  getBookingForm()?.addEventListener("submit", handleBookingSubmit);

  const initialProfileId = selectedStaffId;
  if (initialProfileId && staffProfilesCache.some((profile) => String(profile.id) === String(initialProfileId))) {
    void selectStaffBooking(initialProfileId, { syncUrl: false, scroll: false });
  }
}

function getBookingForm() {
  return document.getElementById("staff-booking-form");
}

function renderBookingSection(currentState) {
  const profile = getSelectedStaffProfile();
  const paramStaffId = getSearchParam("staff_id");

  if (!selectedStaffId && paramStaffId && currentState.publicStaffProfiles?.some((item) => String(item.id) === String(paramStaffId))) {
    selectedStaffId = String(paramStaffId);
    lastAvailabilityKey = "";
  }

  if (selectedStaffId && !profile && currentState.publicStaffProfiles?.length) {
    const exists = currentState.publicStaffProfiles.some((item) => String(item.id) === String(selectedStaffId));
    if (!exists) {
      selectedStaffId = "";
      selectedAvailability = null;
      selectedTime = "";
      lastAvailabilityKey = "";
    }
  }

  if (profile && !selectedAvailability && !loadingAvailability) {
    void loadAvailabilityForSelectedStaff();
  }
  if (profile && !loadingStaffMonth && !Object.keys(staffMonthAvailability).length) {
    void loadStaffMonthAvailability();
  }

  renderStaffBookingShell(currentState);
}

function renderStaffCatalog(allProfiles) {
  const grid = elements.staffTeamGrid;
  if (!grid) return;
  const profiles = (allProfiles || staffProfilesCache).filter((profile) => profile?.active !== false);
  const visibleProfiles = getVisibleStaffProfiles(profiles);
  const resultsCount = getStaffResultsCount();
  if (resultsCount) {
    resultsCount.textContent = `${visibleProfiles.length} staff member${visibleProfiles.length === 1 ? "" : "s"} found`;
  }
  grid.innerHTML = visibleProfiles.length
    ? visibleProfiles.map(renderStaffCatalogCard).join("")
    : '<div class="empty-state">No staff matched those filters. Clear search or choose another specialty.</div>';
}

export function renderStaffDirectoryView(currentState) {
  staffProfilesCache = currentState.publicStaffProfiles || [];

  if (elements.staffTeamGrid) {
    const profiles = staffProfilesCache.filter((profile) => profile?.active !== false);
    renderStaffCategoryBar(profiles);
    renderStaffCatalog(profiles);
  }

  if (selectedStaffId && !staffProfilesCache.some((profile) => String(profile.id) === String(selectedStaffId))) {
    selectedStaffId = "";
    selectedAvailability = null;
    selectedTime = "";
    lastAvailabilityKey = "";
  }

  if (!viewBound) {
    initStaffDirectoryView();
  }

  renderBookingSection(currentState);
}
