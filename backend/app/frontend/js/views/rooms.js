import { api } from "../api.js";
import { elements } from "../dom.js";
import { setState, state } from "../state.js";

let editingRoomId = null;
let selectedCreateStaffIds = new Set();
let roomsViewBound = false;
let selectedRoomCategory = "all";
let roomsCatalogSort = "recommended";
let pendingUrlSearch = false;

const ROOM_CATEGORY_ORDER = [
  "all",
  "recording",
  "podcast",
  "production",
  "photography",
  "dance",
  "film",
];

const ROOM_CATEGORY_LABELS = {
  all: "All",
  recording: "Recording",
  podcast: "Podcast",
  production: "Production",
  photography: "Photography",
  dance: "Dance",
  film: "Film",
};

const ROOM_CATEGORY_RATINGS = {
  recording: 4.9,
  podcast: 4.8,
  production: 5.0,
  photography: 4.7,
  dance: 4.6,
  film: 4.9,
};

const ROOM_CATEGORY_VISUALS = {
  recording: "/assets/media/studio-room-2.png",
  podcast: "/assets/media/studio-lobby-2.png",
  production: "/assets/media/studio-room-2.png",
  photography: "/assets/media/studio-room-2.png",
  dance: "/assets/media/studio-exterior-2.png",
  film: "/assets/media/studio-exterior-2.png",
};

function roomsSearchTextInput() {
  return document.getElementById("rooms-search-text");
}

function roomsSortSelect() {
  return document.getElementById("rooms-sort-select");
}

function roomsCategoryBar() {
  return document.getElementById("rooms-category-bar");
}

function roomsResultsCount() {
  return document.getElementById("rooms-results-count");
}

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-US", {
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

function formatPreviewTimes(availableStartTimes) {
  return availableStartTimes.slice(0, 4).map((startTime) =>
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(startTime)),
  );
}

function extractStudioTime(startTime) {
  const match = String(startTime || "").match(/T(\d{2}:\d{2})/);
  return match ? match[1] : "";
}

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function formatSearchDateLabel(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-CA", { weekday: "short", month: "short", day: "numeric" })
    .format(new Date(`${value}T00:00:00`));
}

function formatSearchTimeLabel(value) {
  if (!value) return "";
  const [h, m] = String(value).split(":").map(Number);
  const date = new Date();
  date.setHours(h || 0, m || 0, 0, 0);
  return new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit" }).format(date);
}

const STUDIO_CLOSED_WEEKDAYS = new Set([0, 1, 2]); // Sun, Mon, Tue
const STUDIO_CLOSE_HOUR = 20;
const CLOSED_WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday"];

function getWeekdayForIsoDate(value) {
  if (!value) return null;
  const [y, mo, d] = value.split("-").map(Number);
  if (!y || !mo || !d) return null;
  return new Date(y, mo - 1, d).getDay();
}

function isPastIsoDate(value) {
  if (!value) return false;
  const today = availCalTodayLocal();
  return value < today;
}

function maxDurationMinutesForStartTime(startTime) {
  if (!startTime) return 300;
  const [h] = String(startTime).split(":").map(Number);
  if (Number.isNaN(h)) return 300;
  const hoursUntilClose = Math.max(0, STUDIO_CLOSE_HOUR - h);
  return Math.min(300, Math.max(60, hoursUntilClose * 60));
}

function getPrimaryPhoto(room) {
  return Array.isArray(room.photos) && room.photos.length ? room.photos[0] : null;
}

function isAdminPage() {
  return document.body?.dataset.page === "admin";
}

function getRoomCategory(room) {
  const haystack = `${room.name || ""} ${room.description || ""}`.toLowerCase();
  if (haystack.includes("podcast")) {
    return "podcast";
  }
  if (haystack.includes("production")) {
    return "production";
  }
  if (haystack.includes("photo")) {
    return "photography";
  }
  if (haystack.includes("dance")) {
    return "dance";
  }
  if (haystack.includes("film") || haystack.includes("video")) {
    return "film";
  }
  return "recording";
}

function getRoomRating(room) {
  return ROOM_CATEGORY_RATINGS[getRoomCategory(room)] || 4.8;
}

function getRoomVisual(room) {
  const category = getRoomCategory(room);
  const photo = getPrimaryPhoto(room);
  const fallback = ROOM_CATEGORY_VISUALS[category] || "/assets/media/studio-room-2.png";
  if (!photo || String(photo).includes("/assets/media/rooms/")) {
    return { photo: fallback, fallback, category };
  }
  return { photo, fallback, category };
}

function getRoomSearchText(room) {
  return `${room.name || ""} ${room.description || ""} ${ROOM_CATEGORY_LABELS[getRoomCategory(room)] || ""}`.toLowerCase();
}

function formatRoomCategoryLabel(category) {
  return ROOM_CATEGORY_LABELS[category] || "Studio";
}

function formatCompactCurrency(cents) {
  return formatCurrency(cents).replace(".00", "");
}

function formatRoomCount(count) {
  return `${count} studio${count === 1 ? "" : "s"} found`;
}

function formatRoomDescription(room) {
  const description = String(room.description || "").trim();
  if (!description) {
    return "A flexible studio space ready for your next session.";
  }
  return description.length > 132 ? `${description.slice(0, 129).trim()}...` : description;
}

function renderCategoryFilterBar(rooms) {
  const target = roomsCategoryBar();
  if (!target) {
    return;
  }

  const availableCategories = new Set((rooms || []).map(getRoomCategory));
  const categories = ROOM_CATEGORY_ORDER.filter((category) => category === "all" || availableCategories.has(category));
  if (selectedRoomCategory !== "all" && !availableCategories.has(selectedRoomCategory)) {
    selectedRoomCategory = "all";
  }

  target.innerHTML = categories.map(
    (category) => `
      <button
        class="rooms-category-chip ${selectedRoomCategory === category ? "is-active" : ""}"
        type="button"
        data-room-category="${escapeHtml(category)}"
      >
        ${escapeHtml(formatRoomCategoryLabel(category))}
      </button>
    `,
  ).join("");
}

