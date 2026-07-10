from __future__ import annotations

import base64
import html
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Disposition,
    FileContent,
    FileName,
    FileType,
    Mail,
)

from app.config import settings

BUSINESS_TIMEZONE = ZoneInfo("America/Edmonton")
STUDIO_NAME = "BIPOC Foundation Digital Media & Creative Innovation Hub"
STUDIO_ADDRESS = "2525 36 St N, Lethbridge, AB T1H 5L1"
STUDIO_PHONE = "403-393-8857"
STUDIO_EMAIL = "lethsmakeithappen@bipocfoundation.org"
STUDIO_HOURS = "Wednesday – Saturday, 12:00 PM – 8:00 PM"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_local(dt: datetime) -> str:
    local = dt.astimezone(BUSINESS_TIMEZONE)
    return local.strftime("%A, %B %-d, %Y at %-I:%M %p MDT")


def _fmt_local_date(dt: datetime) -> str:
    return dt.astimezone(BUSINESS_TIMEZONE).strftime("%A, %B %-d, %Y")


def _fmt_money(cents: int) -> str:
    return f"CAD ${cents / 100:.2f}"


def _html_wrap(body_html: str, *, unsubscribe_url: Optional[str] = None) -> str:
    # CASL: identify the sender (name + physical mailing address, always in the
    # footer) and, for non-essential mail, offer a readily-performed unsubscribe.
    unsubscribe_html = (
        f'<p style="margin:8px 0 0;color:#aaa;font-size:11px;line-height:1.6;">'
        f'You are receiving this because you have a booking or account with the '
        f'{STUDIO_NAME}. '
        f'<a href="{unsubscribe_url}" style="color:#999;text-decoration:underline;">'
        f'Unsubscribe</a> from non-essential email.</p>'
        if unsubscribe_url else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:#00263E;padding:24px 32px;">
            <p style="margin:0;color:#ffffff;font-size:17px;font-weight:700;letter-spacing:-0.02em;">BIPOC Foundation</p>
            <p style="margin:4px 0 0;color:rgba(255,255,255,0.65);font-size:12px;">Digital Media &amp; Creative Innovation Hub</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 32px 24px;">
            {body_html}
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;border-top:1px solid #eef0f3;background:#fafbfc;">
            <p style="margin:0;color:#888;font-size:12px;line-height:1.6;">{STUDIO_ADDRESS} &nbsp;·&nbsp; {STUDIO_PHONE}</p>
            <p style="margin:2px 0 0;color:#888;font-size:12px;">{STUDIO_HOURS}</p>
            {unsubscribe_html}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _button(label: str, url: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;margin-top:20px;padding:12px 24px;'
        f'background:#C8102E;color:#ffffff;text-decoration:none;border-radius:6px;'
        f'font-weight:600;font-size:14px;">{label}</a>'
    )


def _detail_row(label: str, value: str) -> str:
    return (
        f'<tr>'
        f'<td style="padding:8px 0;color:#555;font-size:14px;width:140px;vertical-align:top;">{label}</td>'
        f'<td style="padding:8px 0;color:#111;font-size:14px;font-weight:600;vertical-align:top;">{value}</td>'
        f'</tr>'
    )


def _details_table(rows_html: str) -> str:
    return (
        f'<table cellpadding="0" cellspacing="0" style="width:100%;margin-top:20px;'
        f'border:1px solid #eef0f3;border-radius:8px;overflow:hidden;">'
        f'<tbody style="padding:0 16px;">'
        + rows_html +
        f'</tbody></table>'
    )


# ── ICS generation ────────────────────────────────────────────────────────────

def generate_ics(
    *,
    title: str,
    description: str,
    location: str,
    start_dt: datetime,
    end_dt: datetime,
    uid: str,
) -> bytes:
    def fmt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    now = fmt(datetime.now(timezone.utc))
    # Fold long lines at 75 chars per RFC 5545
    desc = description.replace("\n", "\\n")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BIPOC Foundation Hub//Studio Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART:{fmt(start_dt)}",
        f"DTEND:{fmt(end_dt)}",
        f"SUMMARY:{title}",
        f"DESCRIPTION:{desc}",
        f"LOCATION:{location}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines).encode("utf-8")


# ── Core send functions ───────────────────────────────────────────────────────

def send_email(
    *,
    to_email: str,
    subject: str,
    plain_text_content: str,
    html_content: Optional[str] = None,
    ics_bytes: Optional[bytes] = None,
) -> dict:
    if settings.EMAIL_BACKEND == "disabled":
        return {"backend": "disabled", "status_code": 204, "message": "Email delivery disabled"}

    if settings.EMAIL_BACKEND == "resend":
        if not settings.RESEND_API_KEY or "placeholder" in settings.RESEND_API_KEY.lower():
            raise ValueError("RESEND_API_KEY is not configured")
        payload: dict = {
            "from": settings.EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "text": plain_text_content,
        }
        if html_content:
            payload["html"] = html_content
        if settings.EMAIL_REPLY_TO:
            payload["reply_to"] = settings.EMAIL_REPLY_TO
        if ics_bytes:
            payload["attachments"] = [{
                "filename": "studio-booking.ics",
                "content": base64.b64encode(ics_bytes).decode(),
                "content_type": "text/calendar",
            }]
        request = Request(
            url="https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
                # Resend sits behind Cloudflare, which 403s the default
                # "Python-urllib" agent (error 1010); send a real UA.
                "User-Agent": "StudioBooking-Notifier/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=settings.SMTP_TIMEOUT_SECONDS) as response:
            return {"backend": "resend", "status_code": response.status}

    if settings.EMAIL_BACKEND == "supabase":
        # POST to the Supabase Edge Function, which holds the Resend key as a
        # Supabase secret and performs the actual send. We authenticate with a
        # shared secret header (the function runs with verify_jwt disabled).
        function_url = settings.SUPABASE_EMAIL_FUNCTION_URL or (
            f"{settings.SUPABASE_URL.rstrip('/')}/functions/v1/send-email"
            if settings.SUPABASE_URL
            else ""
        )
        if not function_url:
            raise ValueError(
                "SUPABASE_EMAIL_FUNCTION_URL or SUPABASE_URL must be set for the supabase email backend"
            )
        if not settings.EMAIL_FUNCTION_SECRET:
            raise ValueError("EMAIL_FUNCTION_SECRET is not configured")
        payload = {
            "from": settings.EMAIL_FROM,
            "to": to_email,
            "subject": subject,
            "text": plain_text_content,
        }
        if html_content:
            payload["html"] = html_content
        if settings.EMAIL_REPLY_TO:
            payload["reply_to"] = settings.EMAIL_REPLY_TO
        if ics_bytes:
            payload["ics_base64"] = base64.b64encode(ics_bytes).decode()
            payload["ics_filename"] = "studio-booking.ics"
        request = Request(
            url=function_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-email-secret": settings.EMAIL_FUNCTION_SECRET,
                "User-Agent": "StudioBooking-Notifier/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=settings.SMTP_TIMEOUT_SECONDS) as response:
            return {"backend": "supabase", "status_code": response.status}

    if settings.EMAIL_BACKEND == "sendgrid":
        if not settings.SENDGRID_API_KEY or "placeholder" in settings.SENDGRID_API_KEY.lower():
            raise ValueError("SENDGRID_API_KEY is not configured")
        message = Mail(
            from_email=settings.EMAIL_FROM,
            to_emails=to_email,
            subject=subject,
            plain_text_content=plain_text_content,
            html_content=html_content,
        )
        if settings.EMAIL_REPLY_TO:
            message.reply_to = settings.EMAIL_REPLY_TO
        if ics_bytes:
            message.add_attachment(Attachment(
                FileContent(base64.b64encode(ics_bytes).decode()),
                FileName("studio-booking.ics"),
                FileType("text/calendar"),
                Disposition("attachment"),
            ))
        client = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = client.send(message)
        return {"backend": "sendgrid", "status_code": response.status_code}

    if settings.EMAIL_BACKEND == "smtp":
        if not settings.SMTP_HOST or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
            raise ValueError("SMTP email settings are not configured")
        message = EmailMessage()
        message["From"] = settings.EMAIL_FROM
        message["To"] = to_email
        message["Subject"] = subject
        if settings.EMAIL_REPLY_TO:
            message["Reply-To"] = settings.EMAIL_REPLY_TO
        message.set_content(plain_text_content)
        if html_content:
            message.add_alternative(html_content, subtype="html")
        if ics_bytes:
            message.add_attachment(
                ics_bytes,
                maintype="text",
                subtype="calendar",
                filename="studio-booking.ics",
            )
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as client:
            client.ehlo()
            if settings.SMTP_USE_TLS:
                client.starttls()
                client.ehlo()
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            result = client.send_message(message)
        return {"backend": "smtp", "status_code": 250, "result": result}

    # console / fallback
    return {
        "backend": "console",
        "status_code": 202,
        "message": json.dumps({
            "to": to_email,
            "subject": subject,
            "body": plain_text_content,
            "has_ics": ics_bytes is not None,
        }),
    }


def normalize_phone_number(phone_number: str) -> str:
    trimmed = "".join(c for c in phone_number if c.isdigit() or c == "+")
    if trimmed.startswith("+"):
        return trimmed
    digits_only = "".join(c for c in trimmed if c.isdigit())
    if len(digits_only) == 10:
        return f"+1{digits_only}"
    if len(digits_only) == 11 and digits_only.startswith("1"):
        return f"+{digits_only}"
    return phone_number.strip()


def send_sms(*, to_number: str, body: str) -> dict:
    normalized_number = normalize_phone_number(to_number)

    if settings.SMS_BACKEND == "twilio":
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_FROM_NUMBER:
            raise ValueError("Twilio SMS settings are not configured")
        payload = urlencode({
            "To": normalized_number,
            "From": settings.TWILIO_FROM_NUMBER,
            "Body": body,
        }).encode("utf-8")
        request = Request(
            url=f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json",
            data=payload,
            headers={
                "Authorization": "Basic " + base64.b64encode(
                    f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode()
                ).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(request) as response:
            return {"backend": "twilio", "status_code": response.status}

    return {
        "backend": "console",
        "status_code": 202,
        "message": json.dumps({"to": normalized_number, "body": body}),
    }


# ── Account emails ────────────────────────────────────────────────────────────

def account_created_email(*, to_email: str, full_name: Optional[str]) -> dict:
    greeting = full_name or to_email
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Welcome, {greeting}!</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Your account at the {STUDIO_NAME} is ready. '
        f'You can now browse studios, make bookings, and manage your profile.</p>'
        + _button("Browse Studios", f"{settings.APP_BASE_URL.rstrip('/')}/rooms")
    )
    return send_email(
        to_email=to_email,
        subject=f"Welcome to BIPOC Foundation Hub — your account is ready",
        plain_text_content=(
            f"Welcome, {greeting}!\n\n"
            f"Your account at the {STUDIO_NAME} is ready.\n"
            f"Browse studios and book at: {settings.APP_BASE_URL.rstrip('/')}/rooms\n"
        ),
        html_content=body,
    )


def intake_received_email(
    *,
    to_email: str,
    intake_type_label: str,
    name: str,
    email: str,
    phone: str,
    fields: list,
) -> dict:
    """Notify staff of a new public intake (membership interest / engineer application).

    ``fields`` is a list of ``(label, value)`` tuples for the type-specific
    answers. All values are HTML-escaped because they come from public input.
    """
    label_lower = intake_type_label.lower()
    rows = (
        _detail_row("Name", html.escape(name))
        + _detail_row("Email", html.escape(email))
        + _detail_row("Phone", html.escape(phone))
    )
    plain_lines = [f"New {intake_type_label}", "", f"Name: {name}", f"Email: {email}", f"Phone: {phone}"]
    for field_label, value in fields:
        if not value:
            continue
        rows += _detail_row(html.escape(field_label), html.escape(str(value)))
        plain_lines.append(f"{field_label}: {value}")

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">New {label_lower}</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;line-height:1.6;">'
        f'A new {label_lower} came in through the website.</p>'
        + _details_table(rows)
        + _button("Review in admin", f"{settings.APP_BASE_URL.rstrip('/')}/admin")
    )
    return send_email(
        to_email=to_email,
        subject=f"New {intake_type_label}: {name}",
        plain_text_content="\n".join(plain_lines) + "\n",
        html_content=body,
    )


def password_reset_email(*, to_email: str, full_name: Optional[str], reset_url: str) -> dict:
    greeting = full_name or to_email
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Reset your password</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 20px;color:#444;font-size:15px;line-height:1.6;">'
        f'We received a request to reset your password. Click the button below — '
        f'this link expires in <strong>{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes</strong>.</p>'
        + _button("Reset My Password", reset_url) +
        f'<p style="margin:24px 0 0;color:#888;font-size:13px;">'
        f"If you didn't request a password reset, you can safely ignore this email.</p>"
    )
    return send_email(
        to_email=to_email,
        subject="Reset your BIPOC Foundation Hub password",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"Reset your password using this link (expires in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, ignore this email.\n"
        ),
        html_content=body,
    )


# ── Booking emails (client) ───────────────────────────────────────────────────

def booking_created_email(
    *,
    to_email: str,
    booking_code: str,
    start_time: str,
    status: str,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    price_cents: Optional[int] = None,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt) if start_dt else start_time
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    rows += _detail_row("Date & time", local_time)
    if duration_minutes:
        rows += _detail_row("Duration", f"{duration_minutes} minutes")
    if price_cents is not None:
        rows += _detail_row("Amount due", _fmt_money(price_cents))
    rows += _detail_row("Status", "Awaiting payment")

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Booking received</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Your studio booking has been created and is waiting for payment.</p>'
        + _details_table(rows) +
        _button("Complete Payment", f"{settings.APP_BASE_URL.rstrip('/')}/bookings") +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Questions? Reply to this email or call {STUDIO_PHONE}.</p>'
    )

    ics = None
    if start_dt and end_dt:
        ics = generate_ics(
            title=f"Studio Booking — {room_name or 'BIPOC Foundation Hub'}",
            description=f"Booking code: {booking_code}\nStatus: Awaiting payment\n{STUDIO_ADDRESS}",
            location=STUDIO_ADDRESS,
            start_dt=start_dt,
            end_dt=end_dt,
            uid=f"{booking_code}@bipocfoundation.org",
        )

    return send_email(
        to_email=to_email,
        subject=f"Booking received — {local_time}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"Your studio booking has been created and is waiting for payment.\n\n"
            f"Booking code: {booking_code}\n"
            f"Studio: {room_name or 'BIPOC Foundation Hub'}\n"
            f"Date & time: {local_time}\n"
            + (f"Duration: {duration_minutes} minutes\n" if duration_minutes else "")
            + (f"Amount due: {_fmt_money(price_cents)}\n" if price_cents is not None else "")
            + f"\nComplete payment at: {settings.APP_BASE_URL.rstrip('/')}/bookings\n"
        ),
        html_content=body,
        ics_bytes=ics,
    )


