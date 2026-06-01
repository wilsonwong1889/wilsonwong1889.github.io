import { api } from "../api.js";
import { STORAGE_KEYS } from "../config.js";
import { elements, toggleHidden } from "../dom.js";
import { persistToken, setState } from "../state.js";

let draftSaveTimer = null;
let lastHydratedFingerprint = null;
let activeDraftKey = null;
let lastDraftTimestamp = null;
let hasRestorableDraft = false;
let applyingDraft = false;
let pendingAvatarPreviewUrl = null;

function asText(value) {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed || null;
}

function buildBillingAddress(form) {
  const address = {
    line1: asText(form.get("billing_line1")),
    line2: asText(form.get("billing_line2")),
    city: asText(form.get("billing_city")),
    state: asText(form.get("billing_state")),
    postal_code: asText(form.get("billing_postal_code")),
    country: asText(form.get("billing_country")),
  };

  return address.line1 ? address : null;
}

function buildProfilePayload() {
  const form = new FormData(elements.profileForm);
  return {
    full_name: asText(form.get("full_name")),
    avatar_url: asText(form.get("avatar_url")),
    phone: asText(form.get("phone")),
    birthday: asText(form.get("birthday")),
    billing_address: buildBillingAddress(form),
    emergency_contact: asText(form.get("emergency_contact")),
    visible_minority: asText(form.get("visible_minority")),
    city: asText(form.get("city")),
    opt_in_email: form.get("opt_in_email") === "on",
    opt_in_sms: form.get("opt_in_sms") === "on",
    two_factor_enabled: form.get("two_factor_enabled") === "on",
    two_factor_method: asText(form.get("two_factor_method")) || "email",
  };
}

function buildProfileSnapshot() {
  const payload = buildProfilePayload();
  return {
    ...payload,
    avatar_url: elements.profileForm.avatar_url.value || "",
    email: elements.profileForm.email.value || "",
  };
}

function renderAvatarPreview(avatarUrl, label = "Profile") {
  if (!elements.profileAvatarPreview) {
    return;
  }

  const safeLabel = String(label || "Profile").trim() || "Profile";
  if (avatarUrl) {
    elements.profileAvatarPreview.innerHTML = `
      <img class="profile-avatar-image" src="${avatarUrl}" alt="${safeLabel}" loading="lazy" />
    `;
    return;
  }

  elements.profileAvatarPreview.innerHTML = `
    <div class="profile-avatar-fallback">${safeLabel.slice(0, 1).toUpperCase()}</div>
  `;
}

function applySnapshot(snapshot) {
  if (!elements.profileForm || !snapshot) {
    return;
  }

  applyingDraft = true;
  elements.profileForm.full_name.value = snapshot.full_name || "";
  elements.profileForm.avatar_url.value = snapshot.avatar_url || "";
  elements.profileForm.email.value = snapshot.email || elements.profileForm.email.value || "";
  elements.profileForm.phone.value = snapshot.phone || "";
  elements.profileForm.birthday.value = snapshot.birthday || "";
  elements.profileForm.billing_line1.value = snapshot.billing_address?.line1 || "";
  elements.profileForm.billing_line2.value = snapshot.billing_address?.line2 || "";
  elements.profileForm.billing_city.value = snapshot.billing_address?.city || "";
  elements.profileForm.billing_state.value = snapshot.billing_address?.state || "";
  elements.profileForm.billing_postal_code.value = snapshot.billing_address?.postal_code || "";
  elements.profileForm.billing_country.value = snapshot.billing_address?.country || "";
  elements.profileForm.emergency_contact.value = snapshot.emergency_contact || "";
  elements.profileForm.visible_minority.value = snapshot.visible_minority || "";
  elements.profileForm.city.value = snapshot.city || "";
  elements.profileForm.opt_in_email.checked = Boolean(snapshot.opt_in_email);
  elements.profileForm.opt_in_sms.checked = Boolean(snapshot.opt_in_sms);
  elements.profileForm.two_factor_enabled.checked = Boolean(snapshot.two_factor_enabled);
  elements.profileForm.two_factor_method.value = snapshot.two_factor_method || "email";
  renderAvatarPreview(snapshot.avatar_url || null, snapshot.full_name || snapshot.email || "Profile");
  applyingDraft = false;
}

function profileFingerprint(user) {
  return JSON.stringify({
    id: user.id,
    email: user.email,
    full_name: user.full_name,
    avatar_url: user.avatar_url,
    phone: user.phone,
    birthday: user.birthday,
    billing_address: user.billing_address,
    emergency_contact: user.emergency_contact,
    visible_minority: user.visible_minority,
    city: user.city,
    opt_in_email: user.opt_in_email,
    opt_in_sms: user.opt_in_sms,
    two_factor_enabled: user.two_factor_enabled,
    two_factor_method: user.two_factor_method,
    updated_at: user.updated_at,
  });
}

