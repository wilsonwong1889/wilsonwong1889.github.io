// Per-room photo carousel. Every room gets its own slideshow built only from
// that room's uploaded photos — never stock images and never another room's.
//
// Rendering is a plain HTML string so it can be dropped into the existing
// innerHTML-based views, and all interaction is delegated off `document`, so a
// re-render of the studios grid never needs a re-init.

const ROOM_PLACEHOLDER_IMAGE = "/assets/media/room-placeholder.svg";
const SWIPE_THRESHOLD_PX = 40;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function getRoomPhotos(room) {
  const rawPhotos = Array.isArray(room?.photos) ? room.photos : [];
  return rawPhotos.filter(Boolean);
}

/**
 * Build the markup for one room's photo carousel.
 *
 * @param {string[]} photos    That room's own photo URLs, in display order.
 * @param {object}   options
 * @param {string}   options.name        Room name, used for alt text.
 * @param {string}   options.variant     "card" (studios grid) or "detail".
 * @param {string}   options.emptyLabel  Copy shown when the room has no photos.
 * @param {boolean}  options.eagerFirst  Load the first slide eagerly.
 */
export function renderRoomCarousel(photos, options = {}) {
  const { name = "Room", variant = "card", emptyLabel = "No room image yet.", eagerFirst = false } = options;
  const safeName = escapeHtml(name);
  const list = (photos || []).filter(Boolean);

  if (!list.length) {
    return `<div class="room-card-placeholder">${escapeHtml(emptyLabel)}</div>`;
  }

  const slides = list
    .map(
      (photo, index) => `
        <div class="room-carousel-slide${index === 0 ? " is-active" : ""}" data-room-slide role="group" aria-roledescription="slide" aria-label="Photo ${index + 1} of ${list.length}"${index === 0 ? "" : ' aria-hidden="true"'}>
          <img class="room-carousel-image" src="${escapeHtml(photo)}" alt="${safeName} photo ${index + 1}" loading="${index === 0 && eagerFirst ? "eager" : "lazy"}" draggable="false" onerror="this.onerror=null;this.src='${ROOM_PLACEHOLDER_IMAGE}';" />
        </div>
      `,
    )
    .join("");

  // A single photo needs no controls — just show it.
  if (list.length === 1) {
    return `
      <div class="room-carousel room-carousel-${escapeHtml(variant)} is-single" data-room-carousel data-index="0">
        <div class="room-carousel-track" data-room-carousel-track>${slides}</div>
      </div>
    `;
  }

  const dots = list
    .map(
      (_, index) =>
        `<button class="room-carousel-dot${index === 0 ? " is-active" : ""}" type="button" data-room-carousel-dot data-slide-index="${index}" aria-label="Go to photo ${index + 1}" aria-current="${index === 0 ? "true" : "false"}"></button>`,
    )
    .join("");

  return `
    <div class="room-carousel room-carousel-${escapeHtml(variant)}" data-room-carousel data-index="0" role="region" aria-roledescription="carousel" aria-label="${safeName} photos" tabindex="0">
      <div class="room-carousel-track" data-room-carousel-track>${slides}</div>
      <button class="room-carousel-arrow room-carousel-arrow-prev" type="button" data-room-carousel-prev aria-label="Previous photo of ${safeName}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <button class="room-carousel-arrow room-carousel-arrow-next" type="button" data-room-carousel-next aria-label="Next photo of ${safeName}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
      </button>
      <div class="room-carousel-dots" data-room-carousel-dots>${dots}</div>
      <span class="room-carousel-counter" data-room-carousel-counter aria-hidden="true">1 / ${list.length}</span>
    </div>
  `;
}

function getSlides(carousel) {
  return Array.from(carousel.querySelectorAll("[data-room-slide]"));
}