function getRoomPhotoUrlInput() {
  return elements.roomForm?.querySelector("#room-photo-url");
}

function getRoomPhotoFileInput() {
  return elements.roomForm?.querySelector("#room-photo-file");
}

function getRoomPhotoPreview() {
  return elements.roomForm?.querySelector("#room-photo-preview");
}

function setRoomPhotoPreview(photoUrl, roomName = "Room") {
  const preview = getRoomPhotoPreview();
  if (!preview) {
    return;
  }

  if (!photoUrl) {
    preview.classList.add("empty-state");
    preview.innerHTML = "Upload a JPG photo to show this room across booking and room detail pages.";
    return;
  }

  preview.classList.remove("empty-state");
  const safePhotoUrl = escapeHtml(photoUrl);
  const safeRoomName = escapeHtml(roomName);
  preview.innerHTML = `
    <div class="staff-photo-preview-card">
      <img class="staff-photo-preview-image" src="${safePhotoUrl}" alt="${safeRoomName}" loading="lazy" />
      <div class="staff-option-copy">
        <strong>${safeRoomName}</strong>
        <span>This image will appear as the primary room photo.</span>
      </div>
    </div>
  `;
}

function resetRoomForm() {
  editingRoomId = null;
  selectedCreateStaffIds = new Set();
  elements.roomForm?.reset();
  if (elements.roomFormId) {
    elements.roomFormId.value = "";
  }
  if (elements.roomFormTitle) {
    elements.roomFormTitle.textContent = "Create room";
  }
  if (elements.roomFormSubmit) {
    elements.roomFormSubmit.textContent = "Create room";
  }
  if (elements.roomFormCancel) {
    elements.roomFormCancel.textContent = isAdminPage() ? "Close" : "Cancel edit";
    elements.roomFormCancel.classList.toggle("hidden", !isAdminPage());
  }
  if (elements.roomForm?.elements?.hourly_rate_cents) {
    elements.roomForm.elements.hourly_rate_cents.value = "5000";
  }
  if (elements.roomForm?.elements?.max_booking_duration_minutes) {
    elements.roomForm.elements.max_booking_duration_minutes.value = "300";
  }
  if (elements.roomForm?.elements?.status) {
    elements.roomForm.elements.status.value = "available";
  }
  const roomPhotoUrlInput = getRoomPhotoUrlInput();
  if (roomPhotoUrlInput) {
    roomPhotoUrlInput.value = "";
  }
  setRoomPhotoPreview(null);
}

function populateRoomForm(room) {
  if (!elements.roomForm) {
    return;
  }

  editingRoomId = String(room.id);
  selectedCreateStaffIds = new Set((room.staff_roles || []).map((role) => String(role.id)));
  if (elements.roomFormId) {
    elements.roomFormId.value = editingRoomId;
  }
  elements.roomForm.elements.name.value = room.name || "";
  elements.roomForm.elements.description.value = room.description || "";
  elements.roomForm.elements.capacity.value = room.capacity || "";
  const roomPhotos = Array.isArray(room.photos) ? room.photos : [];
  const primaryPhoto = roomPhotos[0] || "";
  elements.roomForm.elements.photos.value = roomPhotos.slice(1).join("\n");
  elements.roomForm.elements.hourly_rate_cents.value = room.hourly_rate_cents || 5000;
  elements.roomForm.elements.max_booking_duration_minutes.value = room.max_booking_duration_minutes || 300;
  if (elements.roomForm.elements.status) {
    elements.roomForm.elements.status.value = room.status || "available";
  }
  const roomPhotoUrlInput = getRoomPhotoUrlInput();
  if (roomPhotoUrlInput) {
    roomPhotoUrlInput.value = primaryPhoto;
  }
  setRoomPhotoPreview(primaryPhoto || null, room.name || "Room");
  if (elements.roomFormTitle) {
    elements.roomFormTitle.textContent = `Edit ${room.name}`;
  }
  if (elements.roomFormSubmit) {
    elements.roomFormSubmit.textContent = "Save room changes";
  }
  elements.roomFormCancel?.classList.remove("hidden");
}

function renderCreateRoomStaffOptions(currentState) {
  if (!elements.adminRoomCreateStaffSection || !elements.adminRoomCreateStaffOptions) {
    return;
  }

  const profiles = (currentState.adminStaffProfiles || []).filter(
    (profile) => profile.active || selectedCreateStaffIds.has(String(profile.id)),
  );
  if (!profiles.length) {
    selectedCreateStaffIds = new Set();
    elements.adminRoomCreateStaffOptions.innerHTML =
      '<div class="empty-state">Create staff profiles first, then select them here while creating a room.</div>';
    return;
  }

  elements.adminRoomCreateStaffOptions.innerHTML = profiles
    .map(
      (profile) => `
        <label class="staff-option-card staff-option-card-compact">
          <div class="staff-option-toggle">
            <input type="checkbox" value="${escapeHtml(profile.id)}" ${selectedCreateStaffIds.has(String(profile.id)) ? "checked" : ""} />
          </div>
          <div class="staff-option-copy">
            <strong>${escapeHtml(profile.name)}</strong>
            <span>${escapeHtml(profile.description || "Optional staff support for this room.")}</span>
          </div>
          <strong class="staff-option-price">${formatCurrency(profile.add_on_price_cents)}</strong>
        </label>
      `,
    )
    .join("");
}

