import { api } from "../api.js";
import { CURRENT_PAGE } from "../config.js";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// "staff" = approved staff member (full portal); "applicant" = a logged-in user
// who is building/awaiting approval on a studio-engineer application.
let dashboardMode = "staff";
let headshotUrls = [];
let scheduleRules = [];
let scheduleExceptions = [];
let weeklyWindows = { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [] };
const DEFAULT_WINDOW = { start_minute: 720, end_minute: 1200 }; // 12:00–20:00
let dashboardSelectedDate = todayString();
let dashboardCalendarMonth = firstOfMonth(dashboardSelectedDate);

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

function todayString() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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

function formatDateLabel(value) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
  }).format(new Date(`${value}T00:00:00`));
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

function mergeWindows(windows) {
  const ordered = windows
    .filter((window) => Number.isFinite(window.start) && Number.isFinite(window.end) && window.start < window.end)
    .sort((left, right) => left.start - right.start);
  const merged = [];
  ordered.forEach((window) => {
    const previous = merged[merged.length - 1];
    if (previous && window.start <= previous.end) {
      previous.end = Math.max(previous.end, window.end);
      return;
    }
    merged.push({ ...window });
  });
  return merged;
}

function subtractWindow(windows, block) {
  const result = [];
  windows.forEach((window) => {
    if (block.end <= window.start || block.start >= window.end) {
      result.push(window);
      return;
    }
    if (block.start > window.start) {
      result.push({ start: window.start, end: block.start });
    }
    if (block.end < window.end) {
      result.push({ start: block.end, end: window.end });
    }
  });
  return result;
}

function dateWeekday(value) {
  return (new Date(`${value}T00:00:00`).getDay() + 6) % 7;
}

function exceptionsForDate(value) {
  return scheduleExceptions.filter((item) => String(item.exception_date) === String(value));
}

function windowsForDate(value) {
  let windows = scheduleRules
    .filter((rule) => rule.active !== false && Number(rule.weekday) === dateWeekday(value))
    .map((rule) => ({ start: Number(rule.start_minute), end: Number(rule.end_minute) }));

  exceptionsForDate(value)
    .filter((item) => item.is_available)
    .forEach((item) => {
      windows.push({
        start: item.start_minute == null ? 0 : Number(item.start_minute),
        end: item.end_minute == null ? 1440 : Number(item.end_minute),
      });
    });
  windows = mergeWindows(windows);

  exceptionsForDate(value)
    .filter((item) => !item.is_available)
    .forEach((item) => {
      windows = subtractWindow(windows, {
        start: item.start_minute == null ? 0 : Number(item.start_minute),
        end: item.end_minute == null ? 1440 : Number(item.end_minute),
      });
    });

  return mergeWindows(windows);
}

function syncExceptionFormToSelectedDate() {
  const form = el("staff-exception-form");
  if (!form || !dashboardSelectedDate) return;
  form.elements.date.value = dashboardSelectedDate;
}

