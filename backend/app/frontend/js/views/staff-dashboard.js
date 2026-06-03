import { api } from "../api.js";
import { CURRENT_PAGE } from "../config.js";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function el(id) {
  return document.getElementById(id);
}

function minutesToTime(minutes) {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

function timeToMinutes(value) {
  const [hours, mins] = String(value || "").split(":").map(Number);
  if (Number.isNaN(hours)) return null;
  return hours * 60 + (mins || 0);
}

function setFeedback(message, type) {
  const node = el("staff-dashboard-feedback");
  if (!node) return;
  node.textContent = message;
  node.classList.remove("hidden", "is-error", "is-success");
  if (type) node.classList.add(type === "error" ? "is-error" : "is-success");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function setProfileFeedback(message, type) {
  const node = el("staff-profile-feedback");
  if (!node) return;
  if (!message) {
    node.textContent = "";
    node.classList.add("hidden");
    node.classList.remove("is-error", "is-success");
    return;
  }
  node.textContent = message;
  node.classList.remove("hidden", "is-error", "is-success");
  node.classList.add(type === "error" ? "is-error" : "is-success");
}

function parseList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function setProfilePhotoPreview(photoUrl) {
  const node = el("staff-profile-photo-preview");
  if (!node) return;
  if (photoUrl) {
    node.innerHTML = `<img src="${escapeHtml(photoUrl)}" alt="Profile photo" />`;
    node.classList.remove("empty-state");
  } else {
    node.textContent = "Upload a JPG photo to show on your public profile.";
    node.classList.add("empty-state");
  }
}

function populateProfileForm(profile) {
  const form = el("staff-profile-form");
  if (!form) return;
  form.elements.name.value = profile.name || "";
  form.elements.role_title.value = profile.role_title || "";
  form.elements.description.value = profile.description || "";
  form.elements.bio.value = profile.bio || "";
  form.elements.skills.value = (profile.skills || []).join(", ");
  form.elements.talents.value = (profile.talents || []).join(", ");
  form.elements.services.value = (profile.services || []).join(", ");
  form.elements.service_types.value = (profile.service_types || []).join(", ");
  form.elements.portfolio_url.value = profile.portfolio_url || "";
  form.elements.notification_email.value = profile.notification_email || "";
  form.elements.notification_phone.value = profile.notification_phone || "";
  form.elements.notify_by_email.checked = profile.notify_by_email !== false;
  form.elements.notify_by_sms.checked = Boolean(profile.notify_by_sms);
  const photoUrlField = el("staff-profile-photo-url");
  if (photoUrlField) photoUrlField.value = profile.photo_url || "";
  setProfilePhotoPreview(profile.photo_url);
}

async function renderRequests() {
  const list = el("staff-requests-list");
  if (!list) return;
  let bookings = [];
  try {
    bookings = await api.getMyBookingRequests();
  } catch (error) {
    list.innerHTML = '<div class="empty-state">Could not load requests.</div>';
    return;
  }
  if (!bookings.length) {
    list.innerHTML = '<div class="empty-state">No booking requests yet.</div>';
    return;
  }
  list.innerHTML = bookings
    .map((booking) => {
      const when = booking.start_time ? new Date(booking.start_time).toLocaleString() : "";
      const isRequested = booking.status === "Requested";
      const actions = isRequested
        ? `<div class="room-actions">
             <button class="primary-button" type="button" data-staff-action="accept" data-booking-id="${escapeHtml(booking.id)}">Accept</button>
             <button class="ghost-button" type="button" data-staff-action="decline" data-booking-id="${escapeHtml(booking.id)}">Decline</button>
           </div>`
        : "";
      return `
        <article class="admin-intake-card is-status-${escapeHtml(booking.status)}">
          <div class="admin-intake-card-header">
            <div>
              <h4>${escapeHtml(booking.user_full_name || "Client")}</h4>
              <p class="admin-intake-contact">${escapeHtml(when)}${booking.service_type ? " · " + escapeHtml(booking.service_type) : ""}</p>
            </div>
            <span class="pill">${escapeHtml(booking.status)}</span>
          </div>
          ${actions}
        </article>`;
    })
    .join("");
}

async function renderRules() {
  const list = el("staff-rules-list");
  if (!list) return;
  let rules = [];
  try {
    rules = await api.getMyAvailabilityRules();
  } catch (error) {
    return;
  }
  list.innerHTML = rules.length
    ? rules
        .map(
          (rule) => `
        <div class="summary-line staff-schedule-row">
          <span>${escapeHtml(WEEKDAYS[rule.weekday] || "Day")} · ${minutesToTime(rule.start_minute)}–${minutesToTime(rule.end_minute)}</span>
          <button class="ghost-button" type="button" data-staff-action="delete-rule" data-rule-id="${escapeHtml(rule.id)}">Remove</button>
        </div>`,
        )
        .join("")
    : '<div class="empty-state">No weekly windows yet. Add one above.</div>';
}

async function renderExceptions() {
  const list = el("staff-exceptions-list");
  if (!list) return;
  let exceptions = [];
  try {
    exceptions = await api.getMyAvailabilityExceptions();
  } catch (error) {
    return;
  }
  list.innerHTML = exceptions.length
    ? exceptions
        .map((exc) => {
          const span =
            exc.start_minute != null
              ? `${minutesToTime(exc.start_minute)}–${minutesToTime(exc.end_minute)}`
              : "All day";
          const label = exc.is_available ? "Extra available" : "Unavailable";
          return `
            <div class="summary-line staff-schedule-row">
              <span>${escapeHtml(exc.exception_date)} · ${escapeHtml(label)} · ${span}${exc.reason ? " · " + escapeHtml(exc.reason) : ""}</span>
              <button class="ghost-button" type="button" data-staff-action="delete-exception" data-exception-id="${escapeHtml(exc.id)}">Remove</button>
            </div>`;
        })
        .join("")
    : '<div class="empty-state">No one-off changes.</div>';
}

function showGate() {
  el("staff-dashboard-gate")?.classList.remove("hidden");
  el("staff-dashboard-body")?.classList.add("hidden");
}

async function loadDashboard() {
  let profile;
  try {
    profile = await api.getMyStaffProfile();
  } catch (error) {
    showGate();
    return;
  }
  el("staff-dashboard-gate")?.classList.add("hidden");
  el("staff-dashboard-body")?.classList.remove("hidden");
  const title = el("staff-dashboard-title");
  if (title) title.textContent = `${profile.name}'s dashboard`;
  const subtitle = el("staff-dashboard-subtitle");
  if (subtitle) {
    subtitle.textContent = profile.schedule_published
      ? "Your schedule is published — customers can request to book you."
      : "Set your availability and respond to requests. An admin publishes your schedule to make it public.";
  }
  populateProfileForm(profile);
  await Promise.all([renderRequests(), renderRules(), renderExceptions()]);
}

export function initStaffDashboardView() {
  if (CURRENT_PAGE !== "staff-dashboard") return;

  el("staff-profile-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setProfileFeedback(null);
    try {
      let photoUrl = el("staff-profile-photo-url")?.value || null;
      const file = el("staff-profile-photo-file")?.files?.[0];
      if (file) {
        const upload = await api.uploadMyStaffPhoto(file);
        photoUrl = upload.photo_url;
      }
      const payload = {
        name: form.elements.name.value.trim(),
        role_title: form.elements.role_title.value.trim() || null,
        description: form.elements.description.value.trim() || null,
        bio: form.elements.bio.value.trim() || null,
        skills: parseList(form.elements.skills.value),
        talents: parseList(form.elements.talents.value),
        services: parseList(form.elements.services.value),
        service_types: parseList(form.elements.service_types.value),
        portfolio_url: form.elements.portfolio_url.value.trim() || null,
        notification_email: form.elements.notification_email.value.trim() || null,
        notification_phone: form.elements.notification_phone.value.trim() || null,
        notify_by_email: form.elements.notify_by_email.checked,
        notify_by_sms: form.elements.notify_by_sms.checked,
        photo_url: photoUrl,
      };
      const updated = await api.updateMyStaffProfile(payload);
      populateProfileForm(updated);
      const fileField = el("staff-profile-photo-file");
      if (fileField) fileField.value = "";
      const title = el("staff-dashboard-title");
      if (title) title.textContent = `${updated.name}'s dashboard`;
      setProfileFeedback("Profile saved.", "success");
    } catch (error) {
      setProfileFeedback(error?.message || "Could not save your profile.", "error");
    }
  });

  el("staff-rule-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      weekday: Number(form.elements.weekday.value),
      start_minute: timeToMinutes(form.elements.start.value),
      end_minute: timeToMinutes(form.elements.end.value),
    };
    try {
      await api.createMyAvailabilityRule(payload);
      form.reset();
      setFeedback("Weekly window added.", "success");
      await renderRules();
    } catch (error) {
      setFeedback(error?.message || "Could not add that window.", "error");
    }
  });

  el("staff-exception-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const start = form.elements.start.value ? timeToMinutes(form.elements.start.value) : null;
    const end = form.elements.end.value ? timeToMinutes(form.elements.end.value) : null;
    const payload = {
      exception_date: form.elements.date.value,
      is_available: form.elements.kind.value === "available",
      start_minute: start,
      end_minute: end,
      reason: form.elements.reason.value.trim() || null,
    };
    try {
      await api.createMyAvailabilityException(payload);
      form.reset();
      setFeedback("Change saved.", "success");
      await renderExceptions();
    } catch (error) {
      setFeedback(error?.message || "Could not save that change.", "error");
    }
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-staff-action]");
    if (!button) return;
    const action = button.dataset.staffAction;
    try {
      button.disabled = true;
      if (action === "accept") {
        await api.acceptMyBookingRequest(button.dataset.bookingId);
        setFeedback("Request accepted — the client can now pay.", "success");
        await renderRequests();
      } else if (action === "decline") {
        await api.declineMyBookingRequest(button.dataset.bookingId, null);
        setFeedback("Request declined.", "success");
        await renderRequests();
      } else if (action === "delete-rule") {
        await api.deleteMyAvailabilityRule(button.dataset.ruleId);
        await renderRules();
      } else if (action === "delete-exception") {
        await api.deleteMyAvailabilityException(button.dataset.exceptionId);
        await renderExceptions();
      }
    } catch (error) {
      setFeedback(error?.message || "Something went wrong.", "error");
      button.disabled = false;
    }
  });

  loadDashboard();
}

export function renderStaffDashboardView() {}
