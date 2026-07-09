import { api } from "../api.js";
import { downloadBookingCalendarFile } from "../calendar.js";
import { downloadBookingReceiptPdf } from "../receipt.js";
import { getSearchParam } from "../config.js";
import { elements, toggleHidden } from "../dom.js";
import {
  getPersistedLastBookingId,
  persistCheckoutDraft,
  persistLastBookingId,
  setState,
  state,
} from "../state.js";

let paypalButtonsInstance = null;
let paypalSdkPromise = null;
let googlePayScriptPromise = null;
let activePaymentSession = null;
let paymentDeadlineTimer = null;
let reloadBookingDetailAction = null;
// Reschedule UI is temporarily hidden (admin-only panel was too messy). Flip to
// true to bring back the "Reschedule this booking" panel on the detail page;
// all the wiring below is intact.
const RESCHEDULE_ENABLED = false;
let rescheduleAvailability = null;
let rescheduleBookingId = null;
let rescheduleDateValue = "";
let rescheduleLoading = false;
let rescheduleStatusMessage = "";
let rescheduleRequestToken = 0;
let autoLoadingPaymentBookingId = null;
let confirmPaymentInFlight = false;

function getBookingPaymentAlertEl() {
  let alertEl = document.getElementById("booking-payment-alert");
  if (alertEl) return alertEl;
  const panel = document.getElementById("booking-payment-panel");
  if (!panel) return null;
  alertEl = document.createElement("div");
  alertEl.id = "booking-payment-alert";
  alertEl.className = "booking-payment-alert hidden";
  alertEl.setAttribute("role", "alert");
  const deadline = document.getElementById("booking-payment-deadline");
  panel.insertBefore(alertEl, deadline?.nextSibling || panel.firstChild);
  return alertEl;
}

function showBookingPaymentAlert(message) {
  const alertEl = getBookingPaymentAlertEl();
  if (!alertEl) return;
  alertEl.textContent = message;
  alertEl.classList.remove("hidden");
}

function clearBookingPaymentAlert() {
  const alertEl = document.getElementById("booking-payment-alert");
  if (!alertEl) return;
  alertEl.classList.add("hidden");
  alertEl.textContent = "";
}

function humanizePaymentError(raw) {
  const message = String(raw || "").trim();
  if (!message) return "Payment didn't go through. Please try again.";
  if (/card was declined|card_declined|generic_decline/i.test(message)) {
    return "Your card was declined. Try a different card or contact your bank.";
  }
  if (/insufficient[_ ]funds/i.test(message)) {
    return "There weren't enough funds available on that card. Try a different card.";
  }
  if (/incorrect[_ ](cvc|number)/i.test(message)) {
    return "Card details look incorrect. Double-check the number, expiry, and CVC.";
  }
  if (/expired[_ ]card/i.test(message)) {
    return "That card has expired. Try a different card.";
  }
  if (/PaymentIntent.*already.*confirmed|already been confirmed/i.test(message)) {
    return "This payment was already submitted — refreshing your booking status now.";
  }
  if (/payment window expired|no longer.*pending/i.test(message)) {
    return "The 5-minute payment window already passed. Start a new booking to try again.";
  }
  return message;
}
let paymentSessionStatus = "idle";
let paymentSessionMessage = "";
let bookingContactDraftId = null;
let bookingContactDraft = null;
let contactSaveInFlight = false;

const BOOKING_VISUALS = {
  recording: "/assets/media/placeholder-carousel-3.jpg",
  podcast: "/assets/media/placeholder-carousel-2.jpg",
  photography: "/assets/media/placeholder-carousel-1.jpg",
  film: "/assets/media/studio-photo-editing.jpg",
  dance: "/assets/media/studio-conference-room.jpg",
  production: "/assets/media/placeholder-carousel-3.jpg",
};

function getBookingKind(booking) {
  const explicitKind = String(booking?.booking_kind || booking?.kind || "").toLowerCase();
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

function getBookingLocationLabel(booking) {
  if (getBookingKind(booking) === "staff") {
    return booking?.location_label || "Studio support session";
  }
  return booking?.location_label || "Downtown studio district";
}

function getBookingStaffEntity(booking) {
  if (getBookingKind(booking) !== "staff") {
    return null;
  }
  return (
    booking?.staff_profile ||
    booking?.staff ||
    (booking?.staff_name
      ? {
          name: booking.staff_name,
          description: booking.staff_description || booking.description || "Booked staff session",
          photo_url: booking.staff_photo_url || booking.photo_url || null,
          skills: booking.staff_skills || booking.skills || [],
          talents: booking.staff_talents || booking.talents || [],
          add_on_price_cents: booking.price_cents || booking.total_cents || 0,
        }
      : null)
  );
}

function getBookingVisual(booking) {
  if (getBookingKind(booking) === "staff" && (booking?.staff_photo_url || booking?.photo_url)) {
    return booking.staff_photo_url || booking.photo_url;
  }
  const category = inferBookingCategory(booking);
  return BOOKING_VISUALS[category] || BOOKING_VISUALS.recording;
}

function formatBookingDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "full",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatCurrency(cents, currency) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "CAD",
  }).format((cents || 0) / 100);
}