export function goToSlide(carousel, requestedIndex) {
  const slides = getSlides(carousel);
  if (!slides.length) {
    return;
  }

  const total = slides.length;
  const index = ((Number(requestedIndex) || 0) % total + total) % total;
  carousel.dataset.index = String(index);

  const track = carousel.querySelector("[data-room-carousel-track]");
  if (track) {
    track.style.transform = `translate3d(-${index * 100}%, 0, 0)`;
  }

  slides.forEach((slide, slideIndex) => {
    const isActive = slideIndex === index;
    slide.classList.toggle("is-active", isActive);
    if (isActive) {
      slide.removeAttribute("aria-hidden");
    } else {
      slide.setAttribute("aria-hidden", "true");
    }
  });

  carousel.querySelectorAll("[data-room-carousel-dot]").forEach((dot, dotIndex) => {
    const isActive = dotIndex === index;
    dot.classList.toggle("is-active", isActive);
    dot.setAttribute("aria-current", isActive ? "true" : "false");
  });

  const counter = carousel.querySelector("[data-room-carousel-counter]");
  if (counter) {
    counter.textContent = `${index + 1} / ${total}`;
  }

  // Thumbnail rail (room detail page) mirrors the active slide.
  const rail = carousel.parentElement?.querySelector("[data-room-carousel-thumbs]");
  if (rail) {
    rail.querySelectorAll("[data-room-carousel-thumb]").forEach((thumb, thumbIndex) => {
      const isActive = thumbIndex === index;
      thumb.classList.toggle("is-active", isActive);
      thumb.setAttribute("aria-current", isActive ? "true" : "false");
    });
  }
}

function step(carousel, delta) {
  goToSlide(carousel, (Number(carousel.dataset.index) || 0) + delta);
}

let carouselsBound = false;

/**
 * Bind the delegated handlers once per page load. Safe to call repeatedly and
 * safe to call before any carousel exists.
 */
export function bindRoomCarousels() {
  if (carouselsBound) {
    return;
  }
  carouselsBound = true;

  document.addEventListener("click", (event) => {
    const control = event.target?.closest?.(
      "[data-room-carousel-prev], [data-room-carousel-next], [data-room-carousel-dot], [data-room-carousel-thumb]",
    );
    if (!control) {
      return;
    }

    const scope = control.closest("[data-room-carousel-group]") || control.closest("[data-room-carousel]")?.parentElement;
    const carousel = control.closest("[data-room-carousel]") || scope?.querySelector("[data-room-carousel]");
    if (!carousel) {
      return;
    }

    // Room cards sit inside clickable surfaces — never let a photo control
    // bubble up into "open this room" navigation.
    event.preventDefault();
    event.stopPropagation();

    if (control.hasAttribute("data-room-carousel-prev")) {
      step(carousel, -1);
    } else if (control.hasAttribute("data-room-carousel-next")) {
      step(carousel, 1);
    } else {
      goToSlide(carousel, Number(control.dataset.slideIndex) || 0);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    const carousel = event.target.closest?.("[data-room-carousel]");
    if (!carousel || carousel.classList.contains("is-single")) {
      return;
    }
    event.preventDefault();
    step(carousel, event.key === "ArrowRight" ? 1 : -1);
  });

  // Swipe / drag support.
  let dragCarousel = null;
  let dragStartX = 0;
  let dragStartY = 0;

  document.addEventListener(
    "pointerdown",
    (event) => {
      const carousel = event.target.closest?.("[data-room-carousel]");
      if (!carousel || carousel.classList.contains("is-single")) {
        return;
      }
      if (event.target.closest("[data-room-carousel-prev], [data-room-carousel-next], [data-room-carousel-dot]")) {
        return;
      }
      dragCarousel = carousel;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
    },
    { passive: true },
  );

  document.addEventListener(
    "pointerup",
    (event) => {
      if (!dragCarousel) {
        return;
      }
      const carousel = dragCarousel;
      dragCarousel = null;

      const deltaX = event.clientX - dragStartX;
      const deltaY = event.clientY - dragStartY;
      // Ignore mostly-vertical gestures so page scrolling still feels natural.
      if (Math.abs(deltaX) < SWIPE_THRESHOLD_PX || Math.abs(deltaX) < Math.abs(deltaY)) {
        return;
      }
      step(carousel, deltaX < 0 ? 1 : -1);
    },
    { passive: true },
  );

  document.addEventListener("pointercancel", () => {
    dragCarousel = null;
  });
}
