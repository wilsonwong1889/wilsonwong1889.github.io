import { api } from "../api.js";
import { CURRENT_PAGE } from "../config.js";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// "staff" = approved staff member (full portal); "applicant" = a logged-in user
// who is building/awaiting approval on a studio-engineer application.
let dashboardMode = "staff";
let headshotUrls = [];

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
  if (!isApplicant) {
    setApplicationBanner(null);
    if (heading) heading.textContent = "Profile & details";
    if (subhead) subhead.textContent = "Edit how you appear to customers. Pricing, publishing your schedule, your account link, and studio assignments are managed by an admin.";
    if (submitBtn) submitBtn.textContent = "Save profile";
    return;
  }
  if (heading) heading.textContent = "Your studio engineer profile";
  if (subhead) subhead.textContent = "Fill out your profile — headshots, portfolio, skills, and gear. Submit it and an admin will review and grant you studio engineer access.";
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
      ? "Your schedule is published — customers can request to book you."
      : "Set your availability and respond to requests. An admin publishes your schedule to make it public.";
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

  el("staff-profile-headshots-file")?.addEventListener("change", async (event) => {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    setProfileFeedback("Uploading headshots…");
    try {
      const upload = dashboardMode === "applicant" ? api.uploadMyApplicationPhoto : api.uploadMyStaffPhoto;
      for (const file of files) {
        const result = await upload(file);
        if (result?.photo_url) headshotUrls.push(result.photo_url);
      }
      renderHeadshots();
      setProfileFeedback("Headshots added — remember to save.", "success");
    } catch (error) {
      setProfileFeedback(error?.message || "Could not upload that headshot.", "error");
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
