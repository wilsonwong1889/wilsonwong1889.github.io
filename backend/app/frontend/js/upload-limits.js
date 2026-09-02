// Upload size rules, stated to the person before they pick a file.
//
// The server is the authority — see MAX_PHOTO_BYTES in
// backend/app/core/image_utils.py, which refuses anything larger with a 413.
// This is the early warning, so someone on a phone connection is not made to
// upload 200 MB before being told no. If the server limit changes, change this
// with it; the two are deliberately kept in step.
export const MAX_PHOTO_MB = 40;
export const MAX_PHOTO_BYTES = MAX_PHOTO_MB * 1024 * 1024;

export const PHOTO_HINT = `JPG, PNG, WebP or HEIC · up to ${MAX_PHOTO_MB} MB each`;

function formatMb(bytes) {
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? Math.round(mb) : Math.round(mb * 10) / 10;
}

/** Returns a human-readable problem with these files, or null if they're fine. */
export function photoSelectionError(files) {
  const list = Array.from(files || []);
  if (!list.length) {
    return null;
  }

  const tooBig = list.filter((file) => file.size > MAX_PHOTO_BYTES);
  if (tooBig.length === 1) {
    const file = tooBig[0];
    return `“${file.name}” is ${formatMb(file.size)} MB. Photos must be ${MAX_PHOTO_MB} MB or smaller — try exporting it at a smaller size.`;
  }
  if (tooBig.length > 1) {
    return `${tooBig.length} of your photos are over ${MAX_PHOTO_MB} MB. Photos must be ${MAX_PHOTO_MB} MB or smaller — try exporting them at a smaller size.`;
  }

  const empty = list.filter((file) => file.size === 0);
  if (empty.length) {
    return `“${empty[0].name}” is empty. Pick a photo with content in it.`;
  }

  return null;
}

/**
 * Show the limit under a file input, and flag an over-sized pick immediately.
 *
 * The message appears the moment a file is chosen rather than after a failed
 * upload, and the selection is cleared so a too-large file cannot be submitted
 * by mistake. The server still enforces the same limit — this only saves the
 * round trip.
 */
export function attachPhotoLimit(input) {
  if (!input || input.dataset.photoLimitAttached === "true") {
    return;
  }
  input.dataset.photoLimitAttached = "true";

  const hint = document.createElement("p");
  hint.className = "upload-hint";
  hint.textContent = PHOTO_HINT;

  const error = document.createElement("p");
  error.className = "upload-error hidden";
  error.setAttribute("role", "alert");

  input.insertAdjacentElement("afterend", error);
  input.insertAdjacentElement("afterend", hint);

  input.addEventListener("change", () => {
    const message = photoSelectionError(input.files);
    if (message) {
      error.textContent = message;
      error.classList.remove("hidden");
      // Clear it: a file this size cannot be sent, and leaving it selected
      // makes the form look ready when it is not.
      input.value = "";
    } else {
      error.textContent = "";
      error.classList.add("hidden");
    }
  });
}

/** Attach the limit to every photo input on the page. */
export function attachAllPhotoLimits(root = document) {
  root.querySelectorAll('input[type="file"][accept*="image"]').forEach(attachPhotoLimit);
}
