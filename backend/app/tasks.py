from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.celery_app import task
from app.config import settings
from app.database import SessionLocal
from app.monitoring import record_task_items, record_task_run
from app.models.booking import Booking, NotificationLog, WebhookEventLog
from app.models.room import Room
from app.models.staff_booking import StaffBooking
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.services.booking_service import (
    create_notification_log,
    expire_stale_pending_bookings,
    handle_payment_webhook_event,
)
from app.services.staff_booking_service import handle_staff_booking_payment_webhook_event
from app.services.notification_service import (
    account_created_email,
    account_created_sms,
    booking_cancellation_email,
    booking_cancellation_sms,
    booking_created_email,
    booking_created_sms,
    booking_confirmation_email,
    booking_confirmation_sms,
    booking_reminder_email,
    booking_reminder_sms,
    booking_rescheduled_email,
    booking_rescheduled_sms,
    booking_staff_notification_email,
    deposit_paid_email,
    password_reset_email,
    payment_failed_email,
    payment_failed_sms,
    refund_processed_email,
    refund_processed_sms,
    staff_booking_accepted_customer_email,
    staff_booking_declined_customer_email,
    staff_booking_request_email,
    staff_booking_request_sms,
    staff_booking_rescheduled_customer_email,
)
from app.services.suitedash_service import (
    SuiteDashConfigurationError,
    SuiteDashRequestError,
    suitedash_is_configured,
    suitedash_is_enabled,
    sync_contact_to_suitedash,
)


def _get_booking_and_user(db, booking_id: str):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return None, None
    user = None
    if booking.user_id:
        user = db.query(User).filter(User.id == booking.user_id).first()
    return booking, user


def _get_room_name(db, room_id) -> str | None:
    if not room_id:
        return None
    room = db.query(Room).filter(Room.id == room_id).first()
    return room.name if room else None


def _get_user(db, user_id: str):
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def _unsubscribe_url_for(user) -> Optional[str]:
    """CASL unsubscribe link for a recipient, or None if they have no token.

    Forward-compatible: returns None until the unsubscribe_token column exists
    and is populated, so callers can pass it unconditionally.
    """
    token = getattr(user, "unsubscribe_token", None)
    if not token:
        return None
    return f"{settings.APP_BASE_URL.rstrip('/')}/api/notifications/unsubscribe?token={token}"


def _deposit_and_balance_cents(booking) -> tuple[int, int]:
    """Deposit collected online (deposit + 5% GST) and the balance still owing."""
    from math import floor

    deposit = booking.deposit_amount_cents or 0
    deposit_paid = deposit + floor(deposit * 0.05)
    balance_due = max((booking.price_cents or 0) - deposit_paid, 0)
    return deposit_paid, balance_due


def _json_safe_details(value) -> dict:
    if isinstance(value, dict):
        return json.loads(json.dumps(value, default=str))
    return {"result": json.loads(json.dumps(value, default=str))}


def _duplicate_webhook_result(event_log: WebhookEventLog, *, processing: bool = False) -> dict:
    details = event_log.details if isinstance(event_log.details, dict) else {}
    result = dict(details)
    result.setdefault("received", True)
    result["duplicate"] = True
    result["event_id"] = event_log.event_id
    result["webhook_event_status"] = event_log.status
    if processing:
        result["processing"] = True
    return result


def _restart_failed_webhook_event(db, event_log: WebhookEventLog, event_type: str) -> WebhookEventLog:
    now = datetime.now(timezone.utc)
    event_log.status = "Processing"
    event_log.event_type = event_type
    event_log.attempt_count = (event_log.attempt_count or 0) + 1
    event_log.last_error = None
    event_log.updated_at = now
    db.commit()
    db.refresh(event_log)
    return event_log


