import { downloadBookingCalendarFile } from "../calendar.js";
import { downloadBookingReceiptPdf } from "../receipt.js";
import { elements, toggleHidden } from "../dom.js";

let reloadPaymentSuccessAction = null;
let paymentSuccessPollTimer = null;
let paymentSuccessPollCount = 0;
let currentPaymentSuccessBooking = null;

function stopPolling() {
  if (paymentSuccessPollTimer) {
    window.clearInterval(paymentSuccessPollTimer);
    paymentSuccessPollTimer = null;
  }
  paymentSuccessPollCount = 0;
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

function isAdminWaivedPayment(booking) {
  const paymentReference = String(booking.payment_intent_id || "");
  return booking.price_cents === 0 && (
    paymentReference.startsWith("admin_waived_") ||
    paymentReference.startsWith("admin_staff_waived_")
  );
}

function isAdminManualPayment(booking) {
  const paymentReference = String(booking.payment_intent_id || "");
  return paymentReference.startsWith("admin_manual_paid_") || paymentReference.startsWith("admin_staff_manual_paid_");
}

function getBookingKind(booking) {
  return String(booking?.booking_kind || booking?.kind || (booking?.staff_profile_id ? "staff" : "room")).toLowerCase();
}

function renderPaymentSuccessSummary(booking) {
  if (!elements.paymentSuccessSummary) {
    return;
  }

  const settlementLine = isAdminWaivedPayment(booking)
    ? "Booking confirmed — no payment required."
    : isAdminManualPayment(booking)
      ? "Payment confirmed by our team."
      : booking.confirmed_at
        ? `Payment confirmed ${formatBookingDate(booking.confirmed_at)}.`
        : "Payment received — confirming your booking now.";
  const bookingKind = getBookingKind(booking);
  const bookingLabel = bookingKind === "staff" ? "Staff" : "Room";
  const bookingName = bookingKind === "staff"
    ? booking.staff_name || booking.staff_profile_name || booking.service_type || "Staff booking"
    : booking.room_name || "Studio booking";

  elements.paymentSuccessSummary.innerHTML = `
    <div class="summary-line"><span>${bookingLabel}</span><strong>${bookingName}</strong></div>
    <div class="summary-line"><span>Starts</span><strong>${formatBookingDate(booking.start_time)}</strong></div>
    <div class="summary-line"><span>Duration</span><strong>${booking.duration_minutes / 60} hour${booking.duration_minutes === 60 ? "" : "s"}</strong></div>
    ${booking.promo_code ? `<div class="summary-line"><span>Promo</span><strong>${booking.promo_code} saved ${formatCurrency(booking.discount_cents, booking.currency)}</strong></div>` : ""}
    <div class="summary-line"><span>Booked at</span><strong>${formatBookingDate(booking.created_at)}</strong></div>
    <div class="summary-line"><span>Settlement</span><strong>${settlementLine}</strong></div>
  `;
}

function getPaymentSuccessTitle(booking, paymentSettled, paymentStillProcessing) {
  if (isAdminWaivedPayment(booking)) {
    return "Booking confirmed";
  }
  if (isAdminManualPayment(booking)) {
    return "Booking confirmed";
  }
  if (paymentSettled) {
    return "You're all booked — see you at the studio!";
  }
  if (paymentStillProcessing) {
    return "Payment received — confirming your booking";
  }
  return `Booking status: ${booking.status}`;
}

function getPaymentSuccessCopy(booking, paymentSettled, paymentStillProcessing) {
  if (isAdminWaivedPayment(booking)) {
    return "Your booking has been confirmed. No payment was required for this session.";
  }
  if (isAdminManualPayment(booking)) {
    return "Your booking has been confirmed and marked as paid. A confirmation email is on its way.";
  }
  if (paymentSettled) {
    return "Your payment went through and your studio session is confirmed. Check your inbox for a confirmation email and calendar invite.";
  }
  if (paymentStillProcessing) {
    return "Payment received — we're just finishing up the confirmation. This page will update automatically, or you can refresh in a moment.";
  }
  return "Your booking has been updated. Review the details below.";
}

function ensurePolling(booking) {
  if (!reloadPaymentSuccessAction || !booking || booking.status !== "PendingPayment") {
    stopPolling();
    return;
  }
  if (paymentSuccessPollTimer) {
    return;
  }

  paymentSuccessPollTimer = window.setInterval(async () => {
    paymentSuccessPollCount += 1;
    await reloadPaymentSuccessAction("Confirming your booking...");
    if (paymentSuccessPollCount >= 10) {
      stopPolling();
      renderPollTimeoutEscalation();
    }
  }, 3000);
}

function renderPollTimeoutEscalation() {
  if (!elements.paymentSuccessActions) return;
  if (document.getElementById("payment-success-escalation")) return;
  const banner = document.createElement("div");
  banner.id = "payment-success-escalation";
  banner.className = "payment-success-escalation";
  banner.innerHTML = `
    <strong>Still confirming.</strong>
    <span>Stripe or our worker may be running slow. Try refreshing — if your booking still isn't confirmed in a few minutes, call <a href="tel:+14033938857">403-393-8857</a> and quote your booking code.</span>
  `;
  const actions = elements.paymentSuccessActions;
  actions.parentNode?.insertBefore(banner, actions);
}

export function initPaymentSuccessView(actions) {
  reloadPaymentSuccessAction = actions?.reloadPaymentSuccess || null;
  elements.paymentSuccessActions?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-payment-success-action]");
    if (!button) {
      return;
    }
    if (button.dataset.paymentSuccessAction === "download-calendar" && currentPaymentSuccessBooking) {
      downloadBookingCalendarFile(currentPaymentSuccessBooking);
      return;
    }
    if (button.dataset.paymentSuccessAction === "download-receipt" && currentPaymentSuccessBooking) {
      await downloadBookingReceiptPdf(currentPaymentSuccessBooking.id, currentPaymentSuccessBooking.booking_code);
      return;
    }
    if (button.dataset.paymentSuccessAction === "refresh-status" && reloadPaymentSuccessAction) {
      await reloadPaymentSuccessAction("Confirming your booking...");
    }
  });
}