function formatCountdown(seconds) {
  const safeSeconds = Math.max(0, seconds || 0);
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatDuration(minutes) {
  const hours = minutes / 60;
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

function parseRescheduleAvailabilityStarts(payload) {
  const durationMap = payload?.max_duration_minutes_by_start || {};
  const rawStarts =
    payload?.available_start_times ||
    payload?.available_slots ||
    payload?.slots ||
    payload?.times ||
    [];

  return rawStarts
    .map((slot) => {
      if (typeof slot === "string") {
        return {
          value: slot,
          maxDurationMinutes: Number(durationMap[slot] || 0),
        };
      }

      const value = slot?.value || slot?.start_time || slot?.start || slot?.time || "";
      if (!value || slot?.available === false) {
        return null;
      }

      return {
        value,
        maxDurationMinutes: Number(slot.max_duration_minutes || slot.maxDurationMinutes || durationMap[value] || 0),
      };
    })
    .filter(Boolean);
}

function getValidRescheduleStarts(booking) {
  return parseRescheduleAvailabilityStarts(rescheduleAvailability).filter(
    (slot) => slot.maxDurationMinutes >= Number(booking?.duration_minutes || 0) && slot.value !== booking?.start_time,
  );
}

function formatShortDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
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

function formatTimeRange(startValue, endValue) {
  return `${formatTimeOnly(startValue)} to ${formatTimeOnly(endValue)}`;
}

function formatDateLine(value) {
  return new Intl.DateTimeFormat("en-CA", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatTimeLine(startValue, endValue) {
  const formatter = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${formatter.format(new Date(startValue))} to ${formatter.format(new Date(endValue))}`;
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

function isUnconfirmedStaffRequest(booking) {
  return (
    getBookingKind(booking) === "staff" &&
    booking.status === "Requested" &&
    !booking.customer_confirmed_at
  );
}

function getBookingPrimaryKicker(booking) {
  if (isUnconfirmedStaffRequest(booking)) {
    return "Confirm your request";
  }
  if (booking.status === "AcceptedPendingPayment" && (booking.price_cents || 0) <= 0) {
    return "Confirm your booking";
  }
  if (booking.status === "PendingPayment") {
    return "Secure checkout";
  }
  if (booking.status === "Paid") {
    return "Confirmed booking";
  }
  if (booking.status === "Completed") {
    return "Completed session";
  }
  return "Booking";
}

function getBookingPrimaryTitle(booking) {
  const kind = getBookingKind(booking);
  if (isUnconfirmedStaffRequest(booking)) {
    return "Review & send your booking request";
  }
  if (booking.status === "AcceptedPendingPayment" && (booking.price_cents || 0) <= 0) {
    return "Your request was accepted — confirm to book";
  }
  if (booking.status === "PendingPayment") {
    return kind === "staff" ? "Complete your staff booking" : "Complete your booking";
  }
  if (booking.status === "Paid") {
    return kind === "staff" ? "Your staff booking is confirmed" : "Your booking is confirmed";
  }
  if (booking.status === "Completed") {
    return kind === "staff" ? "Your completed staff booking" : "Your completed booking";
  }
  if (booking.status === "Cancelled") {
    return "This booking was cancelled";
  }
  if (booking.status === "Refunded") {
    return "This booking was refunded";
  }
  return "Manage your booking";
}

function getBookingStatusLabel(booking) {
  if (isUnconfirmedStaffRequest(booking)) {
    return "Awaiting your confirmation";
  }
  return String(booking.status || "Booking").replace(/([a-z])([A-Z])/g, "$1 $2");
}

function getBookingLayoutElements() {
  return {
    kicker: document.getElementById("booking-detail-kicker"),
    contact: document.getElementById("booking-detail-contact"),
    overviewStatus: document.getElementById("booking-overview-status"),
    sessionOverview: document.getElementById("booking-session-overview"),
    summaryRoom: document.getElementById("booking-summary-room"),
    summaryMedia: document.getElementById("booking-summary-media"),
    summaryMeta: document.getElementById("booking-summary-meta"),
    summaryPricing: document.getElementById("booking-summary-pricing"),
    summarySupport: document.getElementById("booking-summary-support"),
  };
}

function getDateInputValue(value) {
  return String(value || "").split("T")[0] || new Date().toISOString().slice(0, 10);
}

function isAdminWaivedPayment(booking) {
  return booking.price_cents === 0 && String(booking.payment_intent_id || "").startsWith("admin_waived_");
}

function isAdminManualPayment(booking) {
  return String(booking.payment_intent_id || "").startsWith("admin_manual_paid_");
}

function isCheckoutMode(booking) {
  return booking?.status === "PendingPayment";
}

function buildPaymentSuccessUrl(bookingId, kind = null) {
  const successUrl = new URL("/payment-success", window.location.origin);
  successUrl.searchParams.set("id", bookingId);
  if (String(kind || "").toLowerCase() === "staff") {
    successUrl.searchParams.set("kind", "staff");
  }
  return successUrl;
}

function renderBookingEmptyState(currentState) {
  const resumeBookingId = getPersistedLastBookingId();
  const requestedKind = String(getSearchParam("kind") || "").toLowerCase();
  const defaultBrowseHref = requestedKind === "staff" ? "/staff" : "/rooms";
  const primaryHref = resumeBookingId ? `/booking?id=${resumeBookingId}` : defaultBrowseHref;
  const primaryLabel = resumeBookingId ? "Resume checkout" : requestedKind === "staff" ? "Browse staff" : "Browse studios";
  const secondaryHref = currentState.currentUser ? "/bookings" : "/account";
  const secondaryLabel = currentState.currentUser ? "My bookings" : "Sign in";
  const fallbackCopy = resumeBookingId
    ? "Your booking is ready — complete payment to secure your session."
    : requestedKind === "staff"
      ? "Browse our staff directory and choose someone to get started."
      : "Browse our studios and pick a room to get started.";
  const message = currentState.message && currentState.message !== "Ready." ? currentState.message : fallbackCopy;

  if (elements.bookingEmptyTitle) {
    elements.bookingEmptyTitle.textContent = resumeBookingId
      ? "Ready to complete your booking?"
      : currentState.currentUser
        ? requestedKind === "staff"
          ? "Choose a staff member to get started"
          : "Choose a studio to get started"
        : "Sign in or continue as a guest to book";
  }
  if (elements.bookingEmptyCopy) {
    elements.bookingEmptyCopy.textContent = message;
  }
  if (elements.bookingEmptyPrimaryLink) {
    elements.bookingEmptyPrimaryLink.href = primaryHref;
    elements.bookingEmptyPrimaryLink.textContent = primaryLabel;
  }
  if (elements.bookingEmptySecondaryLink) {
    elements.bookingEmptySecondaryLink.href = secondaryHref;
    elements.bookingEmptySecondaryLink.textContent = secondaryLabel;
  }
}

function renderStaffImage(photoUrl, label) {
  const safeLabel = escapeHtml(label || "Staff");
  if (photoUrl) {
    return `<img class="staff-profile-image" src="${escapeHtml(photoUrl)}" alt="${safeLabel}" loading="lazy" />`;
  }
  return `<div class="staff-profile-image staff-avatar-fallback">${safeLabel.slice(0, 1).toUpperCase()}</div>`;
}

function renderTagGroup(label, values = []) {
  if (!values.length) {
    return "";
  }

  const visibleValues = values.slice(0, 3);
  const hiddenCount = values.length - visibleValues.length;

  return `
    <div class="staff-tag-group">
      <span>${escapeHtml(label)}</span>
      <div class="preview-pill-row">
        ${visibleValues.map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join("")}
        ${hiddenCount > 0 ? `<span class="pill">+${hiddenCount} more</span>` : ""}
      </div>
    </div>
  `;
}

function renderSummaryLine(label, value) {
  return `<div class="summary-line"><span>${label}</span><strong>${value}</strong></div>`;
}

function idsMatch(left, right) {
  return left !== null && left !== undefined && right !== null && right !== undefined && String(left) === String(right);
}

function renderReadonlyField(label, value, className = "") {
  return `
    <label class="booking-contact-field ${className}">
      <span>${label}</span>
      <div class="booking-contact-value">${value || "Not provided"}</div>
    </label>
  `;
}

function normalizeContactValue(value) {
  const cleaned = String(value || "").trim();
  return cleaned || "";
}

function getPublicContactEmail(booking) {
  const email = normalizeContactValue(booking?.user_email);
  return email.endsWith("@guest.studiobooking.local") ? "" : email;
}

function getInitialContactDraft(booking) {
  return {
    full_name: normalizeContactValue(booking?.user_full_name),
    email: getPublicContactEmail(booking),
    phone: normalizeContactValue(booking?.user_phone),
    note: normalizeContactValue(booking?.note),
  };
}

function getBookingContactDraft(booking) {
  if (!booking) {
    return { full_name: "", email: "", phone: "", note: "" };
  }
  const bookingId = String(booking.id || "");
  if (bookingContactDraftId !== bookingId || !bookingContactDraft) {
    bookingContactDraftId = bookingId;
    bookingContactDraft = getInitialContactDraft(booking);
  }
  return bookingContactDraft;
}

function renderContactInputField(label, name, value, className = "", type = "text") {
  return `
    <label class="booking-contact-field ${className}">
      <span>${escapeHtml(label)}</span>
      <input
        class="booking-contact-value"
        type="${escapeHtml(type)}"
        name="${escapeHtml(name)}"
        value="${escapeHtml(value)}"
        autocomplete="${name === "full_name" ? "name" : name === "email" ? "email" : name === "phone" ? "tel" : "off"}"
      />
    </label>
  `;
}

function renderContactTextareaField(label, name, value, className = "") {
  return `
    <label class="booking-contact-field ${className}">
      <span>${escapeHtml(label)}</span>
      <textarea class="booking-contact-value booking-contact-textarea" name="${escapeHtml(name)}" rows="2">${escapeHtml(value)}</textarea>
    </label>
  `;
}

function readBookingContactForm() {
  const contactRoot = document.getElementById("booking-detail-contact");
  if (!contactRoot) {
    return null;
  }
  return {
    full_name: normalizeContactValue(contactRoot.querySelector("[name='full_name']")?.value),
    email: normalizeContactValue(contactRoot.querySelector("[name='email']")?.value),
    phone: normalizeContactValue(contactRoot.querySelector("[name='phone']")?.value),
    note: normalizeContactValue(contactRoot.querySelector("[name='note']")?.value),
  };
}

function updateContactDraftFromForm() {
  const values = readBookingContactForm();
  if (!values || !state.selectedBooking) {
    return null;
  }
  bookingContactDraftId = String(state.selectedBooking.id || "");
  bookingContactDraft = values;
  return values;
}

async function saveBookingIntakeToNote() {
  const booking = state.selectedBooking;
  if (!booking) return;
  const emergency = document.getElementById("booking-emergency-contact")?.value?.trim();
  const minority = document.getElementById("booking-visible-minority")?.value;
  const city = document.getElementById("booking-city")?.value?.trim();
  const intakeLines = [];
  if (emergency) intakeLines.push(`Emergency contact: ${emergency}`);
  if (minority) intakeLines.push(`Visible minority: ${minority}`);
  if (city) intakeLines.push(`City: ${city}`);
  if (!intakeLines.length) return;
  const existingNote = (booking.note || "").replace(/^(Emergency contact:|Visible minority:|City:)[^\n]*\n?/gm, "").trim();
  const combined = [...intakeLines, ...(existingNote ? [existingNote] : [])].join("\n").slice(0, 500);
  const kind = getBookingKind(booking);
  const updated = kind === "staff"
    ? await api.updateStaffBookingContact(booking.id, { note: combined })
    : await api.updateBookingContact(booking.id, { note: combined });
  setState({ selectedBooking: { ...booking, ...updated } });
}

async function saveBookingContactDetails({ silent = false } = {}) {
  const booking = state.selectedBooking;
  if (!booking || contactSaveInFlight) {
    return booking;
  }
  const values = updateContactDraftFromForm() || getBookingContactDraft(booking);
  contactSaveInFlight = true;
  try {
    if (!silent) {
      setState({ message: "Saving contact information..." });
    }
    const updatedBooking =
      getBookingKind(booking) === "staff"
        ? await api.updateStaffBookingContact(booking.id, values)
        : await api.updateBookingContact(booking.id, values);
    bookingContactDraftId = String(updatedBooking.id || booking.id || "");
    bookingContactDraft = getInitialContactDraft(updatedBooking);
    contactSaveInFlight = false;
    setState({
      selectedBooking: {
        ...booking,
        ...updatedBooking,
      },
      message: silent ? state.message : "Contact information saved.",
    });
    return updatedBooking;
  } finally {
    contactSaveInFlight = false;
  }
}

function clearPaymentElement() {
  if (paypalButtonsInstance) {
    try {
      paypalButtonsInstance.close();
    } catch (error) {
      // The buttons may already be detached; nothing to clean up.
    }
    paypalButtonsInstance = null;
  }
  const paymentContainer = elements.bookingPaymentElement || document.getElementById("booking-payment-element");
  if (paymentContainer) {
    paymentContainer.innerHTML = "";
  }
  const wallets = document.getElementById("booking-wallets");
  if (wallets) {
    wallets.innerHTML = "";
    wallets.classList.add("hidden");
  }
  activePaymentSession = null;
  autoLoadingPaymentBookingId = null;
  paymentSessionStatus = "idle";
  paymentSessionMessage = "";
}

function clearPaymentDeadlineTimer() {
  if (paymentDeadlineTimer) {
    window.clearInterval(paymentDeadlineTimer);
    paymentDeadlineTimer = null;
  }
}

function getPaymentDeadlineElement() {
  return document.getElementById("booking-payment-deadline");
}

function renderPaymentDeadline(booking) {
  const deadlineElement = getPaymentDeadlineElement();
  if (!deadlineElement) {
    return;
  }

  clearPaymentDeadlineTimer();

  if (booking.status !== "PendingPayment" || !booking.payment_expires_at) {
    deadlineElement.classList.add("hidden");
    deadlineElement.textContent = "";
    return;
  }

  const updateCountdown = () => {
    const secondsRemaining = Math.max(
      0,
      Math.floor((new Date(booking.payment_expires_at).getTime() - Date.now()) / 1000),
    );
    deadlineElement.classList.remove("hidden");
    deadlineElement.className = "panel-copy payment-deadline-note";

    const PAY_DISABLE_BUFFER_SECONDS = 30;
    // Lock the PayPal buttons just before the hold expires so the customer
    // doesn't start a payment that lands after the booking is released.
    const paymentContainer = elements.bookingPaymentElement || document.getElementById("booking-payment-element");
    if (paymentContainer) {
      const shouldLock = secondsRemaining > 0 && secondsRemaining <= PAY_DISABLE_BUFFER_SECONDS;
      paymentContainer.style.pointerEvents = shouldLock ? "none" : "";
      paymentContainer.style.opacity = shouldLock ? "0.5" : "";
    }

    if (secondsRemaining <= PAY_DISABLE_BUFFER_SECONDS) {
      deadlineElement.classList.add("payment-deadline-note-urgent");
      deadlineElement.textContent = `Your hold expires at ${formatBookingDate(booking.payment_expires_at)}. Time left: ${formatCountdown(secondsRemaining)} — please don't start a new payment now.`;
    } else {
      deadlineElement.classList.remove("payment-deadline-note-urgent");
      deadlineElement.textContent = `This spot is saved until ${formatBookingDate(booking.payment_expires_at)}. Time left: ${formatCountdown(secondsRemaining)}.`;
    }

    if (secondsRemaining <= 0) {
      clearPaymentDeadlineTimer();
      if (reloadBookingDetailAction) {
        void reloadBookingDetailAction("Your 5-minute payment window expired.");
      }
    }
  };

  updateCountdown();
  paymentDeadlineTimer = window.setInterval(updateCountdown, 1000);
}

async function loadPaymentSession(booking) {
  const session =
    getBookingKind(booking) === "staff"
      ? await api.getStaffBookingPaymentSession(booking.id)
      : await api.getBookingPaymentSession(booking.id);
  activePaymentSession = session;
  return session;
}

function injectPayPalSdk(clientId, currency, components) {
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams({
      "client-id": clientId,
      currency: (currency || "CAD").toUpperCase(),
      intent: "capture",
      components,
    });
    const script = document.createElement("script");
    script.src = `https://www.paypal.com/sdk/js?${params.toString()}`;
    script.onload = () => {
      if (window.paypal?.Buttons) {
        resolve(window.paypal);
      } else {
        reject(new Error("PayPal checkout failed to initialise"));
      }
    };
    script.onerror = () => reject(new Error("Unable to load PayPal checkout. Check your connection and try again."));
    document.head.appendChild(script);
  });
}

