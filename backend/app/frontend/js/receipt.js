import { API_BASE_URL } from "./config.js";
import { state } from "./state.js";

function getDownloadFilename(contentDisposition, fallback) {
  const match = /filename="([^"]+)"/i.exec(contentDisposition || "");
  return match?.[1] || fallback;
}

function isMobileSafariLike() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const isIOS = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
  const isMobileSafari = isIOS && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  return isMobileSafari;
}

export async function downloadBookingReceiptPdf(bookingId, bookingCode = "booking") {
  const headers = new Headers();
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  const response = await fetch(`${API_BASE_URL}/api/bookings/${bookingId}/receipt`, {
    method: "GET",
    headers,
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? payload.detail
        : "Receipt download failed";
    throw new Error(detail);
  }

  const blob = await response.blob();
  const filename = getDownloadFilename(
    response.headers.get("content-disposition"),
    `studio-booking-receipt-${bookingCode}.pdf`,
  );
  const url = window.URL.createObjectURL(blob);

  if (isMobileSafariLike()) {
    // iOS Safari blocks blob downloads via <a download>. Opening in a new tab
    // lets the customer use the native viewer's Share → Save to Files action.
    const win = window.open(url, "_blank");
    if (!win) {
      // Pop-up blocked — fall back to top-level navigation so they still get the file.
      window.location.assign(url);
    }
    window.setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
    return;
  }

  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}