function getDraftKey(user) {
  const identifier = user?.id || user?.email || "anonymous";
  return `${STORAGE_KEYS.profileDraftPrefix}:${identifier}`;
}

function readDraft() {
  if (!activeDraftKey) {
    return null;
  }

  const raw = localStorage.getItem(activeDraftKey);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch (_error) {
    localStorage.removeItem(activeDraftKey);
    return null;
  }
}

function setSaveState(title, detail, { success = false, danger = false } = {}) {
  if (elements.profileSaveState) {
    elements.profileSaveState.textContent = title;
    elements.profileSaveState.classList.toggle("is-success", success);
    elements.profileSaveState.classList.toggle("is-error", danger);
  }
  if (elements.profileSaveDetail) {
    elements.profileSaveDetail.textContent = detail;
  }
}

function updateDraftControls() {
  toggleHidden(elements.profileRestoreDraftButton, !hasRestorableDraft);
  toggleHidden(elements.profileDiscardDraftButton, !hasRestorableDraft);
}

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "";
  }

  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function clearPasswordMatchFeedback() {
  if (!elements.profilePasswordMatchFeedback) {
    return;
  }
  elements.profilePasswordMatchFeedback.textContent = "";
  elements.profilePasswordMatchFeedback.classList.add("hidden");
  elements.profilePasswordMatchFeedback.classList.remove("is-match", "is-mismatch");
}

function updatePasswordMatchFeedback() {
  if (!elements.passwordForm || !elements.profilePasswordMatchFeedback) {
    return true;
  }

  const password = String(elements.passwordForm.elements.new_password?.value || "");
  const confirm = String(elements.passwordForm.elements.confirm_password?.value || "");

  if (!password && !confirm) {
    clearPasswordMatchFeedback();
    return true;
  }

  elements.profilePasswordMatchFeedback.classList.remove("hidden", "is-match", "is-mismatch");
  if (password && confirm && password === confirm) {
    elements.profilePasswordMatchFeedback.textContent = "Passwords match.";
    elements.profilePasswordMatchFeedback.classList.add("is-match");
    return true;
  }

  elements.profilePasswordMatchFeedback.textContent = "Passwords do not match.";
  elements.profilePasswordMatchFeedback.classList.add("is-mismatch");
  return false;
}

function clearDraft({ keepMessage = false } = {}) {
  if (draftSaveTimer) {
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = null;
  }

  if (activeDraftKey) {
    localStorage.removeItem(activeDraftKey);
  }

  hasRestorableDraft = false;
  lastDraftTimestamp = null;
  updateDraftControls();

  if (!keepMessage) {
    setSaveState("Account details are ready.", "You can save now or continue later.");
  }
}

function saveDraftNow() {
  if (!elements.profileForm || !activeDraftKey) {
    return;
  }

  const snapshot = buildProfileSnapshot();
  lastDraftTimestamp = new Date().toISOString();
  localStorage.setItem(
    activeDraftKey,
    JSON.stringify({
      saved_at: lastDraftTimestamp,
      snapshot,
    }),
  );
  hasRestorableDraft = true;
  updateDraftControls();
  setSaveState(
    "Draft saved locally.",
    `You can leave and continue later. Last draft: ${formatTimestamp(lastDraftTimestamp)}.`,
    { success: true },
  );
}

function scheduleDraftSave() {
  if (applyingDraft || !activeDraftKey) {
    return;
  }

  if (draftSaveTimer) {
    window.clearTimeout(draftSaveTimer);
  }

  setSaveState("Saving draft...", "Your changes are being saved locally.");
  draftSaveTimer = window.setTimeout(() => {
    saveDraftNow();
    draftSaveTimer = null;
  }, 250);
}

function hydrateFromUser(user) {
  applySnapshot({
    full_name: user.full_name,
    avatar_url: user.avatar_url,
    email: user.email,
    phone: user.phone,
    birthday: user.birthday,
    billing_address: user.billing_address,
    emergency_contact: user.emergency_contact,
    visible_minority: user.visible_minority,
    city: user.city,
    opt_in_email: user.opt_in_email,
    opt_in_sms: user.opt_in_sms,
    two_factor_enabled: user.two_factor_enabled,
    two_factor_method: user.two_factor_method,
  });
}

function restoreDraft() {
  const draft = readDraft();
  if (!draft?.snapshot) {
    hasRestorableDraft = false;
    updateDraftControls();
    return;
  }

  applySnapshot(draft.snapshot);
  lastDraftTimestamp = draft.saved_at || null;
  hasRestorableDraft = true;
  updateDraftControls();
  setSaveState(
    "Draft restored.",
    `Restored your local draft from ${formatTimestamp(lastDraftTimestamp)}.`,
    { success: true },
  );
}

