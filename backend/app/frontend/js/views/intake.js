import { api } from "../api.js";

function setFeedback(el, message, type) {
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden", "is-error", "is-success");
  if (type === "error") {
    el.classList.add("is-error");
  } else if (type === "success") {
    el.classList.add("is-success");
  }
}

function cleanValue(value) {
  return (value || "").toString().trim();
}

/**
 * Wires a public intake form: client-side validation, submit-to-API, inline
 * feedback, and a button busy state. No-op when the form isn't on the page.
 */
function wireIntakeForm(formId, feedbackId, buildPayload, submitter, successMessage) {
  const form = document.getElementById(formId);
  if (!form) return;

  const feedback = document.getElementById(feedbackId);
  const submitButton = form.querySelector('button[type="submit"]');

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (typeof form.reportValidity === "function" && !form.reportValidity()) return;

    const payload = buildPayload(new FormData(form));
    const originalLabel = submitButton ? submitButton.textContent : "";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Sending…";
    }
    if (feedback) feedback.classList.add("hidden");

    try {
      await submitter(payload);
      form.reset();
      setFeedback(feedback, successMessage, "success");
    } catch (error) {
      setFeedback(
        feedback,
        error?.message ? String(error.message) : "Something went wrong. Please try again.",
        "error",
      );
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalLabel;
      }
    }
  });
}

export function initIntakeView() {
  wireIntakeForm(
    "membership-interest-form",
    "membership-interest-feedback",
    (data) => ({
      name: cleanValue(data.get("name")),
      email: cleanValue(data.get("email")),
      phone: cleanValue(data.get("phone")),
      membership_interest: cleanValue(data.get("membership_interest")),
      message: cleanValue(data.get("message")) || null,
    }),
    (payload) => api.submitMembershipInterest(payload),
    "Thanks! Your membership request is in — the team will reach out by email or phone soon.",
  );

  wireIntakeForm(
    "service-inquiry-form",
    "service-inquiry-feedback",
    (data) => ({
      name: cleanValue(data.get("name")),
      email: cleanValue(data.get("email")),
      phone: cleanValue(data.get("phone")),
      service_interest: cleanValue(data.get("service_interest")),
      message: cleanValue(data.get("message")) || null,
    }),
    (payload) => api.submitServiceInquiry(payload),
    "Thanks! Your inquiry is in — the team will reach out by email or phone soon.",
  );

  wireIntakeForm(
    "engineer-application-form",
    "engineer-application-feedback",
    (data) => ({
      name: cleanValue(data.get("name")),
      email: cleanValue(data.get("email")),
      phone: cleanValue(data.get("phone")),
      skillset: cleanValue(data.get("skillset")),
      equipment: cleanValue(data.get("equipment")) || null,
      why_considered: cleanValue(data.get("why_considered")),
    }),
    (payload) => api.submitEngineerApplication(payload),
    "Thanks for applying! We'll review your submission and get back to you.",
  );
}

export function renderIntakeView() {}