def booking_confirmation_email(
    *,
    to_email: str,
    booking_code: str,
    start_time: str,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    price_cents: Optional[int] = None,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    booking_id: Optional[str] = None,
    guest_access_token: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt) if start_dt else start_time
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    rows += _detail_row("Date & time", local_time)
    if duration_minutes:
        rows += _detail_row("Duration", f"{duration_minutes} minutes")
    if price_cents is not None:
        rows += _detail_row("Total paid", _fmt_money(price_cents))
    rows += _detail_row("Location", STUDIO_ADDRESS)

    booking_link_base = settings.APP_BASE_URL.rstrip("/")
    if booking_id:
        link_params = f"?id={booking_id}"
        if guest_access_token:
            link_params += f"&t={guest_access_token}"
        view_booking_url = f"{booking_link_base}/booking{link_params}"
    else:
        view_booking_url = f"{booking_link_base}/bookings"

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">You\'re booked! ✓</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Your booking is confirmed. We\'ve attached a calendar invite to add to your calendar.</p>'
        + _details_table(rows) +
        _button("View My Booking", view_booking_url) +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Plan to arrive 10–15 minutes early. '
        f'Questions? Call {STUDIO_PHONE} or reply to this email.</p>'
    )

    ics = None
    if start_dt and end_dt:
        ics = generate_ics(
            title=f"Studio Booking — {room_name or 'BIPOC Foundation Hub'}",
            description=f"Booking code: {booking_code}\nLocation: {STUDIO_ADDRESS}",
            location=STUDIO_ADDRESS,
            start_dt=start_dt,
            end_dt=end_dt,
            uid=f"{booking_code}@bipocfoundation.org",
        )

    return send_email(
        to_email=to_email,
        subject=f"Booking confirmed — {local_time}",
        plain_text_content=(
            f"Hi {greeting}, your booking is confirmed!\n\n"
            f"Booking code: {booking_code}\n"
            f"Studio: {room_name or 'BIPOC Foundation Hub'}\n"
            f"Date & time: {local_time}\n"
            + (f"Duration: {duration_minutes} minutes\n" if duration_minutes else "")
            + (f"Total paid: {_fmt_money(price_cents)}\n" if price_cents is not None else "")
            + f"Location: {STUDIO_ADDRESS}\n\n"
            f"Plan to arrive 10–15 minutes early.\n"
        ),
        html_content=body,
        ics_bytes=ics,
    )