function collectCreateRoomStaffPayload() {
  const profilesById = new Map(
    (state.adminStaffProfiles || []).map((profile) => [String(profile.id), profile]),
  );

  return Array.from(selectedCreateStaffIds).flatMap((staffProfileId) => {
    const profile = profilesById.get(staffProfileId);
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

function renderAvailabilityPreview(roomId) {
  const preview = state.roomAvailabilityPreview?.[roomId];
  if (!preview) {
    return `
      <div class="availability-preview availability-preview-idle">
        <span class="availability-label">Live openings</span>
        <p>Use the "When?" picker above to see this room's openings for a specific day.</p>
      </div>
    `;
  }

  if (!preview.available_start_times.length) {
    return `
      <div class="availability-preview">
        <span class="availability-label">Availability preview</span>
        <p>No live openings were returned for ${escapeHtml(preview.date)}. Try another date or open the booking flow for a different room.</p>
      </div>
    `;
  }

  const previewTimes = formatPreviewTimes(preview.available_start_times)
    .map((label) => `<span class="pill">${escapeHtml(label)}</span>`)
    .join("");
  return `
    <div class="availability-preview">
      <span class="availability-label">${preview.available_start_times.length} starts open on ${escapeHtml(preview.date)}</span>
      <p>Times are shown in local studio time and update from the live availability feed.</p>
      <div class="preview-pill-row">${previewTimes}</div>
    </div>
  `;
}

const ROOM_STATUS_LABELS = {
  available: "Available",
  in_progress: "In Progress",
  tbc: "TBC",
};

function getRoomStatusLabel(room) {
  if (!room.active && !room.coming_soon) return "Inactive";
  if (room.coming_soon && !room.active) return "Coming Soon";
  return ROOM_STATUS_LABELS[room.status] || "Available";
}

function getRoomStatusPillClass(room) {
  if (!room.active && !room.coming_soon) return "is-booked";
  if (room.coming_soon && !room.active) return "is-coming-soon";
  const map = { available: "is-available", in_progress: "is-in-progress", tbc: "is-tbc" };
  return map[room.status] || "is-available";
}

function renderRoomCard(room, canManageRooms) {
  const { photo: primaryPhoto, fallback, category } = getRoomVisual(room);
  const categoryLabel = formatRoomCategoryLabel(category);
  const statusLabel = getRoomStatusLabel(room);
  const rating = getRoomRating(room);
  const safeRoomId = escapeHtml(room.id);
  const safeRoomName = escapeHtml(room.name);
  const safePrimaryPhoto = escapeHtml(primaryPhoto);
  const safeFallback = escapeHtml(fallback);
  const safeCategoryLabel = escapeHtml(categoryLabel);
  const safeDescription = escapeHtml(formatRoomDescription(room));
  const canEditRoom = canManageRooms && Boolean(elements.roomForm);
  const isComingSoon = Boolean(room.coming_soon) && !room.active;

  if (canManageRooms && isAdminPage()) {
    const managementActions = [
      canEditRoom
        ? `<button class="admin-icon-button" type="button" data-room-action="edit" data-room-id="${safeRoomId}" aria-label="Edit ${safeRoomName}">✎</button>`
        : "",
      room.active
        ? `<button class="admin-icon-button" type="button" data-room-action="archive" data-room-id="${safeRoomId}" aria-label="Archive ${safeRoomName}">◌</button>`
        : `<button class="admin-icon-button" type="button" data-room-action="restore" data-room-id="${safeRoomId}" aria-label="Restore ${safeRoomName}">↻</button>`,
      `<button class="admin-icon-button is-danger" type="button" data-room-action="delete" data-room-id="${safeRoomId}" data-room-name="${safeRoomName}" aria-label="Delete ${safeRoomName}">⌫</button>`,
    ].filter(Boolean).join("");

    return `
      <article class="admin-studio-row">
        <div class="admin-studio-thumb">
          ${
            primaryPhoto
              ? `<img src="${safePrimaryPhoto}" alt="${safeRoomName}" loading="lazy" onerror="this.onerror=null;this.src='${safeFallback}';" />`
              : '<span>No image</span>'
          }
        </div>
        <div class="admin-studio-main">
          <div class="admin-studio-title-row">
            <h3>${safeRoomName}</h3>
            <span class="pill">${safeCategoryLabel}</span>
            ${room.active
              ? `<span class="pill room-status-pill ${getRoomStatusPillClass(room)}">${escapeHtml(getRoomStatusLabel(room))}</span>`
              : isComingSoon
                ? '<span class="pill status-pending">Coming Soon</span>'
                : '<span class="pill status-cancelled">Unavailable</span>'
            }
          </div>
          <p>${formatCompactCurrency(room.hourly_rate_cents)}/hr · capacity ${escapeHtml(room.capacity || "n/a")} · ★ ${rating.toFixed(1).replace(".0", "")}</p>
        </div>
        <div class="admin-studio-actions">
          ${managementActions}
        </div>
      </article>
    `;
  }

  const managementActions = canManageRooms
    ? [
        canEditRoom
          ? `<button class="ghost-button room-action" type="button" data-room-action="edit" data-room-id="${safeRoomId}">Edit</button>`
          : "",
        room.active
          ? `<button class="ghost-button room-action" type="button" data-room-action="archive" data-room-id="${safeRoomId}">Archive</button>`
          : `<button class="ghost-button room-action" type="button" data-room-action="restore" data-room-id="${safeRoomId}">Restore</button>`,
        `<button class="ghost-button room-action" type="button" data-room-action="delete" data-room-id="${safeRoomId}" data-room-name="${safeRoomName}">Delete room</button>`,
      ].filter(Boolean).join("")
    : "";

  const statusPillClass = getRoomStatusPillClass(room);
  const featureRowStatus = room.active ? (ROOM_STATUS_LABELS[room.status] || "Bookable now") : isComingSoon ? "Opening soon" : "Inactive";

  return `
    <article class="room-card room-catalog-card${isComingSoon ? " is-coming-soon" : ""}">
      <div class="room-catalog-media">
        ${
          primaryPhoto
            ? `<img class="room-card-image" src="${safePrimaryPhoto}" alt="${safeRoomName}" loading="lazy" onerror="this.onerror=null;this.src='${safeFallback}';" />`
            : '<div class="room-card-placeholder">No room image yet.</div>'
        }
        <div class="room-catalog-media-badges">
          <span class="room-catalog-pill room-catalog-pill-category">${safeCategoryLabel}</span>
          <span class="room-catalog-pill room-catalog-pill-status ${statusPillClass}">${escapeHtml(statusLabel)}</span>
        </div>
      </div>
      <div class="room-catalog-content">
        <div class="room-catalog-title-row">
          <h3 class="room-catalog-title ${category === "podcast" ? "is-accent" : ""}">${safeRoomName}</h3>
          <span class="room-catalog-rating"><span aria-hidden="true">★</span> ${rating.toFixed(1).replace(".0", "")}</span>
        </div>
        <p class="room-catalog-description">${safeDescription}</p>
        <div class="room-catalog-feature-row" aria-label="Room highlights">
          <span>${safeCategoryLabel}</span>
          <span>${formatDuration(room.max_booking_duration_minutes || 300)} max</span>
          <span>${featureRowStatus}</span>
        </div>
        ${room.active ? renderAvailabilityPreview(room.id) : ""}
        <div class="room-catalog-meta-row">
          <span class="room-catalog-capacity">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <circle cx="7" cy="7" r="2.2"></circle>
              <path d="M2.8 15.2c.8-2.3 2.6-3.5 4.2-3.5s3.4 1.2 4.2 3.5"></path>
              <circle cx="14.1" cy="8" r="1.8"></circle>
              <path d="M11.8 15c.5-1.6 1.9-2.7 3.4-2.7 1 0 2 .5 2.8 1.5"></path>
            </svg>
            Up to ${escapeHtml(room.capacity || "n/a")}
          </span>
          <strong class="room-catalog-price">${formatCompactCurrency(room.hourly_rate_cents)}<span>/hr</span></strong>
        </div>
        <div class="room-actions room-catalog-actions">
          ${
            room.active
              ? `<a class="primary-button room-catalog-book-button" href="/reserve?id=${safeRoomId}">Book now</a>
                 <a class="ghost-button room-catalog-details-button" href="/room?id=${safeRoomId}">View details</a>`
              : isComingSoon
                ? `<span class="ghost-button room-catalog-coming-soon-label" aria-disabled="true">Coming Soon</span>
                   <a class="ghost-button room-catalog-details-button" href="/room?id=${safeRoomId}">Learn more</a>`
                : ""
          }
        </div>
      </div>
      ${
        managementActions
          ? `<div class="room-actions room-actions-admin">${managementActions}</div>`
          : ""
      }
    </article>
  `;
}

async function searchRoomsByAvailability() {
  const searchDate = elements.roomsSearchDate?.value;
  const searchTime = elements.roomsSearchTime?.value;
  const duration = Number(elements.roomsSearchDuration?.value || 60);
  if (!searchDate || !searchTime) {
    setState({ message: "Choose a date and start time to search for rooms." });
    return;
  }
  if (isPastIsoDate(searchDate)) {
    setState({ message: "That date has already passed. Pick a future date." });
    return;
  }
  const weekday = getWeekdayForIsoDate(searchDate);
  if (weekday !== null && STUDIO_CLOSED_WEEKDAYS.has(weekday)) {
    setState({
      message: `The studio is closed on ${CLOSED_WEEKDAY_NAMES[weekday]}. Pick a Wednesday through Saturday.`,
    });
    return;
  }
  if (searchTime < "12:00" || searchTime > "19:00") {
    setState({ message: "Choose a start time between 12:00 PM and 7:00 PM." });
    return;
  }
  const maxDuration = maxDurationMinutesForStartTime(searchTime);
  if (duration > maxDuration) {
    setState({
      message: `A ${formatDuration(duration)} session starting at ${formatSearchTimeLabel(searchTime)} would run past 8:00 PM. Shorten the duration or pick an earlier start time.`,
    });
    return;
  }

  try {
    setState({ message: "Searching rooms for that exact time..." });
    const availabilityRows = await Promise.all(
      state.rooms
        .filter((room) => room.active)
        .map(async (room) => [room.id, await api.getAvailability(room.id, searchDate)]),
    );
    const matchingRoomIds = availabilityRows
      .filter(([, availability]) =>
        (availability.available_start_times || []).some(
          (startTime) =>
            extractStudioTime(startTime) === searchTime &&
            Number(availability.max_duration_minutes_by_start?.[startTime] || 0) >= duration,
        ),
      )
      .map(([roomId]) => String(roomId));

    setState({
      roomAvailabilitySearch: {
        date: searchDate,
        time: searchTime,
        duration,
        matchingRoomIds,
        hasSearched: true,
      },
      roomPreviewDate: searchDate,
      roomAvailabilityPreview: Object.fromEntries(availabilityRows),
      message: matchingRoomIds.length
        ? `Found ${matchingRoomIds.length} matching room${matchingRoomIds.length === 1 ? "" : "s"}.`
        : "No rooms matched that time.",
    });
  } catch (error) {
    setState({ message: error.message });
  }
}

function clearRoomAvailabilitySearch() {
  setState({
    roomAvailabilitySearch: {
      date: elements.roomsSearchDate?.value || state.roomAvailabilitySearch.date,
      time: elements.roomsSearchTime?.value || "15:00",
      duration: Number(elements.roomsSearchDuration?.value || 60),
      matchingRoomIds: [],
      hasSearched: false,
    },
    message: "Room search cleared.",
  });
}

function openRoomsWhenBar() {
  const bar = document.getElementById("rooms-when-bar");
  const btn = document.getElementById("rooms-when-toggle");
  if (!bar || !btn) return;
  bar.classList.remove("hidden");
  btn.classList.add("is-open");
  btn.setAttribute("aria-expanded", "true");
}

function closeRoomsWhenBar() {
  const bar = document.getElementById("rooms-when-bar");
  const btn = document.getElementById("rooms-when-toggle");
  if (!bar || !btn) return;
  bar.classList.add("hidden");
  btn.classList.remove("is-open");
  btn.setAttribute("aria-expanded", "false");
}

function renderRoomsWhenToggleChip(currentState) {
  const btn = document.getElementById("rooms-when-toggle");
  const chip = document.getElementById("rooms-when-toggle-chip");
  if (!btn || !chip) return;
  const search = currentState.roomAvailabilitySearch;
  if (!search?.hasSearched) {
    chip.classList.add("hidden");
    chip.textContent = "";
    btn.classList.remove("is-active");
    return;
  }
  chip.classList.remove("hidden");
  chip.textContent = `${formatSearchDateLabel(search.date)} · ${formatSearchTimeLabel(search.time)} · ${formatDuration(search.duration)}`;
  btn.classList.add("is-active");
}

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
          `<button class="home-carousel-dot${index === 0 ? " is-active" : ""}" type="button" data-home-dot aria-current="${
            index === 0 ? "true" : "false"
          }"></button>`,
      )
      .join("");
  }
  const dots = Array.from(carousel.querySelectorAll("[data-home-dot]"));
  const previousButton = carousel.querySelector("[data-home-prev]");
  const nextButton = carousel.querySelector("[data-home-next]");

  if (!slides.length) {
    return;
  }

  carousel.dataset.initialized = "true";

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeIndex = slides.findIndex((slide) => slide.classList.contains("is-active"));
  let autoPlayTimer = null;

  if (activeIndex < 0) {
    activeIndex = 0;
  }

  const clearAutoPlay = () => {
    if (autoPlayTimer) {
      window.clearInterval(autoPlayTimer);
      autoPlayTimer = null;
    }
  };

  const normalizeIndex = (index, total) => {
    if (!total) {
      return 0;
    }
    return (index + total) % total;
  };

  const render = (nextIndex, { restartAutoPlay = true } = {}) => {
    activeIndex = normalizeIndex(nextIndex, slides.length);

    slides.forEach((slide, index) => {
      const isActive = index === activeIndex;
      slide.classList.toggle("is-active", isActive);
      slide.setAttribute("aria-hidden", String(!isActive));
    });

    dots.forEach((dot, index) => {
      const isActive = index === activeIndex;
      dot.classList.toggle("is-active", isActive);
      dot.setAttribute("aria-current", isActive ? "true" : "false");
    });

    if (restartAutoPlay) {
      clearAutoPlay();
      if (!prefersReducedMotion.matches) {
        autoPlayTimer = window.setInterval(() => {
          render(activeIndex + 1, { restartAutoPlay: false });
        }, AUTOPLAY_INTERVAL_MS);
      }
    }
  };

  const moveBy = (offset) => {
    render(activeIndex + offset);
  };

  previousButton?.addEventListener("click", () => moveBy(-1));
  nextButton?.addEventListener("click", () => moveBy(1));

  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => render(index));
  });

  const pauseAutoPlay = () => {
    clearAutoPlay();
  };

  const resumeAutoPlay = () => {
    render(activeIndex);
  };

  carousel.addEventListener("mouseenter", pauseAutoPlay);
  carousel.addEventListener("mouseleave", resumeAutoPlay);
  carousel.addEventListener("focusin", pauseAutoPlay);
  carousel.addEventListener("focusout", (event) => {
    if (!carousel.contains(event.relatedTarget)) {
      resumeAutoPlay();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      pauseAutoPlay();
      return;
    }
    resumeAutoPlay();
  });

  render(activeIndex);
}