function loadPayPalSdk(clientId, currency) {
  if (window.paypal?.Buttons) {
    return Promise.resolve(window.paypal);
  }
  if (!paypalSdkPromise) {
    // Load the wallet components alongside Buttons. If the merchant isn't
    // enabled for a wallet the combined script can fail to load, so fall back
    // to a buttons-only SDK — the core PayPal button must always work.
    paypalSdkPromise = injectPayPalSdk(clientId, currency, "buttons,googlepay,applepay").catch(() => {
      return injectPayPalSdk(clientId, currency, "buttons").catch((err) => {
        paypalSdkPromise = null;
        throw err;
      });
    });
  }
  return paypalSdkPromise;
}

function loadGooglePayScript() {
  if (window.google?.payments?.api) {
    return Promise.resolve();
  }
  if (!googlePayScriptPromise) {
    googlePayScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://pay.google.com/gp/p/js/pay.js";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => { googlePayScriptPromise = null; reject(new Error("Google Pay failed to load")); };
      document.head.appendChild(script);
    });
  }
  return googlePayScriptPromise;
}

// Renders a Google Pay button if the merchant + device are eligible. Returns
// true when a button was rendered. Never throws to the caller.
async function mountGooglePay(paypal, session, booking, container) {
  if (!container || typeof paypal.Googlepay !== "function") return false;
  const gp = paypal.Googlepay();
  const config = await gp.config();
  if (!config?.isEligible) return false;
  await loadGooglePayScript();
  const environment = session.paypal_env === "live" ? "PRODUCTION" : "TEST";
  const client = new window.google.payments.api.PaymentsClient({ environment });
  const ready = await client.isReadyToPay({
    apiVersion: config.apiVersion,
    apiVersionMinor: config.apiVersionMinor,
    allowedPaymentMethods: config.allowedPaymentMethods,
  });
  if (!ready?.result) return false;

  const onClick = async () => {
    if (confirmPaymentInFlight) return;
    clearBookingPaymentAlert();
    try {
      const paymentData = await client.loadPaymentData({
        apiVersion: config.apiVersion,
        apiVersionMinor: config.apiVersionMinor,
        allowedPaymentMethods: config.allowedPaymentMethods,
        merchantInfo: config.merchantInfo,
        transactionInfo: {
          currencyCode: session.currency_code || (booking?.currency || "CAD"),
          totalPriceStatus: "FINAL",
          totalPrice: session.amount_value || "0.00",
        },
      });
      confirmPaymentInFlight = true;
      const confirm = await gp.confirmOrder({
        orderId: session.payment_intent_id,
        paymentMethodData: paymentData.paymentMethodData,
      });
      if (confirm?.status === "APPROVED") {
        await capturePaymentAfterApproval(session);
      } else {
        throw new Error("Google Pay could not complete this payment. Please use the PayPal button.");
      }
    } catch (error) {
      // User dismissing the sheet reports a benign CANCELED/statusCode error.
      if (error?.statusCode === "CANCELED") return;
      showBookingPaymentAlert(humanizePaymentError(error?.message || String(error || "")));
    } finally {
      confirmPaymentInFlight = false;
    }
  };

  const button = client.createButton({
    onClick,
    buttonType: "pay",
    buttonSizeMode: "fill",
    buttonColor: "black",
  });
  container.appendChild(button);
  return true;
}