function renderDashboardCalendar() {
  const grid = el("staff-dashboard-month-grid");
  const title = el("staff-dashboard-calendar-title");
  const selectedLabel = el("staff-dashboard-selected-date-label");
  const selectedWindows = el("staff-dashboard-day-windows");
  if (!grid || !title || !dashboardCalendarMonth) return;

  const monthDate = new Date(`${dashboardCalendarMonth}T00:00:00`);
  title.textContent = new Intl.DateTimeFormat("en-CA", {
    month: "long",
    year: "numeric",
  }).format(monthDate);

  const firstDay = new Date(`${dashboardCalendarMonth}T00:00:00`);
  const startOffset = firstDay.getDay();
  const totalDays = daysInMonth(dashboardCalendarMonth);
  const cells = [];

  for (let index = 0; index < startOffset; index += 1) {
    cells.push('<div class="calendar-cell calendar-cell-empty"></div>');
  }

  for (let day = 1; day <= totalDays; day += 1) {
    const date = new Date(`${dashboardCalendarMonth}T00:00:00`);
    date.setDate(day);
    const isoDate = date.toISOString().slice(0, 10);
    const windows = windowsForDate(isoDate);
    const isSelected = isoDate === dashboardSelectedDate;
    const label = windows.length ? `${windows.length} window${windows.length === 1 ? "" : "s"}` : "Unavailable";
    const ariaLabel = `${formatDateLabel(isoDate)}: ${label}${isSelected ? ", selected" : ""}`;
    cells.push(`
      <button
        class="calendar-cell ${isSelected ? "is-selected" : ""} ${windows.length ? "is-open" : "is-closed"}"
        type="button"
        data-staff-dashboard-date="${escapeHtml(isoDate)}"
        aria-label="${escapeHtml(ariaLabel)}"
      >
        <strong>${day}</strong>
        <span>${escapeHtml(label)}</span>
      </button>
    `);
  }

  grid.innerHTML = cells.join("");

  if (selectedLabel) {
    selectedLabel.textContent = formatDateLabel(dashboardSelectedDate);
  }
  if (selectedWindows) {
    const windows = windowsForDate(dashboardSelectedDate);
    selectedWindows.innerHTML = windows.length
      ? windows
          .map((window) => `<span class="pill">${minutesToTime(window.start)}-${minutesToTime(window.end)}</span>`)
          .join("")
      : '<span class="empty-state">Unavailable until you add a weekly window or one-off availability.</span>';
  }
  syncExceptionFormToSelectedDate();
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

function renderHeadshots() {
  const list = el("staff-profile-headshots-list");
  if (!list) return;
  list.innerHTML = headshotUrls
    .map(
      (url, index) => `
        <div class="staff-headshot-thumb">
          <img src="${escapeHtml(url)}" alt="Headshot ${index + 1}" />
          <button type="button" class="ghost-button" data-headshot-remove="${index}">Remove</button>
        </div>`,
    )
    .join("");
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
  form.elements.gear.value = profile.gear || "";
  form.elements.portfolio_url.value = profile.portfolio_url || "";
  form.elements.notification_email.value = profile.notification_email || "";
  form.elements.notification_phone.value = profile.notification_phone || "";
  form.elements.notify_by_email.checked = profile.notify_by_email !== false;
  form.elements.notify_by_sms.checked = Boolean(profile.notify_by_sms);
  const photoUrlField = el("staff-profile-photo-url");
  if (photoUrlField) photoUrlField.value = profile.photo_url || "";
  setProfilePhotoPreview(profile.photo_url);
  headshotUrls = Array.isArray(profile.headshot_urls) ? [...profile.headshot_urls] : [];
  renderHeadshots();
}

function setApplicationBanner(message, type) {
  const node = el("staff-application-banner");
  if (!node) return;
  if (!message) {
    node.textContent = "";
    node.classList.add("hidden");
    node.classList.remove("is-error", "is-success");
    return;
  }
  node.textContent = message;
  node.classList.remove("hidden", "is-error", "is-success");
  if (type) node.classList.add(type === "error" ? "is-error" : "is-success");
}

function applyDashboardMode(profile) {
  // Applicant mode: only the profile form is shown; schedule/requests are
  // hidden until an admin approves and grants the staff role.
  const approvedSections = el("staff-approved-sections");
  const heading = el("staff-profile-heading");
  const subhead = el("staff-profile-subhead");
  const submitBtn = el("staff-profile-submit");
  const isApplicant = dashboardMode === "applicant";
  if (approvedSections) approvedSections.classList.toggle("hidden", isApplicant);
  const eyebrow = el("staff-dashboard-eyebrow");
  if (!isApplicant) {
    setApplicationBanner(null);
    if (eyebrow) eyebrow.textContent = "Studio engineer ✓";
    if (heading) heading.textContent = "Edit your profile";
    if (subhead) subhead.textContent = "You're an approved studio engineer. Edit how you appear to customers here. Pricing, publishing your schedule, your account link, and studio assignments are managed by an admin.";
    if (submitBtn) submitBtn.textContent = "Save profile";
    return;
  }
  if (eyebrow) eyebrow.textContent = "Studio engineer application";
  if (heading) heading.textContent = "Your studio engineer profile";
  if (subhead) subhead.textContent = "Fill out your profile — photo, portfolio photos, skills, and gear. Submit it and an admin will review and grant you studio engineer access.";
  if (submitBtn) submitBtn.textContent = "Submit application";
  const submitted = profile && profile.application_status === "submitted";
  setApplicationBanner(
    submitted
      ? "Your application is submitted and under review. You can keep editing and re-submit until an admin approves it."
      : "Create your studio engineer profile below, then submit it for admin review.",
    submitted ? "success" : null,
  );
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

function buildWeeklyWindows() {
  weeklyWindows = { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [] };
  for (const rule of scheduleRules) {
    if (!weeklyWindows[rule.weekday]) weeklyWindows[rule.weekday] = [];
    weeklyWindows[rule.weekday].push({ start_minute: rule.start_minute, end_minute: rule.end_minute });
  }
  for (const day of Object.keys(weeklyWindows)) {
    weeklyWindows[day].sort((a, b) => a.start_minute - b.start_minute);
  }
}

function renderWeeklyEditor() {
  const editor = el("staff-weekly-editor");
  if (!editor) return;
  editor.innerHTML = WEEKDAYS.map((dayName, weekday) => {
    const windows = weeklyWindows[weekday] || [];
    const isOpen = windows.length > 0;
    const blocks = isOpen
      ? windows
          .map(
            (w, index) => `
            <div class="staff-day-window" data-index="${index}">
              <input type="time" step="1800" data-win-start value="${minutesToTime(w.start_minute)}" aria-label="${dayName} start" />
              <span class="staff-day-dash">–</span>
              <input type="time" step="1800" data-win-end value="${minutesToTime(w.end_minute)}" aria-label="${dayName} end" />
              <button type="button" class="staff-day-remove" data-win-remove aria-label="Remove time block">×</button>
            </div>`,
          )
          .join("")
      : '<span class="staff-day-unavailable">Unavailable</span>';
    return `
      <div class="staff-day-row ${isOpen ? "is-open" : ""}" data-weekday="${weekday}">
        <div class="staff-day-head">
          <label class="staff-day-toggle">
            <input type="checkbox" data-day-toggle ${isOpen ? "checked" : ""} aria-label="${dayName} available" />
            <span class="staff-day-name">${dayName}</span>
          </label>
          ${isOpen ? `<button type="button" class="ghost-button staff-day-copy" data-copy-day>Copy to all days</button>` : ""}
        </div>
        <div class="staff-day-windows">${blocks}</div>
        ${isOpen ? `<button type="button" class="ghost-button staff-add-window" data-add-window>+ Add time</button>` : ""}
      </div>`;
  }).join("");
}

async function renderRules() {
  try {
    scheduleRules = await api.getMyAvailabilityRules();
  } catch (error) {
    return;
  }
  buildWeeklyWindows();
  renderWeeklyEditor();
  renderDashboardCalendar();
}

async function saveWeekday(weekday) {
  try {
    await api.setMyAvailabilityWeekday(weekday, weeklyWindows[weekday] || []);
    setFeedback("Schedule updated.", "success");
  } catch (error) {
    setFeedback(error?.message || "Could not update your schedule.", "error");
  }
  await renderRules();
}

async function copyDayToAllDays(weekday) {
  const source = (weeklyWindows[weekday] || []).map((w) => ({ ...w }));
  if (!source.length) {
    setFeedback("Add some hours to this day first, then copy them.", "error");
    return;
  }
  try {
    for (let day = 0; day < 7; day += 1) {
      weeklyWindows[day] = source.map((w) => ({ ...w }));
      await api.setMyAvailabilityWeekday(day, weeklyWindows[day]);
    }
    setFeedback(`Copied ${WEEKDAYS[weekday]}'s hours to every day.`, "success");
  } catch (error) {
    setFeedback(error?.message || "Could not copy those hours.", "error");
  }
  await renderRules();
}

async function renderExceptions() {
  const list = el("staff-exceptions-list");
  if (!list) return;
  try {
    scheduleExceptions = await api.getMyAvailabilityExceptions();
  } catch (error) {
    return;
  }
  list.innerHTML = scheduleExceptions.length
    ? scheduleExceptions
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
  renderDashboardCalendar();
}

function showGate() {
  el("staff-dashboard-gate")?.classList.remove("hidden");
  el("staff-dashboard-body")?.classList.add("hidden");
}

function showBody() {
  el("staff-dashboard-gate")?.classList.add("hidden");
  el("staff-dashboard-body")?.classList.remove("hidden");
}

async function loadStaffDashboard(profile) {
  dashboardMode = "staff";
  showBody();
  applyDashboardMode(profile);
  const title = el("staff-dashboard-title");
  if (title) title.textContent = `${profile.name}'s dashboard`;
  const subtitle = el("staff-dashboard-subtitle");
  if (subtitle) {
    subtitle.textContent = profile.schedule_published
      ? "You're a studio engineer — edit your profile and manage your schedule below. Your schedule is published, so customers can request to book you."
      : "You're a studio engineer — edit your profile and manage your schedule and booking requests below. An admin publishes your schedule to make it public.";
  }
  populateProfileForm(profile);
  await Promise.all([renderRequests(), renderRules(), renderExceptions()]);
}

function loadApplicantDashboard(profile) {
  dashboardMode = "applicant";
  showBody();
  const title = el("staff-dashboard-title");
  if (title) title.textContent = "Become a studio engineer";
  const subtitle = el("staff-dashboard-subtitle");
  if (subtitle) subtitle.textContent = "Build your profile and submit it for admin review.";
  if (profile) {
    populateProfileForm(profile);
  } else {
    headshotUrls = [];
    renderHeadshots();
  }
  applyDashboardMode(profile);
}

async function loadDashboard() {
  // Approved staff use the full portal; everyone else gets the applicant flow.
  try {
    const profile = await api.getMyStaffProfile();
    await loadStaffDashboard(profile);
    return;
  } catch (error) {
    /* not an approved staff member — fall through to applicant/gate */
  }
  try {
    const application = await api.getMyStaffApplication();
    loadApplicantDashboard(application.profile);
  } catch (error) {
    // Not logged in (or no access) — show the gate prompting login/signup.
    showGate();
  }
}

export function initStaffDashboardView() {
  if (CURRENT_PAGE !== "staff-dashboard") return;

  el("staff-dashboard-month-grid")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-staff-dashboard-date]");
    if (!button) return;
    dashboardSelectedDate = button.dataset.staffDashboardDate || dashboardSelectedDate;
    dashboardCalendarMonth = firstOfMonth(dashboardSelectedDate);
    renderDashboardCalendar();
  });

  el("staff-dashboard-prev-month")?.addEventListener("click", () => {
    const date = new Date(`${dashboardCalendarMonth}T00:00:00`);
    date.setMonth(date.getMonth() - 1);
    dashboardCalendarMonth = `${date.toISOString().slice(0, 7)}-01`;
    renderDashboardCalendar();
  });

  el("staff-dashboard-next-month")?.addEventListener("click", () => {
    const date = new Date(`${dashboardCalendarMonth}T00:00:00`);
    date.setMonth(date.getMonth() + 1);
    dashboardCalendarMonth = `${date.toISOString().slice(0, 7)}-01`;
    renderDashboardCalendar();
  });

  document.querySelectorAll("[data-staff-calendar-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.staffCalendarAction;
      try {
        button.disabled = true;
        if (action === "available") {
          const fullDayBlocks = exceptionsForDate(dashboardSelectedDate).filter(
            (item) => !item.is_available && item.start_minute == null && item.end_minute == null,
          );
          for (const block of fullDayBlocks) {
            await api.deleteMyAvailabilityException(block.id);
          }
          await api.createMyAvailabilityException({
            exception_date: dashboardSelectedDate,
            is_available: true,
            start_minute: 720,
            end_minute: 1200,
            reason: "Available",
          });
          setFeedback("Selected day is available from 12 PM to 8 PM.", "success");
        } else if (action === "blocked") {
          await api.createMyAvailabilityException({
            exception_date: dashboardSelectedDate,
            is_available: false,
            start_minute: null,
            end_minute: null,
            reason: "Unavailable",
          });
          setFeedback("Selected day marked unavailable.", "success");
        }
        await renderExceptions();
      } catch (error) {
        setFeedback(error?.message || "Could not update that day.", "error");
      } finally {
        button.disabled = false;
      }
    });
  });

  el("staff-profile-headshots-file")?.addEventListener("change", async (event) => {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    setProfileFeedback("Uploading portfolio photos…");
    try {
      const upload = dashboardMode === "applicant" ? api.uploadMyApplicationPhoto : api.uploadMyStaffPhoto;
      for (const file of files) {
        const result = await upload(file);
        if (result?.photo_url) headshotUrls.push(result.photo_url);
      }
      renderHeadshots();
      setProfileFeedback("Headshots added — remember to save.", "success");
    } catch (error) {
      setProfileFeedback(error?.message || "Could not upload that photo.", "error");
    } finally {
      input.value = "";
    }
  });

  el("staff-profile-headshots-list")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-headshot-remove]");
    if (!button) return;
    headshotUrls.splice(Number(button.dataset.headshotRemove), 1);
    renderHeadshots();
  });

  el("staff-profile-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const applicant = dashboardMode === "applicant";
    setProfileFeedback(null);
    try {
      let photoUrl = el("staff-profile-photo-url")?.value || null;
      const file = el("staff-profile-photo-file")?.files?.[0];
      if (file) {
        const upload = applicant ? await api.uploadMyApplicationPhoto(file) : await api.uploadMyStaffPhoto(file);
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
        gear: form.elements.gear.value.trim() || null,
        portfolio_url: form.elements.portfolio_url.value.trim() || null,
        headshot_urls: headshotUrls,
        notification_email: form.elements.notification_email.value.trim() || null,
        notification_phone: form.elements.notification_phone.value.trim() || null,
        notify_by_email: form.elements.notify_by_email.checked,
        notify_by_sms: form.elements.notify_by_sms.checked,
        photo_url: photoUrl,
      };
      const fileField = el("staff-profile-photo-file");
      if (fileField) fileField.value = "";
      if (applicant) {
        const result = await api.submitMyStaffApplication(payload);
        loadApplicantDashboard(result.profile);
        setProfileFeedback("Application submitted — an admin will review it.", "success");
      } else {
        const updated = await api.updateMyStaffProfile(payload);
        populateProfileForm(updated);
        const title = el("staff-dashboard-title");
        if (title) title.textContent = `${updated.name}'s dashboard`;
        setProfileFeedback("Profile saved.", "success");
      }
    } catch (error) {
      setProfileFeedback(error?.message || "Could not save your profile.", "error");
    }
  });

  const editorEl = el("staff-weekly-editor");
  editorEl?.addEventListener("change", async (event) => {
    const row = event.target.closest(".staff-day-row");
    if (!row) return;
    const weekday = Number(row.dataset.weekday);
    if (event.target.matches("[data-day-toggle]")) {
      weeklyWindows[weekday] = event.target.checked ? [{ ...DEFAULT_WINDOW }] : [];
      await saveWeekday(weekday);
      return;
    }
    if (event.target.matches("[data-win-start], [data-win-end]")) {
      const block = event.target.closest(".staff-day-window");
      const index = Number(block.dataset.index);
      const start = timeToMinutes(block.querySelector("[data-win-start]").value);
      const end = timeToMinutes(block.querySelector("[data-win-end]").value);
      if (start == null || end == null || start >= end) {
        setFeedback("Each block needs a start time before its end time.", "error");
        await renderRules();
        return;
      }
      weeklyWindows[weekday][index] = { start_minute: start, end_minute: end };
      await saveWeekday(weekday);
    }
  });

  editorEl?.addEventListener("click", async (event) => {
    const row = event.target.closest(".staff-day-row");
    if (!row) return;
    const weekday = Number(row.dataset.weekday);
    if (event.target.closest("[data-add-window]")) {
      if (!weeklyWindows[weekday]) weeklyWindows[weekday] = [];
      weeklyWindows[weekday].push({ ...DEFAULT_WINDOW });
      await saveWeekday(weekday);
    } else if (event.target.closest("[data-win-remove]")) {
      const block = event.target.closest(".staff-day-window");
      weeklyWindows[weekday].splice(Number(block.dataset.index), 1);
      await saveWeekday(weekday);
    } else if (event.target.closest("[data-copy-day]")) {
      await copyDayToAllDays(weekday);
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
      dashboardSelectedDate = payload.exception_date || dashboardSelectedDate;
      dashboardCalendarMonth = firstOfMonth(dashboardSelectedDate);
      form.reset();
      syncExceptionFormToSelectedDate();
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
