const AUTOPLAY_INTERVAL_MS = 6000;
const REAL_STUDIO_VISUALS = {
  Recording: "/assets/media/placeholder-carousel-3.jpg",
  Podcast: "/assets/media/placeholder-carousel-2.jpg",
  Photography: "/assets/media/placeholder-carousel-1.jpg",
  Film: "/assets/media/studio-photo-editing.jpg",
  Dance: "/assets/media/studio-conference-room.jpg",
  Production: "/assets/media/placeholder-carousel-3.jpg",
};

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format((cents || 0) / 100);
}

function inferCategory(room) {
  const text = `${room.name || ""} ${room.description || ""}`.toLowerCase();
  if (text.includes("podcast")) {
    return "Podcast";
  }
  if (text.includes("photo")) {
    return "Photography";
  }
  if (text.includes("film")) {
    return "Film";
  }
  if (text.includes("dance")) {
    return "Dance";
  }
  if (text.includes("production")) {
    return "Production";
  }
  return "Recording";
}

function getFeaturePhoto(room) {
  const category = inferCategory(room);
  return REAL_STUDIO_VISUALS[category] || REAL_STUDIO_VISUALS.Recording;
}

function renderFeaturedRooms(currentState) {
  const container = document.getElementById("home-featured-grid");
  if (!container) {
    return;
  }

  const rooms = (currentState.rooms || []).filter((room) => room.active !== false).slice(0, 6);
  if (!rooms.length) {
    container.innerHTML = '<div class="empty-state">Featured studios will appear here once rooms are available.</div>';
    return;
  }

  container.innerHTML = rooms
    .map((room) => {
      const photo = getFeaturePhoto(room);
      const category = inferCategory(room);
      return `
        <article class="home-studio-card">
          <a class="home-studio-card-link" href="/room?id=${room.id}">
            <div class="home-studio-card-media">
              ${
                photo
                  ? `<img class="home-studio-card-image" src="${photo}" alt="${room.name}" loading="lazy" onerror="this.onerror=null;this.src='${REAL_STUDIO_VISUALS[category] || REAL_STUDIO_VISUALS.Recording}';" />`
                  : '<div class="room-card-placeholder">No room image yet.</div>'
              }
              <div class="home-studio-card-badges">
                <span class="home-card-pill home-card-pill-dark">${category}</span>
                <span class="home-card-pill">${room.active ? "Available" : "Booked"}</span>
              </div>
            </div>
            <div class="home-studio-card-copy">
              <div class="home-studio-card-heading">
                <h3>${room.name}</h3>
                <span class="home-studio-card-rating">★ 4.9</span>
              </div>
              <div class="home-studio-card-meta">
                <span>Up to ${room.capacity || 4}</span>
                <strong>${formatCurrency(room.hourly_rate_cents)}/hr</strong>
              </div>
            </div>
          </a>
        </article>
      `;
    })
    .join("");
}

function normalizePublicBookingCtas() {
  const homeBookNowLink = document.querySelector(".home-book-now-button");
  if (homeBookNowLink) {
    homeBookNowLink.href = "/rooms";
    homeBookNowLink.textContent = "Book now";
  }

  const pricingBookLinks = Array.from(document.querySelectorAll(".pricing-page-grid a[href='/rooms']"));
  pricingBookLinks.forEach((link) => {
    if (link.classList.contains("hero-primary")) {
      link.textContent = "Book room";
    }
  });
}

function normalizeIndex(index, total) {
  if (!total) {
    return 0;
  }
  return (index + total) % total;
}