// Renders an Apple Pay button if the merchant + device (Safari) are eligible.
// Returns true when a button was rendered. Never throws to the caller.
async function mountApplePay(paypal, session, booking, container) {
  if (!container || typeof paypal.Applepay !== "function") return false;
  if (!window.ApplePaySession || !window.ApplePaySession.canMakePayments()) return false;
  const ap = paypal.Applepay();
  const config = await ap.config();
  if (!config?.isEligible) return false;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "wallet-apple-pay-button";
  button.setAttribute("aria-label", "Pay with Apple Pay");

  button.addEventListener("click", () => {
    if (confirmPaymentInFlight) return;
    clearBookingPaymentAlert();
    const paymentRequest = {
      countryCode: config.countryCode || "CA",
      currencyCode: session.currency_code || (booking?.currency || "CAD"),
      merchantCapabilities: config.merchantCapabilities,
      supportedNetworks: config.supportedNetworks,
      // A studio session is a service — no shipping/billing address is collected.
      total: {
        label: "BIPOC Creative Innovation Studio",
        type: "final",
        amount: session.amount_value || "0.00",
      },
    };
    const appleSession = new window.ApplePaySession(4, paymentRequest);
    appleSession.onvalidatemerchant = (event) => {
      ap.validateMerchant({ validationUrl: event.validationURL, displayName: "BIPOC Creative Innovation Studio" })
        .then((result) => appleSession.completeMerchantValidation(result.merchantSession))
        .catch((error) => {
          appleSession.abort();
          showBookingPaymentAlert(humanizePaymentError(error?.message || "Apple Pay could not start."));
        });
    };
    appleSession.onpaymentauthorized = async (event) => {
      confirmPaymentInFlight = true;
      try {
        await ap.confirmOrder({
          orderId: session.payment_intent_id,
          token: event.payment.token,
          billingContact: event.payment.billingContact,
        });
        appleSession.completePayment(window.ApplePaySession.STATUS_SUCCESS);
        await capturePaymentAfterApproval(session);
      } catch (error) {
        appleSession.completePayment(window.ApplePaySession.STATUS_FAILURE);
        showBookingPaymentAlert(humanizePaymentError(error?.message || "Apple Pay payment failed."));
      } finally {
        confirmPaymentInFlight = false;
      }
    };
    appleSession.begin();
  });

  container.appendChild(button);
  return true;
}

// Best-effort: render the Apple Pay / Google Pay express buttons above the
// PayPal button. Any failure is swallowed so the PayPal button is unaffected.
async function mountExpressWallets(paypal, session, booking, paymentContainer) {
  let wrap = document.getElementById("booking-wallets");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = "booking-wallets";
    wrap.className = "booking-wallets hidden";
    paymentContainer.parentNode?.insertBefore(wrap, paymentContainer);
  }
  wrap.innerHTML =
    '<div id="booking-applepay" class="wallet-slot"></div>' +
    '<div id="booking-googlepay" class="wallet-slot"></div>' +
    '<div class="booking-wallets-divider"><span>or</span></div>';

  let rendered = false;
  try {
    if (await mountApplePay(paypal, session, booking, document.getElementById("booking-applepay"))) rendered = true;
  } catch (error) {
    /* Apple Pay unavailable — fall through to PayPal button. */
  }
  try {
    if (await mountGooglePay(paypal, session, booking, document.getElementById("booking-googlepay"))) rendered = true;
  } catch (error) {
    /* Google Pay unavailable — fall through to PayPal button. */
  }
  wrap.classList.toggle("hidden", !rendered);
}

async function capturePaymentAfterApproval(session) {
  // Persist intake + contact details first so the confirmation email and the
  // staff notification carry them, mirroring the old pre-payment save.
  await saveBookingIntakeToNote().catch(() => {});
  await saveBookingContactDetails({ silent: true }).catch(() => {});
  setState({ message: "Confirming payment..." });
  const kind = getBookingKind(state.selectedBooking);
  if (kind === "staff") {
    await api.captureStaffBookingPayment(session.booking_id);
  } else {
    await api.captureBookingPayment(session.booking_id);
  }
  window.location.assign(buildPaymentSuccessUrl(session.booking_id, kind).toString());
}

async function mountPayPalButtons(session, booking) {
  const paymentContainer = elements.bookingPaymentElement || document.getElementById("booking-payment-element");
  if (!paymentContainer) {
    throw new Error("Payment form container is missing");
  }
  if (!session?.payment_intent_id) {
    throw new Error("PayPal order is missing for this booking");
  }
  if (!session.paypal_client_id) {
    throw new Error("PayPal is not configured on the server");
  }

  const paypal = await loadPayPalSdk(session.paypal_client_id, booking?.currency);
  clearPaymentElement();
  toggleHidden(paymentContainer, false);

  const buttons = paypal.Buttons({
    style: { layout: "vertical", label: "pay", height: 48 },
    // The order is created server-side when the payment session loads.
    createOrder: () => session.payment_intent_id,
    onApprove: async () => {
      if (confirmPaymentInFlight) {
        return;
      }
      confirmPaymentInFlight = true;
      clearBookingPaymentAlert();
      try {
        await capturePaymentAfterApproval(session);
      } catch (error) {
        showBookingPaymentAlert(humanizePaymentError(error?.message));
        setState({ message: error?.message || "Payment confirmation failed" });
      } finally {
        confirmPaymentInFlight = false;
      }
    },
    onCancel: () => {
      setState({ message: "PayPal checkout was cancelled — you can try again whenever you're ready." });
    },
    onError: (error) => {
      showBookingPaymentAlert(humanizePaymentError(error?.message || String(error || "")));
    },
  });
  await buttons.render(paymentContainer);
  paypalButtonsInstance = buttons;
  activePaymentSession = session;
  paymentSessionStatus = "ready";
  paymentSessionMessage = "Secure PayPal checkout is ready.";

  // Add the Apple Pay / Google Pay express buttons above the PayPal button.
  // Fully best-effort: if wallet setup fails the PayPal button still stands.
  mountExpressWallets(paypal, session, booking, paymentContainer).catch(() => {});
}