export function renderPaymentSuccessView(state) {
  if (!elements.paymentSuccessEmpty || !elements.paymentSuccessCard) {
    return;
  }

  const booking = state.selectedBooking;
  currentPaymentSuccessBooking = booking || null;
  const hasBooking = Boolean(booking);
  toggleHidden(elements.paymentSuccessEmpty, hasBooking);
  toggleHidden(elements.paymentSuccessCard, !hasBooking);

  if (!booking) {
    stopPolling();
    return;
  }

  const paymentSettled = booking.status === "Paid" || booking.status === "Completed";
  const paymentStillProcessing = booking.status === "PendingPayment";
  const bookingKind = getBookingKind(booking);
  const canDownloadReceipt = bookingKind !== "staff" && ["Paid", "Completed", "Refunded"].includes(booking.status);
  const title = getPaymentSuccessTitle(booking, paymentSettled, paymentStillProcessing);
  const copy = getPaymentSuccessCopy(booking, paymentSettled, paymentStillProcessing);
  const bookingHref = `/booking?id=${encodeURIComponent(booking.id)}${bookingKind === "staff" ? "&kind=staff" : ""}`;

  elements.paymentSuccessTitle.textContent = title;
  elements.paymentSuccessCopy.textContent = copy;
  elements.paymentSuccessMeta.innerHTML = `
    <span class="pill">${booking.booking_code}</span>
    <span class="pill">${formatCurrency(booking.price_cents, booking.currency)}</span>
    <span class="pill">${booking.status}</span>
    <span class="pill">${formatBookingDate(booking.start_time)}</span>
  `;
  renderPaymentSuccessSummary(booking);
  const canAddToCalendar = !["PendingPayment", "Cancelled", "Refunded"].includes(booking.status);
  elements.paymentSuccessActions.innerHTML = `
    <a class="primary-button ghost-link" href="${bookingHref}">View booking</a>
    <a class="ghost-button ghost-link" href="/bookings">Back to bookings</a>
    ${canAddToCalendar ? '<button class="ghost-button" type="button" data-payment-success-action="download-calendar">Add to calendar</button>' : ""}
    ${canDownloadReceipt ? '<button class="ghost-button" type="button" data-payment-success-action="download-receipt">Download receipt PDF</button>' : ""}
    ${paymentStillProcessing ? '<button class="ghost-button" type="button" data-payment-success-action="refresh-status">Refresh status</button>' : ""}
  `;

  ensurePolling(booking);
  if (!paymentStillProcessing) {
    stopPolling();
  }
}
