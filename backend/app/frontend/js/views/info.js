import { elements } from "../dom.js";

const FOUNDERS = [
  {
    name: "Creative Founder",
    role: "Founder / Creative Direction",
    summary: "Built the studio around clean production flow, artist comfort, and a booking experience that feels simple from the first click to final session delivery.",
  },
  {
    name: "Operations Founder",
    role: "Founder / Operations",
    summary: "Leads scheduling, guest experience, room readiness, and the operational systems that keep recording, meetings, and production sessions running on time.",
  },
];

const USE_CASES = [
  {
    badge: "1",
    title: "Podcast and interview sessions",
    copy: "A clean, structured room for hosts, guests, and small production teams who need a focused place to record.",
  },
  {
    badge: "2",
    title: "Branded photo and video shoots",
    copy: "Useful for content teams that need a studio backdrop, controlled environment, and a fast setup window.",
  },
  {
    badge: "3",
    title: "Creative planning and client meetings",
    copy: "A professional setting for strategy sessions, presentations, and in-person collaboration without distraction.",
  },
  {
    badge: "4",
    title: "Music and voice capture",
    copy: "Made for artists and creators who want a straightforward space for tracking, rehearsal, and production work.",
  },
];

const AMENITIES = [
  {
    label: "Flexible booking flow",
    value: "Choose a room, reserve the time, and continue as a guest when you do not want to create an account.",
  },
  {
    label: "Support options",
    value: "Add staff help where the room setup calls for it so the session starts with the right level of guidance.",
  },
  {
    label: "Clear pricing",
    value: "Review the room and support details before confirming so the final total is easy to understand.",
  },
  {
    label: "Guest-friendly arrival",
    value: "Arrive with enough buffer to park, check in, and get settled before your booked time begins.",
  },
];

const EXPECTATIONS = [
  {
    badge: "A",
    step: "Start simple",
    copy: "Pick a room that matches the session, then move through the booking without extra steps or friction.",
  },
  {
    badge: "B",
    step: "Know what comes next",
    copy: "The page explains the studio, the booking flow, and the arrival details before you ever leave home.",
  },
  {
    badge: "C",
    step: "Show up prepared",
    copy: "Bring the people and gear you need, then use the setup time you planned for in the booking.",
  },
  {
    badge: "D",
    step: "Leave cleanly",
    copy: "Wrap on time, clear the room, and hand the space back in good shape for the next booking.",
  },
];

const BUILDING_GALLERY = [
  {
    title: "Full building exterior",
    image: "/assets/media/studio-building-exterior.jpg",
    copy: "Use this card for the main exterior shot so guests can recognize the building instantly.",
  },
  {
    title: "Lobby and reception",
    image: "/assets/media/studio-building-lobby.jpg",
    copy: "Our front desk and reception — the first stop when you arrive to check in for your booking.",
  },
  {
    title: "Podcast studio",
    image: "/assets/media/studio-building-signature-room.jpg",
    copy: "A warm, sound-treated room with lounge seating and dual broadcast mics, ready for interviews and conversations.",
  },
  {
    title: "Music production room",
    image: "/assets/media/placeholder-carousel-3.jpg",
    copy: "Studio monitors, a mixing desk, and acoustic treatment for recording, producing, and mixing sessions.",
  },
  {
    title: "Conference room",
    image: "/assets/media/studio-conference-room.jpg",
    copy: "A boardroom-style space for meetings, workshops, and team sessions with seating for six.",
  },
  {
    title: "Photo editing suite",
    image: "/assets/media/studio-photo-editing.jpg",
    copy: "A focused editing station with a large display for reviewing, retouching, and finishing your shoot.",
  },
  {
    title: "Photography backdrop",
    image: "/assets/media/placeholder-carousel-1.jpg",
    copy: "A seamless paper backdrop with lighting stands for portraits, product shots, and content creation.",
  },
  {
    title: "Administration office",
    image: "/assets/media/studio-admin-office.jpg",
    copy: "Our on-site administration and front-of-house area supporting bookings and day-to-day operations.",
  },
];

function renderUseCaseCard(item) {
  return `
    <article class="story-card">
      <span>${item.badge}</span>
      <strong>${item.title}</strong>
      <p>${item.copy}</p>
    </article>
  `;
}

function renderAmenityLine(item) {
  return `
    <div class="summary-line">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
    </div>
  `;
}

function renderExpectationCard(item) {
  return `
    <article class="story-card">
      <span>${item.badge}</span>
      <strong>${item.step}</strong>
      <p>${item.copy}</p>
    </article>
  `;
}

function renderFounderCard(founder) {
  return `
    <article class="staff-profile-card">
      <div class="staff-profile-card-top">
        <div class="staff-profile-image staff-avatar-fallback">${founder.name.slice(0, 1).toUpperCase()}</div>
        <div class="staff-option-copy">
          <strong>${founder.name}</strong>
          <span>${founder.role}</span>
        </div>
      </div>
      <p>${founder.summary}</p>
    </article>
  `;
}

function renderBuildingCard(item) {
  return `
    <article class="room-card room-card-rich building-gallery-card">
      <div class="room-card-media">
        <img class="room-card-image" src="${item.image}" alt="${item.title}" loading="lazy" />
      </div>
      <div class="room-card-top">
        <div>
          <h3>${item.title}</h3>
          <p>${item.copy}</p>
        </div>
      </div>
    </article>
  `;
}

export function initInfoView() {}

export function renderInfoView() {
  const infoUseCasesGrid = document.getElementById("info-use-cases-grid");
  const infoAmenitiesGrid = document.getElementById("info-amenities-grid");
  const infoExpectationsGrid = document.getElementById("info-expectations-grid");

  if (infoUseCasesGrid) {
    infoUseCasesGrid.innerHTML = USE_CASES.map(renderUseCaseCard).join("");
  }
  if (infoAmenitiesGrid) {
    infoAmenitiesGrid.innerHTML = AMENITIES.map(renderAmenityLine).join("");
  }
  if (infoExpectationsGrid) {
    infoExpectationsGrid.innerHTML = EXPECTATIONS.map(renderExpectationCard).join("");
  }
  if (elements.infoFoundersGrid) {
    elements.infoFoundersGrid.innerHTML = FOUNDERS.map(renderFounderCard).join("");
  }
  if (elements.infoBuildingGallery) {
    elements.infoBuildingGallery.innerHTML = BUILDING_GALLERY.map(renderBuildingCard).join("");
  }
}