export function initProfileView(actions) {
  if (!elements.profileForm || !elements.passwordForm) {
    return;
  }

  elements.profileAvatarFile?.addEventListener("change", () => {
    if (pendingAvatarPreviewUrl) {
      URL.revokeObjectURL(pendingAvatarPreviewUrl);
      pendingAvatarPreviewUrl = null;
    }

    const file = elements.profileAvatarFile.files?.[0];
    if (!file) {
      renderAvatarPreview(
        elements.profileForm?.elements?.avatar_url?.value || null,
        elements.profileForm?.elements?.full_name?.value || elements.profileForm?.elements?.email?.value || "Profile",
      );
      return;
    }

    pendingAvatarPreviewUrl = URL.createObjectURL(file);
    renderAvatarPreview(
      pendingAvatarPreviewUrl,
      elements.profileForm?.elements?.full_name?.value || file.name,
    );
  });

  elements.profileForm.addEventListener("input", () => {
    scheduleDraftSave();
  });

  elements.profileForm.addEventListener("change", () => {
    scheduleDraftSave();
  });

  if (elements.profileRestoreDraftButton) {
    elements.profileRestoreDraftButton.addEventListener("click", () => {
      restoreDraft();
    });
  }

  if (elements.profileDiscardDraftButton) {
    elements.profileDiscardDraftButton.addEventListener("click", () => {
      clearDraft();
      setSaveState("Draft cleared.", "Local draft removed. Keep editing and save when ready.", {
        success: true,
      });
    });
  }

  elements.profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = buildProfilePayload();

    try {
      setSaveState("Saving profile...", "Writing your profile to the account.");
      if (elements.profileSaveButton) {
        elements.profileSaveButton.disabled = true;
      }
      const avatarFile = elements.profileAvatarFile?.files?.[0];
      if (avatarFile) {
        const upload = await api.uploadProfileAvatar(avatarFile);
        elements.profileForm.avatar_url.value = upload.avatar_url;
        payload.avatar_url = upload.avatar_url;
      }
      const user = await api.updateProfile(payload);
      lastHydratedFingerprint = profileFingerprint(user);
      hydrateFromUser(user);
      if (elements.profileAvatarFile) {
        elements.profileAvatarFile.value = "";
      }
      if (pendingAvatarPreviewUrl) {
        URL.revokeObjectURL(pendingAvatarPreviewUrl);
        pendingAvatarPreviewUrl = null;
      }
      clearDraft({ keepMessage: true });
      setSaveState("Profile saved.", "Your account details are now stored on the server.", {
        success: true,
      });
      setState({ currentUser: user, message: "Profile updated." });
    } catch (error) {
      setSaveState("Save failed.", error.message, { danger: true });
      setState({ message: error.message });
    } finally {
      if (elements.profileSaveButton) {
        elements.profileSaveButton.disabled = false;
      }
    }
  });

  elements.passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.passwordForm);
    if (!updatePasswordMatchFeedback()) {
      setState({ message: "Passwords do not match yet." });
      return;
    }
    const payload = {
      current_password: form.get("current_password"),
      new_password: form.get("new_password"),
    };

    try {
      await api.updatePassword(payload);
      elements.passwordForm.reset();
      clearPasswordMatchFeedback();
      setState({ message: "Password updated." });
    } catch (error) {
      setState({ message: error.message });
    }
  });

  elements.passwordForm.elements.new_password?.addEventListener("input", updatePasswordMatchFeedback);
  elements.passwordForm.elements.confirm_password?.addEventListener("input", updatePasswordMatchFeedback);

  elements.profileDeleteButton?.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Delete this account? Your profile will be removed and you will be signed out immediately.",
    );
    if (!confirmed) {
      return;
    }

    const deletePassword = window.prompt("Enter your password to delete this account.");
    if (!deletePassword) {
      setState({ message: "Account deletion cancelled." });
      return;
    }

    try {
      elements.profileDeleteButton.disabled = true;
      setSaveState("Deleting account...", "Removing your profile and ending this session.", {
        danger: true,
      });
      await api.deleteProfile({ password: deletePassword });
      clearDraft({ keepMessage: true });
      persistToken(null);
      await actions.clearSession();
      setState({ message: "Account deleted." });
    } catch (error) {
      setSaveState("Delete failed.", error.message, { danger: true });
      setState({ message: error.message });
    } finally {
      elements.profileDeleteButton.disabled = false;
    }
  });
}