// ---------------------------------------------------------------------------
// Public availability calendar
// ---------------------------------------------------------------------------

let availCalMonth = (() => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
})();
let availCalData = null;
let availCalBound = false;

function availCalHeadingEl() { return document.getElementById("avail-cal-heading"); }
function availCalCellsEl() { return document.getElementById("avail-cal-cells"); }
function availCalPrevBtn() { return document.getElementById("avail-cal-prev"); }
function availCalNextBtn() { return document.getElementById("avail-cal-next"); }

function availCalFormatHeading(month) {
  return new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" })
    .format(new Date(`${month}-01T12:00:00`));
}

function availCalOffsetMonth(month, delta) {
  const [year, mon] = month.split("-").map(Number);
  const d = new Date(year, mon - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function availCalTodayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function availCalMonthDayCount(month) {
  const [year, mon] = month.split("-").map(Number);
  return new Date(year, mon, 0).getDate();
}

function availCalStartOffset(month) {
  const [year, mon] = month.split("-").map(Number);
  return new Date(year, mon - 1, 1).getDay();
}

async function availCalLoad() {
  const heading = availCalHeadingEl();
  const cells = availCalCellsEl();
  if (!heading || !cells) return;

  heading.textContent = availCalFormatHeading(availCalMonth);
  cells.innerHTML = '<div class="avail-cal-loading">Loading…</div>';

  try {
    availCalData = await api.getMonthlyAvailability(availCalMonth);
    availCalRender();
  } catch {
    cells.innerHTML = '<div class="avail-cal-loading">Could not load availability.</div>';
  }
}

function availCalRender() {
  const cells = availCalCellsEl();
  if (!cells || !availCalData) return;

  const offset = availCalStartOffset(availCalMonth);
  const dayCount = availCalMonthDayCount(availCalMonth);
  const today = availCalTodayLocal();
  const days = availCalData.days || {};

  const spacers = Array.from({ length: offset }, () =>
    '<div class="avail-cal-spacer" aria-hidden="true"></div>'
  );

  const dayCells = Array.from({ length: dayCount }, (_, i) => {
    const dayNum = i + 1;
    const dateKey = `${availCalMonth}-${String(dayNum).padStart(2, "0")}`;
    const info = days[dateKey] || { status: "closed" };
    const isToday = dateKey === today;
    const isPast = info.status === "past";
    const isClosed = info.status === "closed";
    const isClickable = !isPast && !isClosed && info.status !== "full";

    const classes = ["avail-cal-day", `is-${info.status}`];
    if (isToday) classes.push("is-today");

    const label = info.status === "available"
      ? `${info.open_rooms} studio${info.open_rooms === 1 ? "" : "s"} open`
      : info.status === "limited"
        ? `${info.open_rooms} of ${info.total_rooms} open`
        : info.status === "full"
          ? "Fully booked"
          : info.status === "past"
            ? ""
            : "Closed";

    if (isClickable) {
      return `
        <button class="${classes.join(" ")}" type="button" data-avail-date="${dateKey}" title="${label}">
          <strong>${dayNum}</strong>
          <span>${label}</span>
        </button>`;
    }
    return `
      <div class="${classes.join(" ")}" aria-hidden="${isClosed || isPast ? "true" : "false"}">
        <strong>${dayNum}</strong>
        ${!isClosed && !isPast ? `<span>${label}</span>` : ""}
      </div>`;
  });

  cells.innerHTML = [...spacers, ...dayCells].join("");
}

function availCalPickDate(dateKey) {
  if (elements.roomsSearchDate) elements.roomsSearchDate.value = dateKey;
  // Calendar click triggers a search; collapsed-by-default When bar stays
  // closed — the active-filter chip on the toggle reflects the result.
  searchRoomsByAvailability();
}

function initAvailCal() {
  if (availCalBound) return;
  availCalBound = true;

  availCalPrevBtn()?.addEventListener("click", () => {
    const today = availCalTodayLocal();
    const currentMonth = today.slice(0, 7);
    if (availCalMonth <= currentMonth) return;
    availCalMonth = availCalOffsetMonth(availCalMonth, -1);
    availCalHeadingEl().textContent = availCalFormatHeading(availCalMonth);
    availCalLoad();
  });

  availCalNextBtn()?.addEventListener("click", () => {
    availCalMonth = availCalOffsetMonth(availCalMonth, 1);
    availCalHeadingEl().textContent = availCalFormatHeading(availCalMonth);
    availCalLoad();
  });

  availCalCellsEl()?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-avail-date]");
    if (btn) availCalPickDate(btn.dataset.availDate);
  });

  availCalLoad();
}