def booking_cancellation_email(
    *,
    to_email: str,
    booking_code: str,
    reason: Optional[str],
    full_name: Optional[str] = None,
    start_dt: Optional[datetime] = None,
    room_name: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt) if start_dt else None
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    if local_time:
        rows += _detail_row("Original date", local_time)
    rows += _detail_row("Reason", reason or "No reason provided")
    is_expiry = bool(reason and "expired" in reason.lower())
    charge_warning_html = (
        f'<p style="margin:16px 0 0;color:#7a1216;font-size:14px;line-height:1.55;">'
        f'<strong>If you completed payment</strong> but never saw a confirmation, your card may still '
        f'have been charged. Reply to this email or call {STUDIO_PHONE} and we will look it up and refund '
        f'within one business day.</p>'
        if is_expiry else ""
    )
    charge_warning_text = (
        "\nIf you completed payment but never saw a confirmation, your card may still have been charged. "
        f"Reply to this email or call {STUDIO_PHONE} and we will look it up and refund within one business day.\n"
        if is_expiry else ""
    )

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Booking cancelled</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Your booking has been cancelled. See details below.</p>'
        + _details_table(rows) +
        _button("Book Again", f"{settings.APP_BASE_URL.rstrip('/')}/rooms") +
        charge_warning_html +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Questions about the cancellation? Contact us at {STUDIO_PHONE}.</p>'
    )
    return send_email(
        to_email=to_email,
        subject=f"Booking cancelled — {booking_code}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"Your booking {booking_code} has been cancelled.\n"
            + (f"Original date: {local_time}\n" if local_time else "")
            + f"Reason: {reason or 'No reason provided'}\n"
            + charge_warning_text +
            f"\nBook again at: {settings.APP_BASE_URL.rstrip('/')}/rooms\n"
        ),
        html_content=body,
    )