async function ensurePaymentSession(booking) {
  if (
    !booking ||
    !isCheckoutMode(booking) ||
    idsMatch(activePaymentSession?.booking_id, booking.id) ||
    idsMatch(autoLoadingPaymentBookingId, booking.id)
  ) {
    return;
  }

  autoLoadingPaymentBookingId = booking.id;
  paymentSessionStatus = "loading";
  paymentSessionMessage = "Preparing the secure PayPal checkout...";
  let nextMessage = "";
  try {
    const session = await loadPaymentSession(booking);
    if (session.payment_backend === "paypal") {
      await mountPayPalButtons(session, booking);
      nextMessage = "Secure payment is ready.";
    } else if (session.payment_backend === "free") {
      // Nothing due now (e.g. a 100%-off promo) — the customer just confirms.
      clearPaymentElement();
      toggleHidden(elements.bookingPaymentElement, true);
      activePaymentSession = session;
      paymentSessionStatus = "free";
      paymentSessionMessage = "This booking is fully covered — no payment needed. Confirm to lock it in.";
      nextMessage = paymentSessionMessage;
    } else {
      toggleHidden(elements.bookingPaymentElement, true);
      paymentSessionStatus = "stub";
      paymentSessionMessage =
        "Online payment is not active for this running server. Start the API with PAYMENT_BACKEND=paypal and configured PayPal credentials to show the PayPal checkout.";
      nextMessage = paymentSessionMessage;
    }
  } catch (error) {
    paymentSessionStatus = "error";
    paymentSessionMessage = error.message || "Unable to load the payment form right now.";
    nextMessage = paymentSessionMessage;
  } finally {
    autoLoadingPaymentBookingId = null;
    if (nextMessage) {
      setState({ message: nextMessage });
    }
  }
}

function renderPaymentPanel(state, booking) {
  if (!elements.bookingPaymentPanel || !elements.bookingPaymentCopy || !elements.bookingPaymentControls) {
    return;
  }

  const isPending = booking.status === "PendingPayment";
  const bookingKind = getBookingKind(booking);
  const canAdminWaivePayment = isPending && Boolean(state.currentUser?.is_admin);
  const canAdminMarkPaid = canAdminWaivePayment && booking.price_cents > 0;
  toggleHidden(elements.bookingPaymentPanel, !isPending);
  if (!isPending) {
    elements.bookingPaymentControls.innerHTML = "";
    clearPaymentElement();
    return;
  }

  const hasPayPalSession =
    idsMatch(activePaymentSession?.booking_id, booking.id) && activePaymentSession.payment_backend === "paypal";
  // Nothing due now (e.g. a 100%-off promo): confirm for free instead of paying.
  const isFreeSession =
    idsMatch(activePaymentSession?.booking_id, booking.id) && activePaymentSession.payment_backend === "free";
  const isPaymentLoading = idsMatch(autoLoadingPaymentBookingId, booking.id) || paymentSessionStatus === "loading";
  elements.bookingPaymentCopy.textContent = hasPayPalSession
    ? "Pay securely with PayPal below — you can use your PayPal balance or a card."
    : isFreeSession
      ? "This booking is fully covered — no payment needed. Confirm to lock it in."
      : isPaymentLoading
        ? "Loading secure payment..."
        : paymentSessionMessage || "Complete payment to confirm your studio session.";
  const primaryDisabled = isPaymentLoading ? "disabled" : "";
  // price_cents > 0 exactly matches "an amount is due now" (the deposit is
  // capped at the total, so a $0 total means a $0 — free — booking).
  const primaryAction = isFreeSession ? "confirm-free" : "load-payment";
  const primaryLabel = isFreeSession || booking.price_cents === 0 ? "Confirm booking" : "Pay now";
  elements.bookingPaymentControls.innerHTML = `
    ${
      hasPayPalSession
        ? ""
        : `<button class="primary-button" type="button" data-booking-detail-action="${primaryAction}" data-booking-id="${booking.id}" ${primaryDisabled}>
      ${primaryLabel}
    </button>`
    }
    ${
      canAdminMarkPaid
        ? `<button class="ghost-button" type="button" data-booking-detail-action="mark-paid" data-booking-id="${booking.id}" data-booking-kind="${bookingKind}">
      Mark paid manually as admin
    </button>`
        : ""
    }
    ${
      canAdminWaivePayment
        ? `<button class="ghost-button" type="button" data-booking-detail-action="waive-payment" data-booking-id="${booking.id}" data-booking-kind="${bookingKind}">
      Skip payment as admin
    </button>`
        : ""
    }
  `;

  if (idsMatch(activePaymentSession?.booking_id, booking.id)) {
    if (activePaymentSession.payment_backend !== "paypal") {
      elements.bookingPaymentCopy.textContent =
        paymentSessionMessage ||
        "Online payment is not active for this running server. Start the API with PAYMENT_BACKEND=paypal and configured PayPal credentials to show the PayPal checkout.";
    }
  } else {
    toggleHidden(elements.bookingPaymentElement, true);
  }
}

async function loadRescheduleAvailability(booking, targetDate) {
  if (!booking || !targetDate) {
    return;
  }

  const requestToken = rescheduleRequestToken + 1;
  rescheduleRequestToken = requestToken;
  const bookingId = booking.id;
  rescheduleBookingId = booking.id;
  rescheduleDateValue = targetDate;
  rescheduleLoading = true;
  rescheduleAvailability = null;
  rescheduleStatusMessage = "Loading available start times...";
  setState({ message: state.message });

  try {
    let nextAvailability = null;
    if (getBookingKind(booking) === "staff") {
      const staffId = booking.staff_profile_id || booking.staff_id || booking.staff_profile?.id;
      if (!staffId) {
        throw new Error("This staff booking does not include a staff profile id.");
      }
      nextAvailability = await api.getStaffAvailability(staffId, targetDate).catch(() => null);
    } else {
      nextAvailability = await api.getAvailability(booking.room_id, targetDate);
    }

    if (
      requestToken !== rescheduleRequestToken ||
      rescheduleBookingId !== bookingId ||
      rescheduleDateValue !== targetDate
    ) {
      return;
    }

    rescheduleAvailability = nextAvailability;
    const validStarts = getValidRescheduleStarts(booking);
    rescheduleStatusMessage = validStarts.length
      ? `Choose from ${validStarts.length} open start time${validStarts.length === 1 ? "" : "s"} on ${targetDate}.`
      : "No alternate starts are open for this booking duration on that date.";
  } catch (error) {
    if (requestToken !== rescheduleRequestToken) {
      return;
    }

    rescheduleAvailability = null;
    rescheduleStatusMessage = error.message;
  } finally {
    if (requestToken === rescheduleRequestToken) {
      rescheduleLoading = false;
      setState({ message: state.message });
    }
  }
}

