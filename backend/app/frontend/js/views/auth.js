import { api } from "../api.js";
import { API_BASE_URL, getSearchParam } from "../config.js";
import { elements, toggleHidden } from "../dom.js";
import {
  exchangeSupabaseSession,
  hasSupabaseConfig,
  signOutSupabase,
  startGoogleSignIn,
} from "../supabase.js";
import { persistToken, setState, state } from "../state.js";

let googleButtonBusy = false;
let headerMenuOpen = false;
let headerMenuBound = false;

function setHeaderMenuOpen(isOpen) {
  const shouldOpen =
    Boolean(isOpen) &&
    Boolean(elements.headerUserMenuShell) &&
    !elements.headerUserMenuShell.classList.contains("hidden");
  headerMenuOpen = shouldOpen;
  toggleHidden(elements.headerUserMenu, !shouldOpen);
  elements.headerUserTrigger?.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function bindHeaderMenu() {
  if (headerMenuBound) {
    return;
  }
  headerMenuBound = true;

  elements.headerUserTrigger?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (elements.headerUserMenuShell?.classList.contains("hidden")) {
      return;
    }
    setHeaderMenuOpen(!headerMenuOpen);
  });

  document.addEventListener("click", (event) => {
    if (!headerMenuOpen || !elements.headerUserMenuShell) {
      return;
    }
    if (event.target instanceof Node && elements.headerUserMenuShell.contains(event.target)) {
      return;
    }
    setHeaderMenuOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setHeaderMenuOpen(false);
    }
  });

  [
    elements.headerProfileLink,
    elements.headerBookingsLink,
    elements.headerAdminLink,
    elements.headerLogoutButton,
  ].forEach((element) => {
    element?.addEventListener("click", () => setHeaderMenuOpen(false));
  });
}

function currentResetToken() {
  return getSearchParam("reset_token");
}

function clearLoginFieldFeedback() {
  if (elements.loginEmailFeedback) {
    elements.loginEmailFeedback.textContent = "";
    elements.loginEmailFeedback.classList.add("hidden");
  }
  if (elements.loginPasswordFeedback) {
    elements.loginPasswordFeedback.textContent = "";
    elements.loginPasswordFeedback.classList.add("hidden");
  }
}

function setLoginFieldFeedback(field, message) {
  const target =
    field === "password" ? elements.loginPasswordFeedback : elements.loginEmailFeedback;
  if (!target) {
    return;
  }
  target.textContent = message;
  target.classList.remove("hidden");
}

function hideAuthFeedback() {
  if (!elements.authFeedback) {
    return;
  }
  elements.authFeedback.textContent = "";
  elements.authFeedback.classList.add("hidden");
  elements.authFeedback.classList.remove("is-error", "is-success");
}

function showAuthFeedback(message, tone = "neutral") {
  if (!elements.authFeedback) {
    return;
  }
  elements.authFeedback.textContent = message;
  elements.authFeedback.classList.remove("hidden", "is-error", "is-success");
  elements.authFeedback.classList.toggle("is-error", tone === "error");
  elements.authFeedback.classList.toggle("is-success", tone === "success");
}

function setAccountAuthCopy(mode) {
  const title = document.getElementById("account-auth-title");
  const copy = document.getElementById("account-auth-copy");
  if (!title || !copy) {
    return;
  }

  const content = {
    login: ["Welcome back", "Sign in to view and manage your studio bookings"],
    signup: ["Create your account", "Join the Hub — save your details for faster bookings"],
    "forgot-password": ["Reset your password", "Enter your email and we'll send you a reset link"],
    "reset-password": ["Choose a new password", "Create a new password for your account"],
  };
  const [nextTitle, nextCopy] = content[mode] || content.login;
  title.textContent = nextTitle;
  copy.textContent = nextCopy;
}

function clearPasswordMatchFeedback(target) {
  if (!target) {
    return;
  }
  target.textContent = "";
  target.classList.add("hidden");
  target.classList.remove("is-match", "is-mismatch");
}

function updatePasswordMatchFeedback(target, passwordValue, confirmValue) {
  if (!target) {
    return true;
  }
  const password = String(passwordValue || "");
  const confirm = String(confirmValue || "");

  if (!password && !confirm) {
    clearPasswordMatchFeedback(target);
    return true;
  }

  target.classList.remove("hidden", "is-match", "is-mismatch");
  if (password && confirm && password === confirm) {
    target.textContent = "Passwords match.";
    target.classList.add("is-match");
    return true;
  }

  target.textContent = "Passwords do not match.";
  target.classList.add("is-mismatch");
  return false;
}