export function initRoomsView(actions) {
  const urlParams = new URLSearchParams(window.location.search);
  const urlDate = urlParams.get("date");
  const urlTime = urlParams.get("time");
  if (urlDate && !pendingUrlSearch) {
    if (elements.roomsSearchDate) elements.roomsSearchDate.value = urlDate;
    if (urlTime && elements.roomsSearchTime) elements.roomsSearchTime.value = urlTime;
    pendingUrlSearch = true;
  }

  initCarousel();
  initAvailCal();

  if (!roomsViewBound) {
    roomsViewBound = true;
    roomsSearchTextInput()?.addEventListener("input", () => {
      renderRoomsView(state);
    });
    roomsSortSelect()?.addEventListener("change", (event) => {
      roomsCatalogSort = event.target.value || "recommended";
      renderRoomsView(state);
    });
    roomsCategoryBar()?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-room-category]");
      if (!button) {
        return;
      }
      selectedRoomCategory = button.dataset.roomCategory || "all";
      renderRoomsView(state);
    });
  }

  if (elements.showInactiveToggle) {
    elements.showInactiveToggle.addEventListener("change", async (event) => {
      setState({
        showInactiveRooms: event.target.checked,
        roomAvailabilityPreview: {},
        message: "Room filter updated.",
      });
      await actions.refreshRooms();
    });
  }

  if (elements.roomsSearchDate) {
    elements.roomsSearchDate.value = state.roomAvailabilitySearch.date;
  }
  if (elements.roomsSearchTime) {
    elements.roomsSearchTime.value = state.roomAvailabilitySearch.time;
  }
  if (elements.roomsSearchDuration) {
    elements.roomsSearchDuration.value = String(state.roomAvailabilitySearch.duration);
  }

  elements.roomsSearchButton?.addEventListener("click", async () => {
    await searchRoomsByAvailability();
    closeRoomsWhenBar();
  });
  elements.roomsSearchClearButton?.addEventListener("click", () => {
    clearRoomAvailabilitySearch();
    closeRoomsWhenBar();
  });
  elements.roomsSearchTime?.addEventListener("change", () => {
    renderRoomsView(state);
  });

  const whenToggleBtn = document.getElementById("rooms-when-toggle");
  whenToggleBtn?.addEventListener("click", () => {
    const bar = document.getElementById("rooms-when-bar");
    if (!bar) return;
    const wasHidden = bar.classList.contains("hidden");
    if (wasHidden) {
      openRoomsWhenBar();
    } else {
      closeRoomsWhenBar();
    }
  });

  if (elements.roomForm) {
    elements.roomFormCancel?.addEventListener("click", () => {
      resetRoomForm();
      renderCreateRoomStaffOptions(state);
      if (isAdminPage()) {
        window.dispatchEvent(
          new CustomEvent("admin-subpage-request", {
            detail: { group: "rooms", subpage: "inventory" },
          }),
        );
      }
    });

    window.addEventListener("admin-room-create-request", () => {
      resetRoomForm();
      renderCreateRoomStaffOptions(state);
    });

    getRoomPhotoFileInput()?.addEventListener("change", () => {
      const file = getRoomPhotoFileInput()?.files?.[0];
      if (!file) {
        setRoomPhotoPreview(
          getRoomPhotoUrlInput()?.value || null,
          elements.roomForm?.elements?.name?.value || "Room",
        );
        return;
      }
      setRoomPhotoPreview(
        URL.createObjectURL(file),
        elements.roomForm?.elements?.name?.value || file.name,
      );
    });

    elements.adminRoomCreateStaffOptions?.addEventListener("change", (event) => {
      const input = event.target.closest("input[type='checkbox']");
      if (!input) {
        return;
      }

      if (input.checked) {
        selectedCreateStaffIds.add(input.value);
      } else {
        selectedCreateStaffIds.delete(input.value);
      }
    });

    elements.roomForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.roomForm);
      let primaryPhotoUrl = String(form.get("primary_photo_url") || "").trim() || null;
      const roomPhotoFile = getRoomPhotoFileInput()?.files?.[0];
      const additionalPhotos = String(form.get("photos") || "")
        .split("\n")
        .map((value) => value.trim())
        .filter(Boolean);

      try {
        if (roomPhotoFile) {
          setState({ message: "Uploading photo..." });
          const upload = await api.adminUploadRoomPhoto(roomPhotoFile);
          primaryPhotoUrl = upload.photo_url;
          const roomPhotoUrlInput = getRoomPhotoUrlInput();
          if (roomPhotoUrlInput) {
            roomPhotoUrlInput.value = primaryPhotoUrl;
          }
        }
        const photos = Array.from(new Set([primaryPhotoUrl, ...additionalPhotos].filter(Boolean)));

        const payload = {
          name: form.get("name"),
          description: form.get("description") || null,
          capacity: form.get("capacity") ? Number(form.get("capacity")) : null,
          photos,
          staff_roles: collectCreateRoomStaffPayload(),
          hourly_rate_cents: Number(form.get("hourly_rate_cents") || 0),
          max_booking_duration_minutes: Number(form.get("max_booking_duration_minutes") || 300),
          status: form.get("status") || "available",
        };

        const isEditingRoom = Boolean(editingRoomId);
        setState({ message: isEditingRoom ? "Saving room changes..." : "Creating room..." });
        if (isEditingRoom) {
          await api.adminUpdateRoom(editingRoomId, payload);
        } else {
          await api.createRoom(payload);
        }
        resetRoomForm();
        if (isAdminPage()) {
          window.dispatchEvent(
            new CustomEvent("admin-subpage-request", {
              detail: { group: "rooms", subpage: "inventory" },
            }),
          );
        }
        setState({ roomAvailabilityPreview: {} });
        await actions.refreshRooms(isEditingRoom ? "Room updated." : "Room created.");
      } catch (error) {
        setState({ message: error.message });
      }
    });
  }

  if (!elements.roomsGrid) {
    return;
  }

  elements.roomsGrid.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-room-action]");
    if (!button) {
      return;
    }

    const roomId = button.dataset.roomId;
    const action = button.dataset.roomAction;

    try {
      if (action === "edit") {
        const room = state.rooms.find((item) => String(item.id) === roomId);
        if (!room) {
          setState({ message: "Room not found." });
          return;
        }
          populateRoomForm(room);
          renderCreateRoomStaffOptions(state);
          window.dispatchEvent(
            new CustomEvent("admin-subpage-request", {
              detail: { group: "rooms", subpage: "editor" },
            }),
          );
          if (!isAdminPage()) {
            elements.roomForm?.scrollIntoView({ behavior: "smooth", block: "start" });
          }
          setState({ message: `Editing ${room.name}.` });
          return;
        }

      if (action === "delete") {
        const roomName = button.dataset.roomName || "this room";
        const confirmed = window.confirm(`Delete ${roomName} permanently? This cannot be undone.`);
        if (!confirmed) {
          return;
        }
      }

      setState({
        message:
          action === "archive"
            ? "Archiving room..."
            : action === "restore"
              ? "Restoring room..."
              : "Deleting room...",
      });
      if (action === "archive") {
        await api.archiveRoom(roomId);
      } else if (action === "delete") {
        await api.deleteRoomPermanently(roomId);
      } else {
        await api.restoreRoom(roomId);
      }
      setState({ roomAvailabilityPreview: {} });
      await actions.refreshRooms(
        action === "archive"
          ? "Room archived."
          : action === "restore"
            ? "Room restored."
            : "Room deleted.",
      );
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

export function renderRoomsView(currentState) {
  const canManageRooms = Boolean(currentState.currentUser?.is_admin);
  renderCategoryFilterBar(currentState.rooms);
  renderRoomsWhenToggleChip(currentState);
  if (elements.roomsToolbar) {
    elements.roomsToolbar.classList.toggle("hidden", !canManageRooms);
  }
  if (elements.showInactiveToggle) {
    elements.showInactiveToggle.checked = currentState.showInactiveRooms;
  }
  if (elements.roomsSearchDate) {
    const todayKey = availCalTodayLocal();
    if (elements.roomsSearchDate.min !== todayKey) {
      elements.roomsSearchDate.min = todayKey;
    }
    if (elements.roomsSearchDate.value !== currentState.roomAvailabilitySearch.date) {
      elements.roomsSearchDate.value = currentState.roomAvailabilitySearch.date;
    }
  }
  if (elements.roomsSearchTime && elements.roomsSearchTime.value !== currentState.roomAvailabilitySearch.time) {
    elements.roomsSearchTime.value = currentState.roomAvailabilitySearch.time;
  }
  if (elements.roomsSearchDuration) {
    const selectedTime = elements.roomsSearchTime?.value || currentState.roomAvailabilitySearch.time;
    const maxDuration = maxDurationMinutesForStartTime(selectedTime);
    Array.from(elements.roomsSearchDuration.options).forEach((opt) => {
      opt.disabled = Number(opt.value) > maxDuration;
    });
    const currentDuration = Number(currentState.roomAvailabilitySearch.duration || 60);
    const targetDuration = currentDuration > maxDuration ? maxDuration : currentDuration;
    if (elements.roomsSearchDuration.value !== String(targetDuration)) {
      elements.roomsSearchDuration.value = String(targetDuration);
    }
  }

  renderCreateRoomStaffOptions(currentState);

  if (pendingUrlSearch && currentState.rooms.length) {
    pendingUrlSearch = false;
    searchRoomsByAvailability();
    return;
  }

  if (!elements.roomsGrid) {
    return;
  }

  const availabilityScopedRooms = currentState.roomAvailabilitySearch.hasSearched
    ? currentState.rooms.filter((room) => currentState.roomAvailabilitySearch.matchingRoomIds.includes(String(room.id)))
    : currentState.rooms;
  const searchText = roomsSearchTextInput()?.value.trim().toLowerCase() || "";

  let visibleRooms = availabilityScopedRooms.filter((room) => {
    if (selectedRoomCategory !== "all" && getRoomCategory(room) !== selectedRoomCategory) {
      return false;
    }
    if (searchText && !getRoomSearchText(room).includes(searchText)) {
      return false;
    }
    return true;
  });

  if (elements.roomsSearchSummary) {
    const search = currentState.roomAvailabilitySearch;
    if (!search.hasSearched) {
      elements.roomsSearchSummary.classList.add("hidden");
      elements.roomsSearchSummary.innerHTML = "";
    } else {
      const dateLabel = formatSearchDateLabel(search.date);
      const timeLabel = formatSearchTimeLabel(search.time);
      const durationLabel = formatDuration(search.duration);
      elements.roomsSearchSummary.classList.remove("hidden");
      if (!visibleRooms.length) {
        elements.roomsSearchSummary.innerHTML = `
          <strong>No studios available</strong>
          <span>No studios are open on ${escapeHtml(dateLabel)} at ${escapeHtml(timeLabel)} for ${escapeHtml(durationLabel)}.</span>
        `;
      } else {
        elements.roomsSearchSummary.innerHTML = `
          <strong>${visibleRooms.length} studio${visibleRooms.length === 1 ? "" : "s"} available</strong>
          <span>On ${escapeHtml(dateLabel)} at ${escapeHtml(timeLabel)} for ${escapeHtml(durationLabel)}.</span>
        `;
      }
    }
  }

  visibleRooms = [...visibleRooms].sort((left, right) => {
    if (roomsCatalogSort === "price-low") {
      return (left.hourly_rate_cents || 0) - (right.hourly_rate_cents || 0);
    }
    if (roomsCatalogSort === "price-high") {
      return (right.hourly_rate_cents || 0) - (left.hourly_rate_cents || 0);
    }
    if (roomsCatalogSort === "capacity") {
      return (right.capacity || 0) - (left.capacity || 0);
    }
    if (roomsCatalogSort === "name") {
      return String(left.name || "").localeCompare(String(right.name || ""));
    }

    const ratingDelta = getRoomRating(right) - getRoomRating(left);
    if (ratingDelta !== 0) {
      return ratingDelta;
    }
    return (left.hourly_rate_cents || 0) - (right.hourly_rate_cents || 0);
  });

  if (roomsResultsCount()) {
    const categoryLabel = selectedRoomCategory === "all" ? "all categories" : formatRoomCategoryLabel(selectedRoomCategory).toLowerCase();
    roomsResultsCount().textContent = `${formatRoomCount(visibleRooms.length)} in ${categoryLabel}`;
  }

  if (!visibleRooms.length) {
    const hasSearched = currentState.roomAvailabilitySearch.hasSearched;
    const hasTextFilter = Boolean(searchText);
    const hasCategoryFilter = selectedRoomCategory !== "all";
    let emptyCopy;
    if (hasSearched) {
      emptyCopy = "No studios match this time slot. Try a different date, time, or duration.";
    } else if (hasTextFilter || hasCategoryFilter) {
      emptyCopy = "No studios match these filters. Try a different category or clear the search.";
    } else if (canManageRooms) {
      emptyCopy = "No studios yet. Create one from the admin panel to get started.";
    } else {
      emptyCopy = "No studios are available right now. Please check back soon.";
    }
    elements.roomsGrid.innerHTML = `
      <div class="empty-state">${escapeHtml(emptyCopy)}</div>
    `;
  } else {
    elements.roomsGrid.innerHTML = visibleRooms
      .map((room) => renderRoomCard(room, canManageRooms))
      .join("");
  }

  if (elements.adminEmpty) {
    elements.adminEmpty.classList.toggle("hidden", canManageRooms);
  }
  if (elements.roomForm) {
    if (!canManageRooms) {
      elements.roomForm.classList.add("hidden");
      resetRoomForm();
    } else if (!isAdminPage()) {
      elements.roomForm.classList.remove("hidden");
    }
  }
}
