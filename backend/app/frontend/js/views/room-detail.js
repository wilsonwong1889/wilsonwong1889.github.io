import { elements } from "../dom.js";
// Neutral graphic shown when a room has no uploaded photos (or a photo fails to
// load). We never fill a room's gallery with unrelated stock images.
const ROOM_PLACEHOLDER_IMAGE = "/assets/media/room-placeholder.svg";

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

function formatDuration(minutes) {
  const hours = minutes / 60;
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function formatCategoryLabel(room) {
  const category = getRoomCategory(room);
  return `${category.charAt(0).toUpperCase()}${category.slice(1)} studio`;
}

function getTrustCopy() {
  return ["Deposits are non-refundable", "Plan to arrive 10-15 min early"];
}

function renderStaffImage(photoUrl, label) {
  const safeLabel = escapeHtml(label);
  if (photoUrl) {
    return `<img class="staff-profile-image" src="${escapeHtml(photoUrl)}" alt="${safeLabel}" loading="lazy" />`;
  }
  return `<div class="staff-profile-image staff-avatar-fallback">${escapeHtml(label.slice(0, 1).toUpperCase())}</div>`;
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

function getRoomGallery(room) {
  // Only the room's own uploaded photos — no category stock fill-ins.
  const rawPhotos = Array.isArray(room.photos) ? room.photos : [];
  return rawPhotos.filter(Boolean);
}

function buildAmenityList(room) {
  const amenities = [];
  if ((room.capacity || 0) >= 4) {
    amenities.push("Group-friendly setup");
  }
  if ((room.staff_roles || []).length) {
    amenities.push("Optional staff support");
  }
  if ((room.photos || []).length > 1) {
    amenities.push("Multi-angle gallery");
  }
  amenities.push("Central location");
  return amenities.slice(0, 4);
}

function renderRoomStaffList(room) {
  if (!elements.roomDetailStaffList) {
    return;
  }

  const staffRoles = room.staff_roles || [];
  elements.roomDetailStaffList.innerHTML = staffRoles.length
    ? staffRoles
        .map(
          (role) => `
            <article class="staff-profile-card">
              <div class="staff-profile-card-top">
                ${renderStaffImage(role.photo_url, role.name)}
                <div class="staff-option-copy">
                  <strong>${escapeHtml(role.name)}</strong>
                  <span>${escapeHtml(role.description || "Available as an optional add-on for this room.")}</span>
                </div>
              </div>
              <strong class="staff-option-price">$25/hr add-on</strong>
              <div class="staff-option-copy">
                ${renderTagGroup("Skills", role.skills || [])}
                ${renderTagGroup("Talents", role.talents || [])}
              </div>
            </article>
          `,
        )
        .join("")
    : '<div class="empty-state">This room does not have extra staff add-ons configured yet.</div>';
}

export function initRoomDetailView() {}

export function renderRoomDetailView(state) {
  if (!elements.roomDetailEmpty || !elements.roomDetailCard) {
    return;
  }

  const room = state.selectedRoom;
  const hasRoom = Boolean(room);
  elements.roomDetailEmpty.classList.toggle("hidden", hasRoom);
  elements.roomDetailCard.classList.toggle("hidden", !hasRoom);

  if (!room) {
    return;
  }

  elements.roomDetailTitle.textContent = room.name;
  elements.roomDetailDescription.textContent = room.description || "No description available yet.";
  const isComingSoon = Boolean(room.coming_soon) && !room.active;
  const STATUS_LABELS = { available: "Available", in_progress: "In Progress", tbc: "TBC" };
  const STATUS_CLASSES = { available: "is-available", in_progress: "is-in-progress", tbc: "is-tbc" };
  const statusLabel = !room.active
    ? (isComingSoon ? "Coming Soon" : "Inactive")
    : (STATUS_LABELS[room.status] || "Available");
  const statusClass = !room.active
    ? (isComingSoon ? "is-coming-soon" : "muted")
    : (STATUS_CLASSES[room.status] || "is-available");
  elements.roomDetailMeta.innerHTML = `
    <span class="pill">${escapeHtml(formatCategoryLabel(room))}</span>
    <span class="pill room-status-pill ${statusClass}">${escapeHtml(statusLabel)}</span>
    <span class="pill">Up to ${escapeHtml(room.capacity || "n/a")} people</span>
    <span class="pill">Min 1 hour</span>
  `;
  if (elements.roomDetailAmenities) {
    elements.roomDetailAmenities.innerHTML = buildAmenityList(room)
      .map((item) => `<span class="room-detail-amenity">${escapeHtml(item)}</span>`)
      .join("");
  }
  renderRoomStaffList(room);

  const trustStrip = document.getElementById("room-detail-trust-strip");
  if (trustStrip) {
    trustStrip.innerHTML = getTrustCopy()
      .map((item) => `<span class="pill">${escapeHtml(item)}</span>`)
      .join("");
  }

  const photos = getRoomGallery(room);
  elements.roomDetailPhotos.innerHTML = photos.length
    ? photos
        .map(
          (photo, index) => `
            <figure class="${index === 0 ? "room-detail-hero-media" : "room-detail-thumb-card"}">
              <img class="detail-image" src="${escapeHtml(photo)}" alt="${escapeHtml(room.name)} image ${index + 1}" loading="lazy" onerror="this.onerror=null;this.src='${ROOM_PLACEHOLDER_IMAGE}';" />
              ${index === 0 ? "" : `<figcaption>Image ${index + 1}</figcaption>`}
            </figure>
          `,
        )
        .join("")
    : '<div class="empty-state">No room images were added for this room yet.</div>';

  if (elements.roomDetailBookingLink) {
    if (room.active) {
      elements.roomDetailBookingLink.href = `/reserve?id=${room.id}`;
      elements.roomDetailBookingLink.textContent = "Book this room";
      elements.roomDetailBookingLink.removeAttribute("aria-disabled");
      elements.roomDetailBookingLink.classList.remove("is-disabled");
    } else {
      elements.roomDetailBookingLink.removeAttribute("href");
      elements.roomDetailBookingLink.setAttribute("aria-disabled", "true");
      elements.roomDetailBookingLink.classList.add("is-disabled");
      elements.roomDetailBookingLink.textContent = isComingSoon ? "Coming Soon" : "Unavailable";
    }
  }
  if (elements.roomDetailReserveLink) {
    elements.roomDetailReserveLink.href = `/rooms`;
    elements.roomDetailReserveLink.textContent = "Back to rooms";
  }
  if (elements.roomDetailPrice) {
    elements.roomDetailPrice.textContent = formatCurrency(room.hourly_rate_cents);
  }
  if (elements.roomDetailBookingCopy) {
    elements.roomDetailBookingCopy.textContent = isComingSoon
      ? "This studio is opening soon. Check back here to book once it launches."
      : room.active
        ? "Move into reserve to choose a time, confirm availability, and finish payment with PayPal."
        : "This studio is not currently available for booking."
  }
}