function renderReschedulePanel(booking) {
  if (
    !elements.bookingReschedulePanel ||
    !elements.bookingRescheduleDate ||
    !elements.bookingRescheduleStart ||
    !elements.bookingRescheduleStatus ||
    !elements.bookingRescheduleSubmit
  ) {
    return;
  }

  const isAdmin = Boolean(state.currentUser?.is_admin);
  const canReschedule = RESCHEDULE_ENABLED && isAdmin && booking.status === "Paid" && !booking.checked_in_at;
  toggleHidden(elements.bookingReschedulePanel, !canReschedule);
  if (!canReschedule) {
    return;
  }

  const nextDate = rescheduleDateValue || getDateInputValue(booking.start_time);
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (elements.bookingRescheduleDate.min !== todayKey) {
    elements.bookingRescheduleDate.min = todayKey;
  }
  if (elements.bookingRescheduleDate.value !== nextDate) {
    elements.bookingRescheduleDate.value = nextDate;
  }

  if (rescheduleBookingId !== booking.id || rescheduleDateValue !== nextDate) {
    void loadRescheduleAvailability(booking, nextDate);
  }

  const validStarts = getValidRescheduleStarts(booking);
  elements.bookingRescheduleStart.innerHTML = validStarts.length
    ? validStarts
        .map(
          (slot) => `
            <option value="${slot.value}">
              ${formatBookingDate(slot.value)}
            </option>
          `,
        )
        .join("")
    : '<option value="">No alternate times available</option>';
  elements.bookingRescheduleSubmit.disabled = rescheduleLoading || !validStarts.length;
  elements.bookingRescheduleStatus.textContent = rescheduleLoading
    ? "Loading available start times..."
    : rescheduleStatusMessage ||
      `Move this booking to a different start time while keeping the same ${formatDuration(booking.duration_minutes)} duration.`;
}

function renderStaffAssignments(booking) {
  if (!elements.bookingDetailStaffList) {
    return;
  }

  const assignments =
    getBookingKind(booking) === "staff"
      ? [getBookingStaffEntity(booking)].filter(Boolean)
      : booking.staff_assignments || [];
  elements.bookingDetailStaffList.innerHTML = assignments.length
    ? assignments
        .map((assignment) => {
          const assignmentName = assignment.name || "Studio staff";
          const assignmentDescription =
            assignment.description ||
            (getBookingKind(booking) === "staff" ? "Booked staff session" : "Attached to this booking as an add-on.");
          return `
            <article class="booking-staff-card booking-staff-card-compact staff-profile-card">
              <div class="booking-staff-card-top booking-staff-card-top-compact staff-profile-card-top">
                ${renderStaffImage(assignment.photo_url, assignmentName)}
                <div class="booking-staff-card-copy">
                  <strong>${escapeHtml(assignmentName)}</strong>
                  <span>${escapeHtml(assignmentDescription)}</span>
                </div>
                <strong class="booking-staff-card-price staff-option-price">${formatCurrency(assignment.add_on_price_cents, booking.currency)}</strong>
              </div>
              <div class="booking-staff-card-tags">
                ${renderTagGroup("Skills", assignment.skills || [])}
                ${renderTagGroup("Talents", assignment.talents || [])}
              </div>
            </article>
          `;
        })
        .join("")
    : '<div class="empty-state">No extra staff add-ons were attached to this booking.</div>';
}

function renderCheckoutPricingRows(booking, kind, staffTotal) {
  const originalTotal = Number(booking.original_price_cents ?? booking.price_cents ?? 0);
  const discountCents = Number(booking.discount_cents || 0);
  const taxCents = Number(booking.tax_cents || 0);
  const finalTotal = Number(booking.price_cents || 0);
  const gstLine = taxCents > 0
    ? `<div class="booking-summary-price-line"><span>GST (5%)</span><strong>${formatCurrency(taxCents, booking.currency)}</strong></div>`
    : "";
  // Staff bookings are request-based — no "Free" service fee line for them.
  const serviceFeeLine = kind === "staff"
    ? ""
    : `<div class="booking-summary-price-line"><span>Service fee</span><strong class="booking-summary-price-free">Free</strong></div>`;

  // Public bookings only collect the deposit (+ GST on it) up front; the rest is
  // owed later. Mirror backend upfront_charge_cents: fall back to the full total
  // when no deposit is configured.
  const depositCents = Number(booking.deposit_amount_cents || 0);
  // Deposit is capped at the (post-discount) total — mirrors backend
  // upfront_charge_cents. A 100%-off promo makes the total $0, so nothing is
  // due now; a total under the deposit is simply paid in full now.
  const depositChargeCents = depositCents > 0
    ? Math.min(depositCents + Math.floor(depositCents * 0.05), finalTotal)
    : finalTotal;
  const balanceCents = Math.max(0, finalTotal - depositChargeCents);
  let settlementRows = "";
  if (kind !== "staff" && depositCents > 0 && depositChargeCents > 0) {
    if (booking.status === "PendingPayment") {
      settlementRows = `
        <div class="booking-summary-price-line booking-summary-due-now"><span>Deposit due now</span><strong>${formatCurrency(depositChargeCents, booking.currency)}</strong></div>
        ${balanceCents > 0 ? `<div class="booking-summary-price-line booking-summary-balance"><span>Balance due at studio</span><strong>${formatCurrency(balanceCents, booking.currency)}</strong></div>` : ""}`;
    } else if (booking.status === "DepositPaid") {
      settlementRows = `
        <div class="booking-summary-price-line booking-summary-due-now"><span>Deposit paid</span><strong class="booking-summary-price-free">${formatCurrency(depositChargeCents, booking.currency)}</strong></div>
        ${balanceCents > 0 ? `<div class="booking-summary-price-line booking-summary-balance"><span>Balance due at studio</span><strong>${formatCurrency(balanceCents, booking.currency)}</strong></div>` : ""}`;
    }
  }

  if (discountCents > 0) {
    return `
      <div class="booking-summary-price-line"><span>${kind === "staff" ? "Staff session" : "Session subtotal"}</span><strong>${formatCurrency(originalTotal, booking.currency)}</strong></div>
      <div class="booking-summary-price-line"><span>Promo ${escapeHtml(booking.promo_code || "")}</span><strong class="booking-summary-price-free">-${formatCurrency(discountCents, booking.currency)}</strong></div>
      ${serviceFeeLine}
      ${gstLine}
      <div class="booking-summary-total"><span>Total</span><strong>${formatCurrency(finalTotal, booking.currency)}</strong></div>
      ${settlementRows}
    `;
  }

  if (kind === "staff") {
    return `
      <div class="booking-summary-price-line"><span>Staff session</span><strong>${formatCurrency(finalTotal, booking.currency)}</strong></div>
      ${serviceFeeLine}
      ${gstLine}
      <div class="booking-summary-total"><span>Total</span><strong>${formatCurrency(finalTotal, booking.currency)}</strong></div>
    `;
  }

  const roomSubtotal = Math.max(0, finalTotal - staffTotal - taxCents);
  return `
    <div class="booking-summary-price-line"><span>${formatCurrency(roomSubtotal, booking.currency)} room session</span><strong>${formatCurrency(roomSubtotal, booking.currency)}</strong></div>
    ${
      staffTotal
        ? `<div class="booking-summary-price-line"><span>Staff add-ons</span><strong>${formatCurrency(staffTotal, booking.currency)}</strong></div>`
        : ""
    }
    ${serviceFeeLine}
    ${gstLine}
    <div class="booking-summary-total"><span>Total</span><strong>${formatCurrency(finalTotal, booking.currency)}</strong></div>
    ${settlementRows}
  `;
}