def refund_processed_email(
    *,
    to_email: str,
    booking_code: str,
    amount_cents: int,
    full_name: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    rows = (
        _detail_row("Booking code", booking_code)
        + _detail_row("Refund amount", _fmt_money(amount_cents))
        + _detail_row("Timeline", "3–5 business days to your original payment method")
    )
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Refund processed</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'A refund has been issued for your booking. It typically takes 3–5 business days '
        f'to appear on your statement.</p>'
        + _details_table(rows) +
        f'<p style="margin:24px 0 0;color:#888;font-size:13px;">'
        f'Questions? Contact us at {STUDIO_PHONE}.</p>'
    )
    return send_email(
        to_email=to_email,
        subject=f"Refund processed — {booking_code}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"A refund of {_fmt_money(amount_cents)} has been processed for booking {booking_code}.\n"
            f"Allow 3–5 business days for it to appear on your statement.\n"
        ),
        html_content=body,
    )


def booking_reminder_email(
    *,
    to_email: str,
    booking_code: str,
    start_time: str,
    hours_before: int,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    start_dt: Optional[datetime] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt) if start_dt else start_time
    label = f"{hours_before} hour" + ("s" if hours_before != 1 else "")
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    rows += _detail_row("Date & time", local_time)
    rows += _detail_row("Location", STUDIO_ADDRESS)

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Reminder: {label} away</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Your studio session starts in <strong>{label}</strong>. '
        f'Plan to arrive 10–15 minutes early.</p>'
        + _details_table(rows) +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Need to make changes? Call {STUDIO_PHONE} as soon as possible.</p>'
    )
    return send_email(
        to_email=to_email,
        subject=f"Reminder: your booking starts in {label} — {booking_code}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"Your booking {booking_code} starts in {label}.\n"
            f"Date & time: {local_time}\n"
            f"Location: {STUDIO_ADDRESS}\n\n"
            f"Plan to arrive 10–15 minutes early.\n"
        ),
        html_content=body,
    )


