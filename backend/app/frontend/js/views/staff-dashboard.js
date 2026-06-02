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
  await Promise.all([renderRequests(), renderRules(), renderExceptions()]);
}

export function initStaffDashboardView() {
  if (CURRENT_PAGE !== "staff-dashboard") return;

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