def _claim_webhook_event(db, event: dict) -> tuple[Optional[WebhookEventLog], Optional[dict]]:
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        return None, None

    event_type = str(event.get("type") or "unknown")
    existing = db.query(WebhookEventLog).filter(WebhookEventLog.event_id == event_id).first()
    if existing:
        if existing.status == "Processed":
            return existing, _duplicate_webhook_result(existing)
        if existing.status == "Processing":
            return existing, _duplicate_webhook_result(existing, processing=True)
        return _restart_failed_webhook_event(db, existing, event_type), None

    event_log = WebhookEventLog(
        event_id=event_id,
        event_type=event_type,
        status="Processing",
        attempt_count=1,
    )
    db.add(event_log)
    try:
        db.commit()
        db.refresh(event_log)
        return event_log, None
    except IntegrityError:
        db.rollback()
        existing = db.query(WebhookEventLog).filter(WebhookEventLog.event_id == event_id).first()
        if not existing:
            raise
        if existing.status == "Processed":
            return existing, _duplicate_webhook_result(existing)
        if existing.status == "Processing":
            return existing, _duplicate_webhook_result(existing, processing=True)
        return _restart_failed_webhook_event(db, existing, event_type), None


def _mark_webhook_event_processed(db, event_log: WebhookEventLog, result: dict) -> None:
    now = datetime.now(timezone.utc)
    event_log.status = "Processed"
    event_log.details = _json_safe_details(result)
    event_log.last_error = None
    event_log.processed_at = now
    event_log.updated_at = now
    db.commit()


def _mark_webhook_event_failed(db, event_log: WebhookEventLog, exc: Exception) -> None:
    event_log_id = event_log.id
    db.rollback()
    current_log = db.query(WebhookEventLog).filter(WebhookEventLog.id == event_log_id).first()
    if not current_log:
        return
    now = datetime.now(timezone.utc)
    error_message = str(exc)
    current_log.status = "Failed"
    current_log.last_error = error_message
    current_log.details = _json_safe_details({"error": error_message})
    current_log.updated_at = now
    db.commit()


@task(name="app.tasks.sync_suitedash_contact")
def sync_suitedash_contact_task(user_id: str, source: str, role: Optional[str] = None):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user:
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "skipped", 1)
            return {"synced": False, "reason": "user_not_found"}
        if not suitedash_is_enabled():
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "skipped", 1)
            return {"synced": False, "reason": "integration_disabled"}
        if not suitedash_is_configured():
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "failed", 1)
            return {"synced": False, "reason": "integration_not_configured"}

        try:
            delivery = sync_contact_to_suitedash(user, source=source, role=role)
            create_notification_log(
                db,
                user_id=user.id,
                booking_id=None,
                notification_type=f"suitedash_contact_sync_{source}",
                status="Sent",
                details={"delivery": delivery},
            )
            db.commit()
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "sent", 1)
            return {"synced": True}
        except (SuiteDashConfigurationError, SuiteDashRequestError, ValueError) as exc:
            create_notification_log(
                db,
                user_id=user.id,
                booking_id=None,
                notification_type=f"suitedash_contact_sync_{source}",
                status="Failed",
                details={"error": str(exc)},
            )
            db.commit()
            record_task_run("sync_suitedash_contact")
            record_task_items("sync_suitedash_contact", "failed", 1)
            return {"synced": False, "error": str(exc)}
    finally:
        db.close()