# ── Reschedule & payment-state emails ─────────────────────────────────────────

def booking_rescheduled_email(
    *,
    to_email: str,
    booking_code: str,
    new_start_dt: datetime,
    new_end_dt: datetime,
    previous_start_dt: Optional[datetime] = None,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    booking_id: Optional[str] = None,
    guest_access_token: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    new_time = _fmt_local(new_start_dt)
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    if previous_start_dt:
        rows += _detail_row("Previous time", _fmt_local(previous_start_dt))
    rows += _detail_row("New date & time", new_time)
    if duration_minutes:
        rows += _detail_row("Duration", f"{duration_minutes} minutes")
    rows += _detail_row("Location", STUDIO_ADDRESS)

    booking_link_base = settings.APP_BASE_URL.rstrip("/")
    if booking_id:
        link_params = f"?id={booking_id}"
        if guest_access_token:
            link_params += f"&t={guest_access_token}"
        view_booking_url = f"{booking_link_base}/booking{link_params}"
    else:
        view_booking_url = f"{booking_link_base}/bookings"

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Your booking was rescheduled</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'The time for your booking has changed. Your new details are below — we\'ve '
        f'attached an updated calendar invite.</p>'
        + _details_table(rows) +
        _button("View My Booking", view_booking_url) +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Didn\'t request this change? Call {STUDIO_PHONE} right away.</p>',
        unsubscribe_url=unsubscribe_url,
    )

    ics = generate_ics(
        title=f"Studio Booking — {room_name or 'BIPOC Foundation Hub'}",
        description=f"Booking code: {booking_code}\nLocation: {STUDIO_ADDRESS}",
        location=STUDIO_ADDRESS,
        start_dt=new_start_dt,
        end_dt=new_end_dt,
        uid=f"{booking_code}@bipocfoundation.org",
    )

    return send_email(
        to_email=to_email,
        subject=f"Booking rescheduled — new time {new_time}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"The time for booking {booking_code} has changed.\n"
            + (f"Previous time: {_fmt_local(previous_start_dt)}\n" if previous_start_dt else "")
            + f"New date & time: {new_time}\n"
            + (f"Duration: {duration_minutes} minutes\n" if duration_minutes else "")
            + f"Studio: {room_name or 'BIPOC Foundation Hub'}\n"
            f"Location: {STUDIO_ADDRESS}\n\n"
            f"Didn't request this change? Call {STUDIO_PHONE} right away.\n"
        ),
        html_content=body,
        ics_bytes=ics,
    )