function setAuthMode(mode, { preserveFeedback = false } = {}) {
  setAccountAuthCopy(mode);
  if (!preserveFeedback) {
    hideAuthFeedback();
  }
  clearLoginFieldFeedback();
  clearPasswordMatchFeedback(elements.signupPasswordMatchFeedback);
  clearPasswordMatchFeedback(elements.resetPasswordMatchFeedback);

  const loginFamilyModes = new Set(["login", "forgot-password", "reset-password"]);
  const activeTab = loginFamilyModes.has(mode) ? "login" : "signup";

  elements.authTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === activeTab);
  });

  toggleHidden(elements.loginForm, mode !== "login");
  toggleHidden(elements.forgotPasswordForm, mode !== "forgot-password");
  toggleHidden(elements.resetPasswordForm, mode !== "reset-password");
  toggleHidden(elements.signupForm, mode !== "signup");
}

function activateTab(tab) {
  setAuthMode(tab === "signup" ? "signup" : "login");
}

function redirectHome() {
  window.location.assign("/");
}

function setGoogleButtonsDisabled(isDisabled) {
  [elements.googleLoginButton, elements.googleSignupButton].forEach((button) => {
    if (!button) {
      return;
    }
    button.disabled = isDisabled;
    button.textContent = isDisabled ? "Redirecting to Google..." : button.dataset.defaultLabel;
  });
}

async function handleGoogleSignIn() {
  if (googleButtonBusy) {
    return;
  }
  googleButtonBusy = true;
  setGoogleButtonsDisabled(true);
  hideAuthFeedback();

  try {
    await startGoogleSignIn();
    showAuthFeedback("Redirecting to Google...", "success");
    setState({ message: "Redirecting to Google..." });
  } catch (error) {
    googleButtonBusy = false;
    setGoogleButtonsDisabled(false);
    showAuthFeedback(error.message || "Google sign-in failed.", "error");
    setState({ message: error.message || "Google sign-in failed." });
  }
}

async function finalizeGoogleSignIn() {
  const supabaseReady = await hasSupabaseConfig();
  if (!supabaseReady || state.token) {
    return;
  }

  const accessToken = await exchangeSupabaseSession();
  if (!accessToken) {
    return;
  }

  googleButtonBusy = true;
  setGoogleButtonsDisabled(true);
  showAuthFeedback("Finishing Google sign-in...", "success");
  setState({ message: "Finishing Google sign-in..." });

  try {
    const session = await api.loginWithGoogle(accessToken);
    if (!session.access_token) {
      throw new Error("Google sign-in did not return an access token.");
    }
    persistToken(session.access_token);
    hideAuthFeedback();
    redirectHome();
  } catch (error) {
    showAuthFeedback(error.message || "Google sign-in failed.", "error");
    setState({ message: error.message || "Google sign-in failed." });
  } finally {
    googleButtonBusy = false;
    setGoogleButtonsDisabled(false);
  }
}

async function requestJson(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? data.detail
        : "Request failed";
    throw new Error(detail);
  }
  return data;
}

function applyLoginError(message) {
  clearLoginFieldFeedback();
  const normalizedMessage = String(message || "Log in failed.");
  const lowered = normalizedMessage.toLowerCase();

  if (lowered.includes("valid email")) {
    setLoginFieldFeedback("email", "Enter a valid email address to continue.");
    showAuthFeedback("Check your email address and try again.", "error");
  } else if (
    lowered.includes("invalid email or password") ||
    lowered.includes("wrong password") ||
    lowered.includes("couldn't find an account") ||
    lowered.includes("not found")
  ) {
    setLoginFieldFeedback("email", "Check the email address.");
    setLoginFieldFeedback("password", "Check the password or use Forgot password.");
    showAuthFeedback("Invalid email or password.", "error");
  } else {
    showAuthFeedback(normalizedMessage, "error");
  }
}

function clearSignupFieldFeedback() {
  if (elements.signupEmailFeedback) {
    elements.signupEmailFeedback.textContent = "";
    elements.signupEmailFeedback.classList.add("hidden");
  }
}

function applySignupError(message) {
  clearSignupFieldFeedback();
  const normalizedMessage = String(message || "Sign up failed.");
  const lowered = normalizedMessage.toLowerCase();

  if (lowered.includes("already registered") || lowered.includes("already in use") || lowered.includes("email")) {
    if (elements.signupEmailFeedback) {
      elements.signupEmailFeedback.textContent = "An account with this email already exists. Try signing in instead.";
      elements.signupEmailFeedback.classList.remove("hidden");
    }
    showAuthFeedback("That email is already registered. Sign in or reset your password.", "error");
  } else {
    showAuthFeedback(normalizedMessage, "error");
  }
}