function renderBookingSummaryLayout(booking) {
  const layout = getBookingLayoutElements();
  const kind = getBookingKind(booking);
  const bookingTitle = getBookingDisplayName(booking);
  const roomName = booking.room_name || "Studio booking";
  const staffTotal = (booking.staff_assignments || []).reduce(
    (sum, assignment) => sum + Number(assignment.add_on_price_cents || 0),
    0,
  );
  const statusLabel = getBookingStatusLabel(booking);
  const staffCount = (booking.staff_assignments || []).length;
  const contactDraft = getBookingContactDraft(booking);
  const supportCopy =
    booking.status === "PendingPayment"
      ? "Complete payment below to secure your studio session."
      : booking.status === "Paid"
        ? "Your session is confirmed. Add it to your calendar or download your receipt below."
        : "Your booking history and receipt are available below.";

  if (layout.kicker) {
    layout.kicker.textContent = getBookingPrimaryKicker(booking);
  }
  if (layout.overviewStatus) {
    layout.overviewStatus.textContent = statusLabel;
    layout.overviewStatus.className = `pill status-${String(booking.status || "").toLowerCase()}`;
  }

  if (
    layout.contact &&
    layout.sessionOverview &&
    layout.summaryRoom &&
    layout.summaryMeta &&
    layout.summaryPricing &&
    layout.summarySupport &&
    layout.summaryMedia
  ) {
    const category = inferBookingCategory(booking);
    const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);
    const visual = getBookingVisual(booking);
    const typeLabel = getBookingTypeLabel(booking);

    layout.contact.innerHTML = `
      ${renderContactInputField("Full name", "full_name", contactDraft.full_name, "booking-contact-field-full")}
      ${renderContactInputField("Email", "email", contactDraft.email, "", "email")}
      ${renderContactInputField("Phone", "phone", contactDraft.phone, "", "tel")}
      ${renderContactTextareaField("Notes for the studio (optional)", "note", contactDraft.note, "booking-contact-field-full")}
      <div class="booking-contact-actions booking-contact-field-full">
        <button class="ghost-button" type="button" data-booking-contact-save ${contactSaveInFlight ? "disabled" : ""}>
          ${contactSaveInFlight ? "Saving..." : "Save contact information"}
        </button>
      </div>
    `;

    layout.sessionOverview.innerHTML = `
      ${renderSummaryLine(kind === "staff" ? "Staff" : "Room", bookingTitle)}
      ${renderSummaryLine("Date", formatDateLine(booking.start_time))}
      ${renderSummaryLine("Time", formatTimeLine(booking.start_time, booking.end_time))}
      ${renderSummaryLine("Duration", formatDuration(booking.duration_minutes))}
      ${booking.promo_code ? renderSummaryLine("Promo", `${booking.promo_code} saved ${formatCurrency(booking.discount_cents, booking.currency)}`) : ""}
      ${renderSummaryLine("Booking code", booking.booking_code)}
      ${
        booking.payment_intent_id
          ? renderSummaryLine("Payment reference", booking.payment_intent_id)
          : renderSummaryLine("Payment status", statusLabel)
      }
    `;

    layout.summaryRoom.textContent = bookingTitle;
    layout.summaryMedia.innerHTML = `
      <div class="booking-summary-room-card">
        <div class="booking-summary-room-copy">
          <div class="booking-summary-room-pills">
            <span class="pill">${typeLabel}</span>
            <span class="pill">${categoryLabel}</span>
            <span class="pill status-${String(booking.status || "").toLowerCase()}">${statusLabel}</span>
          </div>
          <strong>${bookingTitle}</strong>
          <span>${getBookingLocationLabel(booking)}</span>
        </div>
      </div>
    `;
    layout.summaryMeta.innerHTML = `
      ${renderSummaryLine("Date", formatDateLine(booking.start_time))}
      ${renderSummaryLine("Time", `${formatTimeOnly(booking.start_time)} • ${formatDuration(booking.duration_minutes)}`)}
      ${
        kind === "staff"
          ? renderSummaryLine("Service", booking.service_type || "Staff session")
          : renderSummaryLine("Staff", `${staffCount} add-on${staffCount === 1 ? "" : "s"}`)
      }
    `;
    layout.summaryPricing.innerHTML = renderCheckoutPricingRows(booking, kind, staffTotal);
    layout.summarySupport.innerHTML = `
      <div class="booking-summary-support-item">${supportCopy}</div>
    `;
    return;
  }

}

export function initBookingDetailView(actions) {
  if (!elements.bookingDetailActions) {
    return;
  }

  reloadBookingDetailAction = actions?.reloadBookingDetail || null;

  const handleAction = async (event) => {
    const button = event.target.closest("[data-booking-detail-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.bookingDetailAction;

    try {
      if (action === "cancel") {
        const confirmed = window.confirm("Are you sure you want to cancel this booking?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Cancelling booking..." });
        const booking = await api.cancelBooking(button.dataset.bookingId, { reason: "Cancelled by user" });
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking cancelled." });
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Booking detail refreshed.");
        }
        return;
      }

      if (action === "confirm-free-staff") {
        setState({ message: "Confirming your booking..." });
        const booking = await api.confirmFreeStaffBooking(button.dataset.bookingId);
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking confirmed." });
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Booking confirmed.");
        }
        return;
      }

      if (action === "confirm-free") {
        // A fully-discounted room booking ($0 due now): confirm without payment.
        if (confirmPaymentInFlight) return;
        confirmPaymentInFlight = true;
        clearBookingPaymentAlert();
        try {
          await saveBookingIntakeToNote().catch(() => {});
          await saveBookingContactDetails({ silent: true }).catch(() => {});
          setState({ message: "Confirming your booking..." });
          const confirmed = await api.confirmFreeBooking(button.dataset.bookingId);
          clearPaymentElement();
          window.location.assign(
            buildPaymentSuccessUrl(confirmed.id, getBookingKind(state.selectedBooking)).toString(),
          );
        } catch (error) {
          showBookingPaymentAlert(humanizePaymentError(error?.message));
          setState({ message: error?.message || "Could not confirm the booking." });
        } finally {
          confirmPaymentInFlight = false;
        }
        return;
      }

      if (action === "confirm-staff-request") {
        const selected = state.selectedBooking;
        const staffName = selected?.staff_profile?.name || selected?.staff_name || "this staff member";
        if (!window.confirm(`Send your booking request to ${staffName}? They'll be notified and have 48 hours to respond.`)) {
          return;
        }
        // Save the contact details so the staff member has them, then send.
        await saveBookingContactDetails({ silent: true });
        setState({ message: "Sending your request..." });
        const booking = await api.confirmStaffBookingRequest(button.dataset.bookingId);
        setState({ selectedBooking: booking, message: "Request sent." });
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Request sent — the staff member has been notified.");
        }
        return;
      }

      if (action === "load-payment") {
        setState({ message: "Loading payment session..." });
        const booking =
          state.selectedBooking && String(state.selectedBooking.id) === String(button.dataset.bookingId)
            ? state.selectedBooking
            : await api.getBooking(button.dataset.bookingId);
        await ensurePaymentSession(booking);
        if (actions?.reloadBookingDetail) {
          await actions.reloadBookingDetail("Payment session ready.");
        }
        return;
      }

      if (action === "waive-payment") {
        const confirmed = window.confirm("Skip payment and mark this booking free?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Skipping payment and marking booking free..." });
        const booking =
          button.dataset.bookingKind === "staff"
            ? await api.adminWaiveStaffBookingPayment(button.dataset.bookingId)
            : await api.adminWaiveBookingPayment(button.dataset.bookingId);
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking marked free." });
        window.location.assign(buildPaymentSuccessUrl(booking.id, button.dataset.bookingKind).toString());
        return;
      }

      if (action === "mark-paid") {
        const confirmed = window.confirm("Mark this booking paid manually?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Marking booking paid manually..." });
        const booking =
          button.dataset.bookingKind === "staff"
            ? await api.adminMarkStaffBookingPaid(button.dataset.bookingId)
            : await api.adminMarkBookingPaid(button.dataset.bookingId);
        clearPaymentElement();
        setState({ selectedBooking: booking, message: "Booking marked paid manually." });
        window.location.assign(buildPaymentSuccessUrl(booking.id, button.dataset.bookingKind).toString());
        return;
      }

      if (action === "check-in") {
        const confirmed = window.confirm("Mark this guest as arrived and complete the session?");
        if (!confirmed) {
          return;
        }
        setState({ message: "Marking guest as arrived..." });
        const booking = await api.adminCheckInBooking(button.dataset.bookingId);
        if (reloadBookingDetailAction) {
          await reloadBookingDetailAction("Guest checked in.");
        } else {
          setState({ selectedBooking: booking, message: "Guest checked in." });
        }
        return;
      }

      if (action === "admin-refund") {
        const amount = Number(button.dataset.amount || 0);
        const amountLabel = formatCurrency(amount, state.selectedBooking?.currency || "CAD");
        const confirmed = window.confirm(`Process a ${amountLabel} refund? This changes payment records.`);
        if (!confirmed) {
          return;
        }
        setState({ message: "Processing refund..." });
        await api.adminRefundBooking(button.dataset.bookingId, {
          amount_cents: amount,
          reason: "Admin refund",
        });
        if (reloadBookingDetailAction) {
          await reloadBookingDetailAction("Refund processed.");
        } else {
          setState({ message: "Refund processed." });
        }
        return;
      }

      if (action === "download-calendar") {
        const booking = await api.getBooking(button.dataset.bookingId);
        downloadBookingCalendarFile(booking);
        setState({ message: "Calendar file downloaded." });
        return;
      }

      if (action === "download-receipt") {
        const booking = await api.getBooking(button.dataset.bookingId);
        await downloadBookingReceiptPdf(booking.id, booking.booking_code);
        setState({ message: "Receipt PDF downloaded." });
        return;
      }
    } catch (error) {
      setState({ message: error.message });
    }
  };

  elements.bookingDetailActions.addEventListener("click", handleAction);
  elements.bookingPaymentControls?.addEventListener("click", handleAction);
  document.getElementById("booking-detail-contact")?.addEventListener("input", () => {
    updateContactDraftFromForm();
  });
  document.getElementById("booking-detail-contact")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-booking-contact-save]");
    if (!button) {
      return;
    }
    try {
      await saveBookingContactDetails();
    } catch (error) {
      setState({ message: error.message });
    }
  });
  elements.bookingRescheduleDate?.addEventListener("change", () => {
    if (!state.selectedBooking) {
      return;
    }
    void loadRescheduleAvailability(state.selectedBooking, elements.bookingRescheduleDate.value);
  });
  elements.bookingRescheduleSubmit?.addEventListener("click", async () => {
    const selectedStart = elements.bookingRescheduleStart?.value || "";
    const validStarts = state.selectedBooking ? getValidRescheduleStarts(state.selectedBooking) : [];
    const canUseStart = validStarts.some((slot) => slot.value === selectedStart);
    if (!state.selectedBooking || rescheduleLoading || !selectedStart || !canUseStart) {
      setState({ message: "Choose a new start time before rescheduling." });
      return;
    }

    try {
      setState({ message: "Rescheduling booking..." });
      const booking =
        getBookingKind(state.selectedBooking) === "staff"
          ? await api.rescheduleStaffBooking(state.selectedBooking.id, { start_time: selectedStart })
          : await api.rescheduleBooking(state.selectedBooking.id, { start_time: selectedStart });
      rescheduleRequestToken += 1;
      rescheduleAvailability = null;
      rescheduleBookingId = null;
      rescheduleDateValue = "";
      rescheduleStatusMessage = "";
      setState({ selectedBooking: booking, message: "Booking rescheduled." });
      if (actions?.reloadBookingDetail) {
        await actions.reloadBookingDetail("Booking detail refreshed.");
      }
    } catch (error) {
      setState({ message: error.message });
    }
  });
}