def staff_booking_rescheduled_customer_email(
    *,
    to_email: str,
    booking_code: str,
    new_start_dt: datetime,
    previous_start_dt: Optional[datetime] = None,
    customer_name: Optional[str] = None,
    staff_name: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
) -> dict:
    greeting = customer_name or to_email
    new_time = _fmt_local(new_start_dt)
    rows = _detail_row("Booking code", booking_code)
    if staff_name:
        rows += _detail_row("Staff", staff_name)
    if previous_start_dt:
        rows += _detail_row("Previous time", _fmt_local(previous_start_dt))
    rows += _detail_row("New date & time", new_time)
    rows += _detail_row("Location", STUDIO_ADDRESS)

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Your session was rescheduled</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'The time for your session'
        + (f' with {staff_name}' if staff_name else '') +
        f' has changed. Your new details are below.</p>'
        + _details_table(rows) +
        _button("View My Bookings", f"{settings.APP_BASE_URL.rstrip('/')}/bookings") +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Didn\'t request this change? Call {STUDIO_PHONE} right away.</p>',
        unsubscribe_url=unsubscribe_url,
    )
    return send_email(
        to_email=to_email,
        subject=f"Session rescheduled — new time {new_time}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"The time for booking {booking_code} has changed.\n"
            + (f"Previous time: {_fmt_local(previous_start_dt)}\n" if previous_start_dt else "")
            + f"New date & time: {new_time}\n"
            + (f"Staff: {staff_name}\n" if staff_name else "")
            + f"Location: {STUDIO_ADDRESS}\n\n"
            f"Didn't request this change? Call {STUDIO_PHONE} right away.\n"
        ),
        html_content=body,
    )


def deposit_paid_email(
    *,
    to_email: str,
    booking_code: str,
    deposit_paid_cents: int,
    balance_due_cents: int,
    start_dt: datetime,
    end_dt: datetime,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    booking_id: Optional[str] = None,
    guest_access_token: Optional[str] = None,
    unsubscribe_url: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt)
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    rows += _detail_row("Date & time", local_time)
    if duration_minutes:
        rows += _detail_row("Duration", f"{duration_minutes} minutes")
    rows += _detail_row("Deposit paid", _fmt_money(deposit_paid_cents))
    rows += _detail_row("Balance due", _fmt_money(balance_due_cents))
    rows += _detail_row("Location", STUDIO_ADDRESS)

    booking_link_base = settings.APP_BASE_URL.rstrip("/")
    if booking_id:
        link_params = f"?id={booking_id}"
        if guest_access_token:
            link_params += f"&t={guest_access_token}"
        view_booking_url = f"{booking_link_base}/booking{link_params}"
    else:
        view_booking_url = f"{booking_link_base}/bookings"

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Deposit received ✓</h2>'
        f'<p style="margin:0 0 4px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Thanks — your deposit is in and your booking is confirmed. The remaining '
        f'balance of <strong>{_fmt_money(balance_due_cents)}</strong> is due at the '
        f'studio. We\'ve attached a calendar invite.</p>'
        + _details_table(rows) +
        _button("View My Booking", view_booking_url) +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Plan to arrive 10–15 minutes early. '
        f'Questions? Call {STUDIO_PHONE} or reply to this email.</p>',
        unsubscribe_url=unsubscribe_url,
    )

    ics = generate_ics(
        title=f"Studio Booking — {room_name or 'BIPOC Foundation Hub'}",
        description=f"Booking code: {booking_code}\nBalance due: {_fmt_money(balance_due_cents)}\nLocation: {STUDIO_ADDRESS}",
        location=STUDIO_ADDRESS,
        start_dt=start_dt,
        end_dt=end_dt,
        uid=f"{booking_code}@bipocfoundation.org",
    )

    return send_email(
        to_email=to_email,
        subject=f"Deposit received — balance {_fmt_money(balance_due_cents)} due at studio",
        plain_text_content=(
            f"Hi {greeting}, your deposit is confirmed!\n\n"
            f"Booking code: {booking_code}\n"
            f"Studio: {room_name or 'BIPOC Foundation Hub'}\n"
            f"Date & time: {local_time}\n"
            + (f"Duration: {duration_minutes} minutes\n" if duration_minutes else "")
            + f"Deposit paid: {_fmt_money(deposit_paid_cents)}\n"
            f"Balance due at studio: {_fmt_money(balance_due_cents)}\n"
            f"Location: {STUDIO_ADDRESS}\n\n"
            f"Plan to arrive 10–15 minutes early.\n"
        ),
        html_content=body,
        ics_bytes=ics,
    )


