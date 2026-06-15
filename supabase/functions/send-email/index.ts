// Supabase Edge Function: send-email
//
// Transactional email relay for the Studio Booking app. The FastAPI backend
// (EMAIL_BACKEND=supabase) POSTs rendered emails here; this function forwards
// them to Resend. The Resend API key lives only as a Supabase secret, never in
// the app repo or app environment.
//
// Auth: server-to-server via a shared secret in the `x-email-secret` header
// (deployed with verify_jwt=false). The secret is set as a Supabase secret and
// must match the backend's EMAIL_FUNCTION_SECRET.
//
// Required Supabase secrets:
//   RESEND_API_KEY        - Resend API key (re_...)
//   EMAIL_FUNCTION_SECRET - shared secret matching the backend
//
// Request body: { to, subject, from?, reply_to?, html?, text?,
//                 ics_base64?, ics_filename? }
import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const EMAIL_FUNCTION_SECRET = Deno.env.get("EMAIL_FUNCTION_SECRET") ?? "";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return json({ error: "method_not_allowed" }, 405);
  }

  // Shared-secret authentication (constant-ish comparison).
  const provided = req.headers.get("x-email-secret") ?? "";
  if (!EMAIL_FUNCTION_SECRET || provided !== EMAIL_FUNCTION_SECRET) {
    return json({ error: "unauthorized" }, 401);
  }
  if (!RESEND_API_KEY) {
    return json({ error: "resend_key_missing" }, 500);
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid_json" }, 400);
  }

  const to = body.to;
  const subject = body.subject;
  if (!to || !subject) {
    return json({ error: "missing_fields", detail: "to and subject are required" }, 400);
  }

  const payload: Record<string, unknown> = {
    from: body.from ?? "onboarding@resend.dev",
    to: Array.isArray(to) ? to : [to],
    subject,
  };
  if (body.html) payload.html = body.html;
  if (body.text) payload.text = body.text;
  if (body.reply_to) payload.reply_to = body.reply_to;
  if (body.ics_base64) {
    payload.attachments = [{
      filename: body.ics_filename ?? "studio-booking.ics",
      content: body.ics_base64,
      content_type: "text/calendar",
    }];
  }

  let res: Response;
  try {
    res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    return json({ ok: false, error: "resend_request_failed", detail: String(err) }, 502);
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return json({ ok: false, status: res.status, error: data?.message ?? "resend_error" }, 502);
  }
  return json({ ok: true, status: res.status, id: data?.id ?? null }, 200);
});