export function renderProfileView(state) {
  if (!elements.profileEmpty || !elements.profileForm || !elements.passwordForm) {
    return;
  }

  const user = state.currentUser;
  const isSessionRestoring = Boolean(state.token && !state.currentUser);
  const isVisible = Boolean(user);
  if (elements.accountProfilePanel) {
    toggleHidden(elements.accountProfilePanel, !isVisible);
  }
  toggleHidden(elements.profileEmpty, isVisible || isSessionRestoring);
  toggleHidden(elements.profileForm, !isVisible);
  toggleHidden(elements.passwordForm, !isVisible);
  toggleHidden(elements.accountDangerZone, !isVisible);

  if (!user) {
    activeDraftKey = null;
    lastHydratedFingerprint = null;
    hasRestorableDraft = false;
    lastDraftTimestamp = null;
    updateDraftControls();
    if (!isSessionRestoring) {
      setSaveState("Account details are ready.", "You can save now or continue later.");
    }
    renderAvatarPreview(null, "Profile");
    clearPasswordMatchFeedback();
    return;
  }

  const fingerprint = profileFingerprint(user);
  const nextDraftKey = getDraftKey(user);
  const draftKeyChanged = activeDraftKey !== nextDraftKey;
  activeDraftKey = nextDraftKey;

  const draft = readDraft();
  hasRestorableDraft = Boolean(draft?.snapshot);
  lastDraftTimestamp = draft?.saved_at || null;
  updateDraftControls();

  if (draftKeyChanged || lastHydratedFingerprint !== fingerprint) {
    hydrateFromUser(user);
    lastHydratedFingerprint = fingerprint;

    if (draft?.snapshot) {
      applySnapshot(draft.snapshot);
      setSaveState(
        "Draft ready to continue.",
        `Local draft found from ${formatTimestamp(lastDraftTimestamp)}. You can keep editing or save now.`,
        { success: true },
      );
    } else {
      setSaveState("Profile loaded.", "Your saved account details are ready to edit.", {
        success: true,
      });
    }
  }

  renderMembershipSection(user);
}

const MEMBERSHIP_INFO = {
  artist_member:         { label: "Artist Member",         roomRate: "$50/hr",  spaceRate: "$100/hr", fee: "$15/mo or $120/yr", benefits: ["Reduced studio rate", "Book 4 hours, get the 5th free", "Community programming access"] },
  fellowship_artist:     { label: "Fellowship Artist",     roomRate: "$50/hr",  spaceRate: "$100/hr", fee: "Free",              benefits: ["Complimentary membership", "Reduced studio rate", "Community programming access"] },
  artist_in_residence:   { label: "Artist in Residence",   roomRate: "$50/hr",  spaceRate: "$100/hr", fee: "Free",              benefits: ["Complimentary membership", "Reduced studio rate", "Community programming access"] },
  service_engineer:      { label: "Service Engineer",      roomRate: "$50/hr",  spaceRate: "$100/hr", fee: "Free",              benefits: ["Complimentary membership", "Reduced studio rate", "Community programming access"] },
  bipoc_community_member:{ label: "BIPOC Community Member",roomRate: "$75/hr",  spaceRate: "$150/hr", fee: "Free",              benefits: ["Complimentary membership", "Community programming access"] },
  venture_member:        { label: "Venture Member",        roomRate: "$50/hr",  spaceRate: "$100/hr", fee: "Contact us",        benefits: ["Monthly free hours included", "Rate applies after free hours are used"] },
  organizational_member: { label: "Organizational Member", roomRate: "Contact", spaceRate: "Contact", fee: "Contact us",        benefits: ["Custom rates — contact the Hub to confirm"] },
  general_public:        { label: "General Public",        roomRate: "$100/hr", spaceRate: "$200/hr", fee: "Free",              benefits: ["No membership required", "Book online instantly"] },
};

function renderMembershipSection(user) {
  const section = document.getElementById("account-membership-section");
  if (!section) return;

  const category = user?.user_category || "general_public";
  const info = MEMBERSHIP_INFO[category] || MEMBERSHIP_INFO.general_public;

  section.classList.remove("hidden");

  const tierName = document.getElementById("account-membership-tier-name");
  const roomRate = document.getElementById("account-membership-room-rate");
  const spaceRate = document.getElementById("account-membership-space-rate");
  const fee = document.getElementById("account-membership-fee");
  const benefits = document.getElementById("account-membership-benefits");

  if (tierName) tierName.textContent = info.label;
  if (roomRate) roomRate.textContent = info.roomRate;
  if (spaceRate) spaceRate.textContent = info.spaceRate;
  if (fee) fee.textContent = info.fee;
  if (benefits) {
    benefits.innerHTML = info.benefits
      .map((b) => `<div class="account-membership-benefit"><span class="account-membership-check">✓</span>${b}</div>`)
      .join("");
  }
}