export function initAuthView(actions) {
  bindHeaderMenu();

  [elements.googleLoginButton, elements.googleSignupButton].forEach((button) => {
    if (!button) {
      return;
    }
    button.dataset.defaultLabel = button.textContent;
    button.addEventListener("click", handleGoogleSignIn);
  });

  hasSupabaseConfig().then((ready) => {
    [elements.googleLoginButton, elements.googleSignupButton].forEach((button) => {
      toggleHidden(button, !ready);
    });
    toggleHidden(elements.googleAuthNote, !ready);
  });

  finalizeGoogleSignIn();

  elements.authTabs.forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.authTab));
  });

  const initialResetToken = currentResetToken();
  if (initialResetToken) {
    setAuthMode("reset-password");
    showAuthFeedback("Choose a new password for your account.", "neutral");
  } else if (getSearchParam("mode") === "signup") {
    setAuthMode("signup");
  } else {
    setAuthMode("login");
  }

  if (elements.loginForm && elements.signupForm) {
    const updateSignupPasswordMatch = () =>
      updatePasswordMatchFeedback(
        elements.signupPasswordMatchFeedback,
        elements.signupForm?.elements.password?.value,
        elements.signupForm?.elements.confirm_password?.value,
      );
    elements.signupForm.elements.password?.addEventListener("input", updateSignupPasswordMatch);
    elements.signupForm.elements.confirm_password?.addEventListener("input", updateSignupPasswordMatch);

    elements.loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.loginForm);
      clearLoginFieldFeedback();
      hideAuthFeedback();

      try {
        setState({ message: "Logging in..." });
        const session = await api.login(form.get("email"), form.get("password"));
        if (!session.access_token) {
          throw new Error("Login did not return an access token.");
        }
        persistToken(session.access_token);
        hideAuthFeedback();
        elements.loginForm.reset();
        redirectHome();
      } catch (error) {
        applyLoginError(error.message);
        setState({ message: error.message });
      }
    });

    elements.signupForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(elements.signupForm);
      const password = String(form.get("password") || "");
      const confirmPassword = String(form.get("confirm_password") || "");

      if (!updateSignupPasswordMatch()) {
        const message = "Passwords do not match yet.";
        showAuthFeedback(message, "error");
        setState({ message });
        return;
      }

      const payload = {
        email: form.get("email"),
        password,
        full_name: form.get("full_name"),
        phone: form.get("phone") || null,
      };

      hideAuthFeedback();

      try {
        setState({ message: "Creating account..." });
        await api.signup(payload);
        const session = await api.login(payload.email, payload.password);
        if (!session.access_token) {
          throw new Error("Account was created, but login did not return an access token.");
        }
        persistToken(session.access_token);
        hideAuthFeedback();
        elements.signupForm.reset();
        clearPasswordMatchFeedback(elements.signupPasswordMatchFeedback);
        redirectHome();
      } catch (error) {
        applySignupError(error.message);
        setState({ message: error.message });
      }
    });
  }

  elements.forgotPasswordLink?.addEventListener("click", () => {
    setAuthMode("forgot-password");
    showAuthFeedback("Enter your email and we will send a reset link.", "neutral");
  });

  elements.forgotPasswordBackButton?.addEventListener("click", () => {
    setAuthMode("login");
  });

  elements.resetPasswordBackButton?.addEventListener("click", () => {
    window.history.replaceState({}, "", "/account");
    setAuthMode("login");
  });

  elements.forgotPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(elements.forgotPasswordForm);
    const email = String(form.get("email") || "").trim();

    try {
      setState({ message: "Sending password reset link..." });
      const response = await requestJson("/api/auth/forgot-password", { email });
      if (elements.loginForm?.email) {
        elements.loginForm.email.value = email;
      }
      elements.forgotPasswordForm.reset();
      setAuthMode("login", { preserveFeedback: true });
      showAuthFeedback(response.message, "success");
      setState({ message: response.message });
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  const updateResetPasswordMatch = () =>
    updatePasswordMatchFeedback(
      elements.resetPasswordMatchFeedback,
      elements.resetPasswordForm?.elements.new_password?.value,
      elements.resetPasswordForm?.elements.confirm_password?.value,
    );
  elements.resetPasswordForm?.elements.new_password?.addEventListener("input", updateResetPasswordMatch);
  elements.resetPasswordForm?.elements.confirm_password?.addEventListener("input", updateResetPasswordMatch);

  elements.resetPasswordForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const resetToken = currentResetToken();
    const form = new FormData(elements.resetPasswordForm);
    const newPassword = String(form.get("new_password") || "");
    const confirmPassword = String(form.get("confirm_password") || "");

    if (!resetToken) {
      const message = "Password reset link is missing. Request a new one.";
      showAuthFeedback(message, "error");
      setState({ message });
      return;
    }

    if (!updateResetPasswordMatch()) {
      const message = "Passwords do not match yet.";
      showAuthFeedback(message, "error");
      setState({ message });
      return;
    }

    try {
      setState({ message: "Saving new password..." });
      await requestJson("/api/auth/reset-password", {
        reset_token: resetToken,
        new_password: newPassword,
      });
      elements.resetPasswordForm.reset();
      clearPasswordMatchFeedback(elements.resetPasswordMatchFeedback);
      window.history.replaceState({}, "", "/account");
      setAuthMode("login", { preserveFeedback: true });
      showAuthFeedback("Password updated. You can log in now.", "success");
      setState({ message: "Password updated. You can log in now." });
    } catch (error) {
      showAuthFeedback(error.message, "error");
      setState({ message: error.message });
    }
  });

  const handleLogout = async () => {
    hideAuthFeedback();
    await signOutSupabase();
    persistToken(null);
    await actions.clearSession();
  };

  if (elements.logoutButton) {
    elements.logoutButton.addEventListener("click", handleLogout);
  }
  if (elements.headerLogoutButton) {
    elements.headerLogoutButton.addEventListener("click", handleLogout);
  }
}