export function renderBookingDetailView(state) {
  if (!elements.bookingDetailEmpty || !elements.bookingDetailCard) {
    return;
  }

  const booking = state.selectedBooking;
  const hasBooking = Boolean(booking);
  const checkoutMode = isCheckoutMode(booking);
  renderBookingEmptyState(state);
  toggleHidden(elements.bookingDetailEmpty, hasBooking);
  toggleHidden(elements.bookingDetailCard, !hasBooking);

  if (!booking) {
    clearPaymentDeadlineTimer();
    clearPaymentElement();
    return;
  }

  persistLastBookingId(booking.id);
  persistCheckoutDraft(
    booking.status === "PendingPayment"
      ? { booking }
      : null,
  );
  elements.bookingDetailCard.classList.toggle("is-checkout-mode", checkoutMode);
  if (elements.bookingDetailTitle) {
    elements.bookingDetailTitle.textContent = checkoutMode
      ? getBookingPrimaryTitle(booking)
      : booking.room_name || getBookingPrimaryTitle(booking);
  }
  if (elements.bookingDetailWindow) {
    elements.bookingDetailWindow.textContent = checkoutMode
      ? "Review your session details and complete payment below."
      : `${formatDateLine(booking.start_time)} • ${formatTimeLine(booking.start_time, booking.end_time)}`;
  }
  if (elements.bookingDetailNote) {
    elements.bookingDetailNote.textContent = booking.note
      ? `Session note: ${booking.note}`
      : booking.status === "PendingPayment"
        ? "Complete payment to secure your studio session."
        : booking.status === "Paid"
          ? "Your session is confirmed — add it to your calendar, download your receipt, or reschedule if needed."
          : "Past sessions are stored here so you can access receipts and review your history.";
  }
  renderBookingSummaryLayout(booking);
  renderStaffAssignments(booking);
  renderPaymentDeadline(booking);

  const isAdmin = Boolean(state.currentUser?.is_admin);
  const bookingKindForActions = getBookingKind(booking);
  const canConfirmFreeStaff =
    bookingKindForActions === "staff" &&
    booking.status === "AcceptedPendingPayment" &&
    (booking.price_cents || 0) <= 0;
  const canConfirmRequest = isUnconfirmedStaffRequest(booking);
  const canCancel = booking.status === "PendingPayment" || booking.status === "Paid";
  const canPay = booking.status === "PendingPayment";
  const canAddToCalendar = ["Paid", "Completed"].includes(booking.status);
  const canDownloadReceipt = ["Paid", "Completed", "Refunded"].includes(booking.status);
  const canAdminCheckIn = isAdmin && booking.status === "Paid" && !booking.checked_in_at && bookingKindForActions !== "staff";
  const canAdminRefund = isAdmin && bookingKindForActions !== "staff" && booking.price_cents > 0 && ["Paid", "Completed", "Cancelled"].includes(booking.status);
  if (elements.bookingDetailActions) {
    elements.bookingDetailActions.innerHTML = `
      ${canConfirmRequest ? `<button class="primary-button" type="button" data-booking-detail-action="confirm-staff-request" data-booking-id="${booking.id}">Confirm &amp; send request</button>` : ""}
      ${canConfirmFreeStaff ? `<button class="primary-button" type="button" data-booking-detail-action="confirm-free-staff" data-booking-id="${booking.id}">Confirm booking</button>` : ""}
      ${canAddToCalendar ? `<button class="ghost-button" type="button" data-booking-detail-action="download-calendar" data-booking-id="${booking.id}">Add to calendar</button>` : ""}
      ${canDownloadReceipt ? `<button class="ghost-button" type="button" data-booking-detail-action="download-receipt" data-booking-id="${booking.id}">Download receipt PDF</button>` : ""}
      ${canAdminCheckIn ? `<button class="ghost-button" type="button" data-booking-detail-action="check-in" data-booking-id="${booking.id}">Mark guest arrived</button>` : ""}
      ${canAdminRefund ? `<button class="ghost-button" type="button" data-booking-detail-action="admin-refund" data-booking-id="${booking.id}" data-amount="${booking.price_cents}">Process refund</button>` : ""}
      ${canCancel ? `<button class="ghost-button" type="button" data-booking-detail-action="cancel" data-booking-id="${booking.id}">Cancel booking</button>` : ""}
    `;
  }
  toggleHidden(elements.bookingSessionPanel, checkoutMode);
  toggleHidden(elements.bookingStaffPanel, checkoutMode);
  toggleHidden(elements.bookingDetailActions, checkoutMode);

  renderPaymentPanel(state, booking);
  renderReschedulePanel(booking);
  if (canPay) {
    void ensurePaymentSession(booking);
  }
}
