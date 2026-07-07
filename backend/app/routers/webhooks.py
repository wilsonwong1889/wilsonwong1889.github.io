import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import redact_sensitive_text, settings
from app.services.payment_service import (
    PaymentConfigurationError,
    PaymentProviderError,
    translate_paypal_webhook_event,
    verify_paypal_webhook_signature,
)
from app.tasks import process_webhook_event_task


router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


class StubSignatureError(Exception):
    pass


def verify_stub_signature(payload: bytes, signature_header: str) -> None:
    """Dev/test-mode webhook verification: HMAC-SHA256 of "{t}.{payload}" with
    the app SECRET_KEY, sent as "t=<ts>,v1=<hex>" in the Webhook-Signature header."""
    if not signature_header:
        raise HTTPException(status_code=400, detail="Missing Webhook-Signature header")

    parts = dict(
        item.split("=", 1)
        for item in signature_header.split(",")
        if "=" in item
    )
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Invalid Webhook-Signature header")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise StubSignatureError("Webhook signature does not match the expected signature")

    if abs(time.time() - int(timestamp)) > settings.WEBHOOK_TOLERANCE_SECONDS:
        raise HTTPException(status_code=400, detail="Webhook timestamp is too old")


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    webhook_signature: str = Header(default="", alias="Webhook-Signature"),
):
    payload = await request.body()
    try:
        event = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    if settings.PAYMENT_BACKEND == "paypal":
        try:
            verified = verify_paypal_webhook_signature(event, request.headers)
        except PaymentConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PaymentProviderError as exc:
            raise HTTPException(status_code=502, detail=redact_sensitive_text(str(exc))) from exc
        if not verified:
            raise HTTPException(status_code=400, detail="PayPal webhook signature verification failed")
        internal_event = translate_paypal_webhook_event(event)
        if internal_event is None:
            return {"received": True, "ignored": True, "event_type": event.get("event_type")}
    else:
        # Stub backend (tests/dev): events already arrive in the internal shape.
        try:
            verify_stub_signature(payload, webhook_signature)
        except StubSignatureError as exc:
            raise HTTPException(status_code=400, detail=redact_sensitive_text(str(exc))) from exc
        internal_event = event

    result = process_webhook_event_task.delay(internal_event)
    if getattr(result, "inline", False) or settings.CELERY_TASK_ALWAYS_EAGER:
        return result.get()
    return {"queued": True, "task_id": result.id}