@task(
    name="app.tasks.process_webhook_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_webhook_event_task(event: dict):
    db = SessionLocal()
    try:
        event_log, duplicate_result = _claim_webhook_event(db, event)
        if duplicate_result:
            record_task_run("process_webhook_event")
            return duplicate_result
        try:
            metadata = event.get("data", {}).get("object", {}).get("metadata", {}) or {}
            booking_type = metadata.get("booking_type")
            if booking_type == "staff":
                result = handle_staff_booking_payment_webhook_event(db, event)
            else:
                try:
                    result = handle_payment_webhook_event(db, event)
                except ValueError:
                    result = handle_staff_booking_payment_webhook_event(db, event)
        except Exception as exc:
            if event_log:
                _mark_webhook_event_failed(db, event_log, exc)
            raise
        if event_log:
            _mark_webhook_event_processed(db, event_log, result)
        record_task_run("process_webhook_event")
        return result
    finally:
        db.close()


@task(name="app.tasks.send_account_created_email")
def send_account_created_email_task(user_id: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.email:
            record_task_run("send_account_created_email")
            record_task_items("send_account_created_email", "skipped", 1)
            return {"sent": False}
        delivery = account_created_email(
            to_email=user.email,
            full_name=user.full_name,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="account_created_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_account_created_email")
        record_task_items("send_account_created_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_account_created_sms")
def send_account_created_sms_task(user_id: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.phone:
            record_task_run("send_account_created_sms")
            record_task_items("send_account_created_sms", "skipped", 1)
            return {"sent": False}
        delivery = account_created_sms(
            to_number=user.phone,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="account_created_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_account_created_sms")
        record_task_items("send_account_created_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_password_reset_email")
def send_password_reset_email_task(user_id: str, reset_token: str):
    db = SessionLocal()
    try:
        user = _get_user(db, user_id)
        if not user or not user.email:
            record_task_run("send_password_reset_email")
            record_task_items("send_password_reset_email", "skipped", 1)
            return {"sent": False}
        reset_url = (
            f"{settings.APP_BASE_URL.rstrip('/')}/account"
            f"?mode=reset&reset_token={reset_token}"
        )
        delivery = password_reset_email(
            to_email=user.email,
            full_name=user.full_name,
            reset_url=reset_url,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="password_reset_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_password_reset_email")
        record_task_items("send_password_reset_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_created_email")
def send_booking_created_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email:
            record_task_run("send_booking_created_email")
            record_task_items("send_booking_created_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        end_dt = booking.start_time + timedelta(minutes=booking.duration_minutes)
        delivery = booking_created_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
            status=booking.status,
            full_name=user.full_name,
            room_name=room_name,
            duration_minutes=booking.duration_minutes,
            price_cents=booking.price_cents,
            start_dt=booking.start_time,
            end_dt=end_dt,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_created_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_created_email")
        record_task_items("send_booking_created_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_created_sms")
def send_booking_created_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone:
            record_task_run("send_booking_created_sms")
            record_task_items("send_booking_created_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_created_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
            status=booking.status,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_created_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_created_sms")
        record_task_items("send_booking_created_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_confirmation_email")
def send_booking_confirmation_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_booking_confirmation_email")
            record_task_items("send_booking_confirmation_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        end_dt = booking.start_time + timedelta(minutes=booking.duration_minutes)
        # For guest users (auto-generated email), mint a fresh long-lived token
        # so the email link works on any device they open it on.
        guest_token = None
        try:
            from app.core.security import create_access_token
            if user.email and "@guest.studiobooking.local" in user.email:
                guest_token = create_access_token(
                    {"sub": str(user.id)},
                    expires_minutes=60 * 24 * 30,
                )
        except Exception:  # noqa: BLE001 — never let token minting block the email
            guest_token = None
        try:
            delivery = booking_confirmation_email(
                to_email=user.email,
                booking_code=booking.booking_code,
                start_time=booking.start_time.isoformat(),
                full_name=user.full_name,
                room_name=room_name,
                duration_minutes=booking.duration_minutes,
                price_cents=booking.price_cents,
                start_dt=booking.start_time,
                end_dt=end_dt,
                booking_id=str(booking.id),
                guest_access_token=guest_token,
            )
        except Exception as exc:  # noqa: BLE001 — record the failure so admins can see it
            create_notification_log(
                db,
                user_id=user.id,
                booking_id=booking.id,
                notification_type="booking_confirmation_email_worker",
                status="Failed",
                details={"error": str(exc)},
            )
            db.commit()
            record_task_run("send_booking_confirmation_email")
            record_task_items("send_booking_confirmation_email", "failed", 1)
            raise
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_confirmation_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_confirmation_email")
        record_task_items("send_booking_confirmation_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_confirmation_sms")
def send_booking_confirmation_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_booking_confirmation_sms")
            record_task_items("send_booking_confirmation_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_confirmation_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            start_time=booking.start_time.isoformat(),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_confirmation_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_confirmation_sms")
        record_task_items("send_booking_confirmation_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_rescheduled_email")
def send_booking_rescheduled_email_task(booking_id: str, previous_start_iso: Optional[str] = None):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_booking_rescheduled_email")
            record_task_items("send_booking_rescheduled_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        end_dt = booking.start_time + timedelta(minutes=booking.duration_minutes)
        previous_start_dt = datetime.fromisoformat(previous_start_iso) if previous_start_iso else None
        guest_token = None
        try:
            from app.core.security import create_access_token
            if user.email and "@guest.studiobooking.local" in user.email:
                guest_token = create_access_token({"sub": str(user.id)}, expires_minutes=60 * 24 * 30)
        except Exception:  # noqa: BLE001 — never let token minting block the email
            guest_token = None
        delivery = booking_rescheduled_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            new_start_dt=booking.start_time,
            new_end_dt=end_dt,
            previous_start_dt=previous_start_dt,
            full_name=user.full_name,
            room_name=room_name,
            duration_minutes=booking.duration_minutes,
            booking_id=str(booking.id),
            guest_access_token=guest_token,
            unsubscribe_url=_unsubscribe_url_for(user),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_rescheduled_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_rescheduled_email")
        record_task_items("send_booking_rescheduled_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_rescheduled_sms")
def send_booking_rescheduled_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_booking_rescheduled_sms")
            record_task_items("send_booking_rescheduled_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_rescheduled_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            new_start_time=booking.start_time.isoformat(),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_rescheduled_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_rescheduled_sms")
        record_task_items("send_booking_rescheduled_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_staff_booking_rescheduled_email")
def send_staff_booking_rescheduled_email_task(staff_booking_id: str, previous_start_iso: Optional[str] = None):
    db = SessionLocal()
    try:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
        if not booking or not booking.user_email:
            record_task_run("send_staff_booking_rescheduled_email")
            record_task_items("send_staff_booking_rescheduled_email", "skipped", 1)
            return {"sent": False}
        user = _get_user(db, str(booking.user_id)) if booking.user_id else None
        if user and not user.opt_in_email:
            record_task_run("send_staff_booking_rescheduled_email")
            record_task_items("send_staff_booking_rescheduled_email", "skipped", 1)
            return {"sent": False}
        profile = db.query(StaffProfile).filter(StaffProfile.id == booking.staff_profile_id).first()
        previous_start_dt = datetime.fromisoformat(previous_start_iso) if previous_start_iso else None
        delivery = staff_booking_rescheduled_customer_email(
            to_email=booking.user_email,
            booking_code=booking.booking_code,
            new_start_dt=booking.start_time,
            previous_start_dt=previous_start_dt,
            customer_name=booking.user_full_name_snapshot,
            staff_name=profile.name if profile else None,
            unsubscribe_url=_unsubscribe_url_for(user) if user else None,
        )
        create_notification_log(
            db,
            user_id=booking.user_id,
            booking_id=None,
            notification_type="staff_booking_rescheduled_email_worker",
            status="Sent",
            details={"delivery": delivery, "staff_booking_id": str(booking.id)},
        )
        db.commit()
        record_task_run("send_staff_booking_rescheduled_email")
        record_task_items("send_staff_booking_rescheduled_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_deposit_paid_email")
def send_deposit_paid_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_deposit_paid_email")
            record_task_items("send_deposit_paid_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        end_dt = booking.start_time + timedelta(minutes=booking.duration_minutes)
        deposit_paid_cents, balance_due_cents = _deposit_and_balance_cents(booking)
        guest_token = None
        try:
            from app.core.security import create_access_token
            if user.email and "@guest.studiobooking.local" in user.email:
                guest_token = create_access_token({"sub": str(user.id)}, expires_minutes=60 * 24 * 30)
        except Exception:  # noqa: BLE001 — never let token minting block the email
            guest_token = None
        delivery = deposit_paid_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            deposit_paid_cents=deposit_paid_cents,
            balance_due_cents=balance_due_cents,
            start_dt=booking.start_time,
            end_dt=end_dt,
            full_name=user.full_name,
            room_name=room_name,
            duration_minutes=booking.duration_minutes,
            booking_id=str(booking.id),
            guest_access_token=guest_token,
            unsubscribe_url=_unsubscribe_url_for(user),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="deposit_paid_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_deposit_paid_email")
        record_task_items("send_deposit_paid_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_payment_failed_email")
def send_payment_failed_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_payment_failed_email")
            record_task_items("send_payment_failed_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        delivery = payment_failed_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            full_name=user.full_name,
            room_name=room_name,
            start_dt=booking.start_time,
            unsubscribe_url=_unsubscribe_url_for(user),
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="payment_failed_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_payment_failed_email")
        record_task_items("send_payment_failed_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_payment_failed_sms")
def send_payment_failed_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_payment_failed_sms")
            record_task_items("send_payment_failed_sms", "skipped", 1)
            return {"sent": False}
        delivery = payment_failed_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="payment_failed_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_payment_failed_sms")
        record_task_items("send_payment_failed_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_cancellation_email")
def send_booking_cancellation_email_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_booking_cancellation_email")
            record_task_items("send_booking_cancellation_email", "skipped", 1)
            return {"sent": False}
        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        delivery = booking_cancellation_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            reason=booking.cancellation_reason,
            full_name=user.full_name,
            start_dt=booking.start_time,
            room_name=room_name,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_cancellation_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_cancellation_email")
        record_task_items("send_booking_cancellation_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_booking_cancellation_sms")
def send_booking_cancellation_sms_task(booking_id: str):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_booking_cancellation_sms")
            record_task_items("send_booking_cancellation_sms", "skipped", 1)
            return {"sent": False}
        delivery = booking_cancellation_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            reason=booking.cancellation_reason,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="booking_cancellation_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_booking_cancellation_sms")
        record_task_items("send_booking_cancellation_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_refund_processed_email")
def send_refund_processed_email_task(booking_id: str, amount_cents: int):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.email or not user.opt_in_email:
            record_task_run("send_refund_processed_email")
            record_task_items("send_refund_processed_email", "skipped", 1)
            return {"sent": False}
        delivery = refund_processed_email(
            to_email=user.email,
            booking_code=booking.booking_code,
            amount_cents=amount_cents,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="refund_processed_email_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_refund_processed_email")
        record_task_items("send_refund_processed_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_refund_processed_sms")
def send_refund_processed_sms_task(booking_id: str, amount_cents: int):
    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking or not user or not user.phone or not user.opt_in_sms:
            record_task_run("send_refund_processed_sms")
            record_task_items("send_refund_processed_sms", "skipped", 1)
            return {"sent": False}
        delivery = refund_processed_sms(
            to_number=user.phone,
            booking_code=booking.booking_code,
            amount_cents=amount_cents,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=booking.id,
            notification_type="refund_processed_sms_worker",
            status="Sent",
            details={"delivery": delivery},
        )
        db.commit()
        record_task_run("send_refund_processed_sms")
        record_task_items("send_refund_processed_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.dispatch_due_reminders")
def dispatch_due_reminders_task(hours_before: int):
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(hours=hours_before) - timedelta(minutes=30)
        window_end = now + timedelta(hours=hours_before) + timedelta(minutes=30)
        notification_type = f"reminder_{hours_before}h"
        bookings = (
            db.query(Booking)
            .filter(Booking.status.in_(("Paid", "Completed")))
            .filter(Booking.start_time >= window_start)
            .filter(Booking.start_time <= window_end)
            .all()
        )

        sent = 0
        for booking in bookings:
            user = db.query(User).filter(User.id == booking.user_id).first()
            if not user:
                continue
            if user.email and user.opt_in_email:
                email_type = f"{notification_type}_email"
                existing_email = (
                    db.query(NotificationLog)
                    .filter(NotificationLog.booking_id == booking.id)
                    .filter(NotificationLog.type == email_type)
                    .first()
                )
                if not existing_email:
                    room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
                    delivery = booking_reminder_email(
                        to_email=user.email,
                        booking_code=booking.booking_code,
                        start_time=booking.start_time.isoformat(),
                        hours_before=hours_before,
                        full_name=user.full_name,
                        room_name=room_name,
                        start_dt=booking.start_time,
                    )
                    create_notification_log(
                        db,
                        user_id=user.id,
                        booking_id=booking.id,
                        notification_type=email_type,
                        status="Sent",
                        details={"delivery": delivery},
                    )
                    sent += 1

            if user.phone and user.opt_in_sms:
                sms_type = f"{notification_type}_sms"
                existing_sms = (
                    db.query(NotificationLog)
                    .filter(NotificationLog.booking_id == booking.id)
                    .filter(NotificationLog.type == sms_type)
                    .first()
                )
                if not existing_sms:
                    delivery = booking_reminder_sms(
                        to_number=user.phone,
                        booking_code=booking.booking_code,
                        start_time=booking.start_time.isoformat(),
                        hours_before=hours_before,
                    )
                    create_notification_log(
                        db,
                        user_id=user.id,
                        booking_id=booking.id,
                        notification_type=sms_type,
                        status="Sent",
                        details={"delivery": delivery},
                    )
                    sent += 1

        db.commit()
        record_task_run("dispatch_due_reminders")
        record_task_items("dispatch_due_reminders", "sent", sent)
        return {"sent": sent}
    finally:
        db.close()


@task(name="app.tasks.cleanup_expired_pending_bookings")
def cleanup_expired_pending_bookings_task(
    expired_after_minutes: int = settings.PENDING_BOOKING_EXPIRY_MINUTES,
):
    db = SessionLocal()
    try:
        cleaned = expire_stale_pending_bookings(
            db,
            expired_after_minutes=expired_after_minutes,
        )
        record_task_run("cleanup_expired_pending_bookings")
        record_task_items("cleanup_expired_pending_bookings", "cleaned", cleaned)
        return {"cleaned": cleaned}
    finally:
        db.close()


@task(name="app.tasks.send_booking_staff_notification_email")
def send_booking_staff_notification_email_task(booking_id: str, event_type: str):
    """Send a booking update to the studio admin/coordinator email."""
    admin_email = settings.STUDIO_ADMIN_EMAIL
    if not admin_email:
        record_task_run("send_booking_staff_notification_email")
        record_task_items("send_booking_staff_notification_email", "skipped", 1)
        return {"sent": False, "reason": "no_admin_email"}

    db = SessionLocal()
    try:
        booking, user = _get_booking_and_user(db, booking_id)
        if not booking:
            record_task_run("send_booking_staff_notification_email")
            record_task_items("send_booking_staff_notification_email", "skipped", 1)
            return {"sent": False, "reason": "booking_not_found"}

        room_name = getattr(booking, "room_name_snapshot", None) or _get_room_name(db, booking.room_id)
        end_dt = booking.start_time + timedelta(minutes=booking.duration_minutes)

        delivery = booking_staff_notification_email(
            to_email=admin_email,
            event_type=event_type,
            booking_code=booking.booking_code,
            client_name=booking.user_full_name_snapshot or (user.full_name if user else None),
            client_email=booking.user_email_snapshot or (user.email if user else None),
            client_phone=booking.user_phone_snapshot or (user.phone if user else None),
            room_name=room_name,
            start_dt=booking.start_time,
            end_dt=end_dt,
            duration_minutes=booking.duration_minutes,
            price_cents=booking.price_cents,
            staff_assignments=booking.staff_assignments or [],
            note=booking.note,
        )
        create_notification_log(
            db,
            user_id=user.id if user else None,
            booking_id=booking.id,
            notification_type=f"booking_staff_notification_{event_type}_email",
            status="Sent",
            details={"delivery": delivery, "to": admin_email},
        )
        db.commit()
        record_task_run("send_booking_staff_notification_email")
        record_task_items("send_booking_staff_notification_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


# ── Staff booking request flow notifications ───────────────────────────────────

def _staff_recipient_email(db, profile) -> Optional[str]:
    if profile.notification_email:
        return profile.notification_email
    if profile.user_id:
        user = db.query(User).filter(User.id == profile.user_id).first()
        if user and user.email:
            return user.email
    return settings.STUDIO_ADMIN_EMAIL


def _staff_recipient_phone(db, profile) -> Optional[str]:
    if profile.notification_phone:
        return profile.notification_phone
    if profile.user_id:
        user = db.query(User).filter(User.id == profile.user_id).first()
        if user and user.phone:
            return user.phone
    return None


def _staff_response_urls(staff_booking_id, raw_token: str):
    base = settings.APP_BASE_URL.rstrip("/")
    common = f"{base}/staff-respond?booking={staff_booking_id}&token={raw_token}"
    return f"{common}&action=accept", f"{common}&action=decline"


@task(name="app.tasks.send_staff_booking_request_email")
def send_staff_booking_request_email_task(staff_booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
        profile = (
            db.query(StaffProfile).filter(StaffProfile.id == booking.staff_profile_id).first()
            if booking
            else None
        )
        if not booking or booking.status != "Requested" or not profile or not profile.notify_by_email:
            record_task_run("send_staff_booking_request_email")
            record_task_items("send_staff_booking_request_email", "skipped", 1)
            return {"sent": False}
        from app.services.staff_token_service import create_response_token

        raw_token = create_response_token(db, booking)
        accept_url, decline_url = _staff_response_urls(booking.id, raw_token)
        delivery = staff_booking_request_email(
            to_email=_staff_recipient_email(db, profile),
            staff_name=profile.name,
            customer_name=booking.user_full_name_snapshot,
            customer_phone=booking.user_phone_snapshot,
            service=booking.service_type,
            start_time=booking.start_time,
            accept_url=accept_url,
            decline_url=decline_url,
        )
        create_notification_log(
            db,
            user_id=booking.user_id,
            booking_id=None,
            notification_type="staff_booking_request_email_worker",
            status="Sent",
            details={"delivery": delivery, "staff_booking_id": str(booking.id)},
        )
        db.commit()
        record_task_run("send_staff_booking_request_email")
        record_task_items("send_staff_booking_request_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_staff_booking_request_sms")
def send_staff_booking_request_sms_task(staff_booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
        profile = (
            db.query(StaffProfile).filter(StaffProfile.id == booking.staff_profile_id).first()
            if booking
            else None
        )
        recipient = _staff_recipient_phone(db, profile) if profile else None
        if not booking or booking.status != "Requested" or not profile or not profile.notify_by_sms or not recipient:
            record_task_run("send_staff_booking_request_sms")
            record_task_items("send_staff_booking_request_sms", "skipped", 1)
            return {"sent": False}
        from app.services.staff_token_service import create_response_token

        raw_token = create_response_token(db, booking)
        accept_url, decline_url = _staff_response_urls(booking.id, raw_token)
        delivery = staff_booking_request_sms(
            to_number=recipient,
            customer_name=booking.user_full_name_snapshot,
            start_time=booking.start_time,
            accept_url=accept_url,
            decline_url=decline_url,
        )
        create_notification_log(
            db,
            user_id=booking.user_id,
            booking_id=None,
            notification_type="staff_booking_request_sms_worker",
            status="Sent",
            details={"delivery": delivery, "staff_booking_id": str(booking.id)},
        )
        db.commit()
        record_task_run("send_staff_booking_request_sms")
        record_task_items("send_staff_booking_request_sms", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_staff_booking_accepted_customer_email")
def send_staff_booking_accepted_customer_email_task(staff_booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
        if not booking or not booking.user_email:
            record_task_run("send_staff_booking_accepted_customer_email")
            record_task_items("send_staff_booking_accepted_customer_email", "skipped", 1)
            return {"sent": False}
        profile = db.query(StaffProfile).filter(StaffProfile.id == booking.staff_profile_id).first()
        delivery = staff_booking_accepted_customer_email(
            to_email=booking.user_email,
            customer_name=booking.user_full_name_snapshot,
            staff_name=profile.name if profile else None,
            start_time=booking.start_time,
            payment_url=f"{settings.APP_BASE_URL.rstrip('/')}/bookings",
        )
        create_notification_log(
            db,
            user_id=booking.user_id,
            booking_id=None,
            notification_type="staff_booking_accepted_customer_email_worker",
            status="Sent",
            details={"delivery": delivery, "staff_booking_id": str(booking.id)},
        )
        db.commit()
        record_task_run("send_staff_booking_accepted_customer_email")
        record_task_items("send_staff_booking_accepted_customer_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()


@task(name="app.tasks.send_staff_booking_declined_customer_email")
def send_staff_booking_declined_customer_email_task(staff_booking_id: str):
    db = SessionLocal()
    try:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
        if not booking or not booking.user_email:
            record_task_run("send_staff_booking_declined_customer_email")
            record_task_items("send_staff_booking_declined_customer_email", "skipped", 1)
            return {"sent": False}
        profile = db.query(StaffProfile).filter(StaffProfile.id == booking.staff_profile_id).first()
        delivery = staff_booking_declined_customer_email(
            to_email=booking.user_email,
            customer_name=booking.user_full_name_snapshot,
            staff_name=profile.name if profile else None,
            start_time=booking.start_time,
            reason=booking.cancellation_reason,
        )
        create_notification_log(
            db,
            user_id=booking.user_id,
            booking_id=None,
            notification_type="staff_booking_declined_customer_email_worker",
            status="Sent",
            details={"delivery": delivery, "staff_booking_id": str(booking.id)},
        )
        db.commit()
        record_task_run("send_staff_booking_declined_customer_email")
        record_task_items("send_staff_booking_declined_customer_email", "sent", 1)
        return {"sent": True}
    finally:
        db.close()