export function renderAuthView(state) {
  const isSessionRestoring = Boolean(state.token && !state.currentUser);
  document.body?.setAttribute("data-auth-pending", isSessionRestoring ? "true" : "false");
  if (state.currentUser) {
    hideAuthFeedback();
  }

  if (elements.logoutButton) {
    elements.logoutButton.classList.toggle("hidden", !state.currentUser);
  }

  if (elements.accountAuthPanel) {
    toggleHidden(elements.accountAuthPanel, Boolean(state.currentUser || isSessionRestoring));
  }

  if (elements.accountHeroTitle) {
    elements.accountHeroTitle.textContent = state.currentUser
      ? "Your account is ready."
      : "Access and profile live in one clean place.";
  }

  if (elements.accountHeroCopy) {
    elements.accountHeroCopy.textContent = state.currentUser
      ? "Update your personal details, password, and reminder preferences here."
      : "Use this page for account entry, profile updates, password changes, and reminder preferences.";
  }

  if (elements.accountSummaryCard && elements.accountSummaryName && elements.accountSummaryEmail) {
    toggleHidden(elements.accountSummaryCard, !state.currentUser);
    if (state.currentUser) {
      elements.accountSummaryName.textContent = `Welcome, ${
        state.currentUser.full_name || state.currentUser.email
      }.`;
      elements.accountSummaryEmail.textContent = state.currentUser.email;
    }
  }

  if (elements.headerAccountLink) {
    elements.headerAccountLink.href = "/account";
    elements.headerAccountLink.textContent = "Log in";
  }
  if (elements.mobileNavAccountLink) {
    elements.mobileNavAccountLink.href = state.currentUser ? "/account" : "/account";
    elements.mobileNavAccountLink.textContent = state.currentUser ? "My Account" : "Log in";
  }

  if (elements.headerSecondaryLink) {
    elements.headerSecondaryLink.href = "/rooms";
    elements.headerSecondaryLink.textContent = "Book Now";
    elements.headerSecondaryLink.classList.remove("hidden");
  }

  toggleHidden(elements.headerAccountLink, Boolean(state.currentUser) || isSessionRestoring);
  toggleHidden(elements.headerSecondaryLink, isSessionRestoring ? true : false);
  toggleHidden(elements.headerUserMenuShell, !state.currentUser || isSessionRestoring);

  if (elements.headerUserEmail) {
    elements.headerUserEmail.textContent = state.currentUser?.email || "account@example.com";
  }

  if (elements.headerProfileLink) {
    elements.headerProfileLink.href = "/account";
  }

  if (elements.headerBookingsLink) {
    elements.headerBookingsLink.href = "/bookings";
    const actionCount = Number(state.actionRequiredCount || 0);
    elements.headerBookingsLink.innerHTML =
      state.currentUser && actionCount > 0
        ? `My Bookings <span class="header-menu-badge" title="${actionCount} booking${actionCount === 1 ? "" : "s"} need your confirmation">${actionCount}</span>`
        : "My Bookings";
  }

  if (elements.headerAdminLink) {
    elements.headerAdminLink.href = "/admin";
    elements.headerAdminLink.classList.toggle("hidden", !state.currentUser?.is_admin);
  }

  if (elements.headerStaffLink) {
    elements.headerStaffLink.classList.toggle("hidden", state.currentUser?.role !== "Staff");
  }

  if (!state.currentUser) {
    setHeaderMenuOpen(false);
  }
}