def payment_failed_email(
    *,
    to_email: str,
    booking_code: str,
    full_name: Optional[str] = None,
    room_name: Optional[str] = None,
    start_dt: Optional[datetime] = None,
    unsubscribe_url: Optional[str] = None,
) -> dict:
    greeting = full_name or to_email
    local_time = _fmt_local(start_dt) if start_dt else None
    rows = _detail_row("Booking code", booking_code)
    if room_name:
        rows += _detail_row("Studio", room_name)
    if local_time:
        rows += _detail_row("Requested time", local_time)

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Payment didn\'t go through</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">Hi {greeting},</p>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'We couldn\'t process the payment for this booking, so the time slot has been '
        f'released. No charge was made. You\'re welcome to book again whenever you\'re '
        f'ready.</p>'
        + _details_table(rows) +
        _button("Book Again", f"{settings.APP_BASE_URL.rstrip('/')}/rooms") +
        f'<p style="margin:20px 0 0;color:#888;font-size:13px;">'
        f'Think this is a mistake? Call {STUDIO_PHONE} or reply to this email.</p>',
        unsubscribe_url=unsubscribe_url,
    )
    return send_email(
        to_email=to_email,
        subject=f"Payment didn't go through — {booking_code}",
        plain_text_content=(
            f"Hi {greeting},\n\n"
            f"We couldn't process the payment for booking {booking_code}, so the "
            f"time slot has been released. No charge was made.\n"
            + (f"Requested time: {local_time}\n" if local_time else "")
            + f"\nBook again at: {settings.APP_BASE_URL.rstrip('/')}/rooms\n"
        ),
        html_content=body,
    )


# ── Staff notification email ──────────────────────────────────────────────────

def booking_staff_notification_email(
    *,
    to_email: str,
    event_type: str,
    booking_code: str,
    client_name: Optional[str],
    client_email: Optional[str],
    client_phone: Optional[str],
    room_name: Optional[str],
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    duration_minutes: Optional[int],
    price_cents: Optional[int],
    staff_assignments: Optional[list],
    note: Optional[str],
) -> dict:
    local_time = _fmt_local(start_dt) if start_dt else "—"

    event_labels = {
        "created": ("New booking", "A new booking has been made and is awaiting payment."),
        "confirmed": ("Booking confirmed & paid", "A booking has been paid and confirmed."),
        "cancelled": ("Booking cancelled", "A booking has been cancelled."),
    }
    title, subtitle = event_labels.get(event_type, ("Booking update", "A booking was updated."))

    rows = _detail_row("Booking code", booking_code)
    rows += _detail_row("Client", client_name or "—")
    if client_email:
        rows += _detail_row("Client email", client_email)
    if client_phone:
        rows += _detail_row("Client phone", client_phone)
    if room_name:
        rows += _detail_row("Studio", room_name)
    rows += _detail_row("Date & time", local_time)
    if duration_minutes:
        rows += _detail_row("Duration", f"{duration_minutes} minutes")
    if price_cents is not None:
        rows += _detail_row("Total", _fmt_money(price_cents))
    if staff_assignments:
        names = ", ".join(a.get("name", "") for a in staff_assignments if a.get("name"))
        if names:
            rows += _detail_row("Staff assigned", names)
    if note:
        rows += _detail_row("Client note", note)

    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">{title}</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;">{subtitle}</p>'
        + _details_table(rows) +
        _button("View in Admin", f"{settings.APP_BASE_URL.rstrip('/')}/admin")
    )

    ics = None
    if event_type != "cancelled" and start_dt and end_dt:
        ics = generate_ics(
            title=f"[STUDIO] {client_name or 'Client'} — {room_name or 'Booking'}",
            description=f"Booking code: {booking_code}\nClient: {client_name or '—'}\n{client_phone or ''}",
            location=STUDIO_ADDRESS,
            start_dt=start_dt,
            end_dt=end_dt,
            uid=f"staff-{booking_code}@bipocfoundation.org",
        )

    return send_email(
        to_email=to_email,
        subject=f"[{title}] {client_name or booking_code} — {local_time}",
        plain_text_content=(
            f"{title}\n{subtitle}\n\n"
            f"Booking code: {booking_code}\n"
            f"Client: {client_name or '—'}\n"
            + (f"Email: {client_email}\n" if client_email else "")
            + (f"Phone: {client_phone}\n" if client_phone else "")
            + f"Studio: {room_name or '—'}\n"
            f"Date & time: {local_time}\n"
            + (f"Duration: {duration_minutes} minutes\n" if duration_minutes else "")
            + (f"Note: {note}\n" if note else "")
            + f"\nAdmin: {settings.APP_BASE_URL.rstrip('/')}/admin\n"
        ),
        html_content=body,
        ics_bytes=ics,
    )


# ── SMS functions ─────────────────────────────────────────────────────────────

def booking_confirmation_sms(*, to_number: str, booking_code: str, start_time: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Booking confirmed! Code: {booking_code}. {start_time}. {STUDIO_ADDRESS}.",
    )


def account_created_sms(*, to_number: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Welcome to BIPOC Foundation Hub. Your account is ready — book a studio at {settings.APP_BASE_URL.rstrip('/')}/rooms",
    )


# ── Staff booking request flow ─────────────────────────────────────────────────