export function initHomeView() {
  const carousel = document.querySelector("[data-home-carousel]");
  if (!carousel || carousel.dataset.initialized === "true") {
    return;
  }

  const slides = Array.from(carousel.querySelectorAll("[data-home-slide]"));
  const dotsContainer = carousel.querySelector(".home-carousel-dots");
  if (dotsContainer) {
    dotsContainer.innerHTML = slides
      .map(
        (_, index) =>
          `<button class="home-carousel-dot${index === 0 ? " is-active" : ""}" type="button" data-home-dot aria-current="${
            index === 0 ? "true" : "false"
          }"></button>`,
      )
      .join("");
  }
  const dots = Array.from(carousel.querySelectorAll("[data-home-dot]"));
  const captions = Array.from(carousel.querySelectorAll("[data-home-caption]"));
  const previousButton = carousel.querySelector("[data-home-prev]");
  const nextButton = carousel.querySelector("[data-home-next]");
  const counter = carousel.querySelector("[data-home-counter]");

  if (!slides.length) {
    return;
  }

  carousel.dataset.initialized = "true";

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let activeIndex = slides.findIndex((slide) => slide.classList.contains("is-active"));
  let autoPlayTimer = null;

  if (activeIndex < 0) {
    activeIndex = 0;
  }

  const clearAutoPlay = () => {
    if (autoPlayTimer) {
      window.clearInterval(autoPlayTimer);
      autoPlayTimer = null;
    }
  };

  const render = (nextIndex, { restartAutoPlay = true } = {}) => {
    activeIndex = normalizeIndex(nextIndex, slides.length);

    slides.forEach((slide, index) => {
      const isActive = index === activeIndex;
      slide.classList.toggle("is-active", isActive);
      slide.setAttribute("aria-hidden", String(!isActive));
    });

    dots.forEach((dot, index) => {
      const isActive = index === activeIndex;
      dot.classList.toggle("is-active", isActive);
      dot.setAttribute("aria-current", isActive ? "true" : "false");
    });

    captions.forEach((caption, index) => {
      const isActive = index === activeIndex;
      caption.classList.toggle("is-active", isActive);
      caption.setAttribute("aria-pressed", isActive ? "true" : "false");
    });

    if (counter) {
      counter.textContent = `${activeIndex + 1} / ${slides.length}`;
    }

    if (restartAutoPlay) {
      clearAutoPlay();
      if (!prefersReducedMotion.matches) {
        autoPlayTimer = window.setInterval(() => {
          render(activeIndex + 1, { restartAutoPlay: false });
        }, AUTOPLAY_INTERVAL_MS);
      }
    }
  };

  const moveBy = (offset) => {
    render(activeIndex + offset);
  };

  previousButton?.addEventListener("click", () => moveBy(-1));
  nextButton?.addEventListener("click", () => moveBy(1));

  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => render(index));
  });

  captions.forEach((caption, index) => {
    caption.addEventListener("click", () => render(index));
  });

  const pauseAutoPlay = () => {
    clearAutoPlay();
  };

  const resumeAutoPlay = () => {
    render(activeIndex);
  };

  carousel.addEventListener("mouseenter", pauseAutoPlay);
  carousel.addEventListener("mouseleave", resumeAutoPlay);
  carousel.addEventListener("focusin", pauseAutoPlay);
  carousel.addEventListener("focusout", (event) => {
    if (!carousel.contains(event.relatedTarget)) {
      resumeAutoPlay();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      pauseAutoPlay();
      return;
    }
    resumeAutoPlay();
  });

  render(activeIndex);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderHomeStaffStrip(currentState) {
  const container = document.getElementById("home-staff-strip");
  if (!container) return;

  const profiles = (currentState.publicStaffProfiles || [])
    .filter((p) => p.active !== false)
    .slice(0, 3);

  if (!profiles.length) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = profiles
    .map((p) => {
      const initials = escapeHtml(
        (p.name || "?")
          .split(" ")
          .map((w) => w[0])
          .join("")
          .slice(0, 2)
          .toUpperCase(),
      );
      const avatar = p.photo_url
        ? `<img class="home-staff-card-avatar" src="${escapeHtml(p.photo_url)}" alt="${escapeHtml(p.name)}" loading="lazy" />`
        : `<div class="home-staff-card-avatar home-staff-avatar-fallback">${initials}</div>`;
      const services = (p.service_types || []).slice(0, 2).map(escapeHtml).join(" · ");
      const rate = p.booking_rate_cents
        ? `$${Math.round(p.booking_rate_cents / 100)}/hr`
        : "";
      return `
        <a class="home-staff-card" href="/staff?id=${escapeHtml(p.id)}">
          ${avatar}
          <div class="home-staff-card-body">
            <strong class="home-staff-card-name">${escapeHtml(p.name)}</strong>
            ${services ? `<span class="home-staff-card-role">${services}</span>` : ""}
            ${rate ? `<span class="home-staff-card-rate">${rate}</span>` : ""}
          </div>
        </a>`;
    })
    .join("");
}

export function renderHomeView(currentState) {
  normalizePublicBookingCtas();
  renderFeaturedRooms(currentState);
  renderHomeStaffStrip(currentState);
}