def staff_booking_request_email(
    *,
    to_email: str,
    staff_name: Optional[str],
    customer_name: Optional[str],
    customer_phone: Optional[str],
    service: Optional[str],
    start_time: datetime,
    accept_url: str,
    decline_url: str,
    note: Optional[str] = None,
) -> dict:
    when = _fmt_local(start_time)
    rows = (
        _detail_row("Client", html.escape(customer_name or "Guest"))
        + _detail_row("Phone", html.escape(customer_phone or "—"))
        + _detail_row("When", html.escape(when))
    )
    if service:
        rows += _detail_row("Service", html.escape(service))
    if note:
        rows += _detail_row("Notes", html.escape(note))
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">New session request</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Hi {html.escape(staff_name or "there")}, you have a new booking request. '
        f'Please accept or decline within {settings.STAFF_REQUEST_EXPIRY_HOURS} hours.</p>'
        + _details_table(rows)
        + _button("Accept", accept_url)
        + ' &nbsp; '
        + _button("Decline", decline_url)
    )
    return send_email(
        to_email=to_email,
        subject=f"New booking request — {when}",
        plain_text_content=(
            f"New session request from {customer_name or 'a client'} for {when}.\n"
            + (f"Notes: {note}\n" if note else "")
            + f"Accept: {accept_url}\nDecline: {decline_url}\n"
        ),
        html_content=body,
    )


def staff_booking_request_sms(
    *,
    to_number: str,
    customer_name: Optional[str],
    start_time: datetime,
    accept_url: str,
    decline_url: str,
) -> dict:
    when = _fmt_local(start_time)
    return send_sms(
        to_number=to_number,
        body=(
            f"New booking request from {customer_name or 'a client'} for {when}. "
            f"Accept: {accept_url} | Decline: {decline_url}"
        ),
    )


def staff_booking_accepted_customer_email(
    *,
    to_email: str,
    customer_name: Optional[str],
    staff_name: Optional[str],
    start_time: datetime,
    payment_url: str,
) -> dict:
    when = _fmt_local(start_time)
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Your request was accepted</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Hi {html.escape(customer_name or "there")}, {html.escape(staff_name or "the staff member")} '
        f'accepted your session on {html.escape(when)}. Complete payment to confirm your booking.</p>'
        + _button("Complete payment", payment_url)
    )
    return send_email(
        to_email=to_email,
        subject=f"{staff_name or 'Your booking'} accepted — complete payment",
        plain_text_content=(
            f"Good news! Your session on {when} was accepted.\n"
            f"Complete payment to confirm: {payment_url}\n"
        ),
        html_content=body,
    )


def staff_booking_declined_customer_email(
    *,
    to_email: str,
    customer_name: Optional[str],
    staff_name: Optional[str],
    start_time: datetime,
    reason: Optional[str],
) -> dict:
    when = _fmt_local(start_time)
    reason_html = (
        f'<p style="margin:0 0 16px;color:#444;font-size:14px;">Reason: {html.escape(reason)}</p>'
        if reason
        else ""
    )
    body = _html_wrap(
        f'<h2 style="margin:0 0 8px;color:#00263E;font-size:22px;">Booking request not available</h2>'
        f'<p style="margin:0 0 16px;color:#444;font-size:15px;line-height:1.6;">'
        f'Hi {html.escape(customer_name or "there")}, unfortunately '
        f'{html.escape(staff_name or "the staff member")} isn\'t available for your session on '
        f'{html.escape(when)}. Your time has been released and you have not been charged.</p>'
        + reason_html
        + _button("Browse the team", f"{settings.APP_BASE_URL.rstrip('/')}/staff")
    )
    return send_email(
        to_email=to_email,
        subject="Your booking request couldn't be confirmed",
        plain_text_content=(
            f"Your session request for {when} wasn't available."
            + (f" Reason: {reason}." if reason else "")
            + f"\nBrowse the team: {settings.APP_BASE_URL.rstrip('/')}/staff\n"
        ),
        html_content=body,
    )


def booking_created_sms(*, to_number: str, booking_code: str, start_time: str, status: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Booking received! Code: {booking_code}. {start_time}. Complete payment to confirm.",
    )


def booking_cancellation_sms(*, to_number: str, booking_code: str, reason: Optional[str]) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Booking {booking_code} cancelled. {reason or 'No reason provided.'}",
    )


def refund_processed_sms(*, to_number: str, booking_code: str, amount_cents: int) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Refund of {_fmt_money(amount_cents)} processed for booking {booking_code}. Allow 3–5 business days.",
    )


def booking_reminder_sms(*, to_number: str, booking_code: str, start_time: str, hours_before: int) -> dict:
    label = f"{hours_before}h"
    return send_sms(
        to_number=to_number,
        body=f"Reminder: your booking {booking_code} starts in {label}. {start_time}. {STUDIO_ADDRESS}.",
    )


def booking_rescheduled_sms(*, to_number: str, booking_code: str, new_start_time: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Booking {booking_code} rescheduled. New time: {new_start_time}. {STUDIO_ADDRESS}.",
    )


def payment_failed_sms(*, to_number: str, booking_code: str) -> dict:
    return send_sms(
        to_number=to_number,
        body=f"Payment for booking {booking_code} didn't go through and the slot was released. No charge was made. Book again anytime.",
    )
