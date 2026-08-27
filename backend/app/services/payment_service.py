from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import httpx

from app.config import get_paypal_configuration_status, redact_sensitive_text, settings


PAYPAL_API_BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}

# Order statuses that mean the order can still be paid (safe to reuse).
_REUSABLE_ORDER_STATUSES = {"CREATED", "APPROVED", "PAYER_ACTION_REQUIRED"}


@dataclass
class PaymentIntentData:
    intent_id: str
    client_secret: str


@dataclass
class CaptureResult:
    order_id: str
    status: str
    capture_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class PaymentBackendError(Exception):
    pass


class PaymentConfigurationError(PaymentBackendError):
    pass


class PaymentProviderError(PaymentBackendError):
    pass


def _is_paypal_backend() -> bool:
    return settings.PAYMENT_BACKEND == "paypal"


def paypal_api_base_url() -> str:
    env = (getattr(settings, "PAYPAL_ENV", "sandbox") or "sandbox").lower().strip()
    return PAYPAL_API_BASE_URLS.get(env, PAYPAL_API_BASE_URLS["sandbox"])


def _require_paypal_configuration(*, purpose: str, require_webhook_id: bool = False) -> None:
    status = get_paypal_configuration_status(settings)
    missing_keys = []
    if not status["paypal_client_id_ready"]:
        missing_keys.append("PAYPAL_CLIENT_ID")
    if not status["paypal_client_secret_ready"]:
        missing_keys.append("PAYPAL_CLIENT_SECRET")
    if require_webhook_id and not status["paypal_webhook_id_ready"]:
        missing_keys.append("PAYPAL_WEBHOOK_ID")
    if missing_keys:
        key_list = ", ".join(missing_keys)
        raise PaymentConfigurationError(
            f"PayPal {purpose} is not configured. Set real values for {key_list} and keep PAYMENT_BACKEND=paypal."
        )


_token_lock = threading.Lock()
_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def _fetch_paypal_access_token() -> str:
    try:
        response = httpx.post(
            f"{paypal_api_base_url()}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=settings.PAYPAL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        message = redact_sensitive_text(str(exc) or "unknown PayPal error", settings)
        raise PaymentProviderError(f"PayPal authentication failed: {message}") from exc
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise PaymentProviderError("PayPal authentication failed: no access token returned")
    # Refresh a minute early so in-flight requests never use an expired token.
    expires_in = int(payload.get("expires_in") or 300)
    with _token_lock:
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = time.time() + max(expires_in - 60, 60)
    return token


def get_paypal_access_token(*, force_refresh: bool = False) -> str:
    if not force_refresh:
        with _token_lock:
            token = _token_cache.get("access_token")
            if token and time.time() < _token_cache.get("expires_at", 0.0):
                return token
    return _fetch_paypal_access_token()


# How long a credential verdict is reused before PayPal is asked again. A good
# verdict is cheap to trust for a while; a bad one is re-checked sooner so a
# corrected misconfiguration clears quickly without polling PayPal every time
# a health check runs.
PAYPAL_CREDENTIAL_OK_TTL_SECONDS = 600
PAYPAL_CREDENTIAL_FAILURE_TTL_SECONDS = 60

# The probe runs inside /ready, which the production healthcheck polls with a
# 5s budget (docker-compose.prod.yml). Bound it well under that: a slow PayPal
# must read as "unreachable" — a transient result — rather than hang the health
# check long enough to have the container restarted.
PAYPAL_CREDENTIAL_CHECK_TIMEOUT_SECONDS = 3.0

_credential_check_lock = threading.Lock()
_credential_check_cache: dict = {"checked_at": 0.0, "result": None}


def verify_paypal_credentials(*, force: bool = False) -> dict:
    """Ask PayPal whether the configured credentials actually work against the
    configured PAYPAL_ENV.

    Configuration checks only prove the env vars are non-empty. They cannot
    catch the mistake that matters when switching to live: keys from one
    environment paired with the other environment's host, which authenticates
    nowhere and breaks every checkout while the app still looks healthy.

    Returns ``{"ok", "env", "reason", "reachable", "checked_at"}``. ``reachable``
    is False when PayPal itself could not be contacted — a transient fault
    rather than a misconfiguration, so callers can treat it differently from a
    flat rejection. Uses its own token request so the shared access-token cache
    that real payments rely on is left untouched.
    """
    env = (getattr(settings, "PAYPAL_ENV", "sandbox") or "sandbox").lower().strip()
    now = time.time()

    with _credential_check_lock:
        cached = _credential_check_cache.get("result")
        age = now - _credential_check_cache.get("checked_at", 0.0)
        if cached and not force and cached.get("env") == env:
            ttl = (
                PAYPAL_CREDENTIAL_OK_TTL_SECONDS
                if cached["ok"]
                else PAYPAL_CREDENTIAL_FAILURE_TTL_SECONDS
            )
            if age < ttl:
                return dict(cached)

    result = {"ok": False, "env": env, "reason": None, "reachable": True, "checked_at": now}
    status = get_paypal_configuration_status(settings)
    if not (status["paypal_client_id_ready"] and status["paypal_client_secret_ready"]):
        result["reason"] = "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set to real values"
    else:
        try:
            response = httpx.post(
                f"{paypal_api_base_url()}/v1/oauth2/token",
                auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                data={"grant_type": "client_credentials"},
                timeout=min(
                    float(getattr(settings, "PAYPAL_TIMEOUT_SECONDS", 20) or 20),
                    PAYPAL_CREDENTIAL_CHECK_TIMEOUT_SECONDS,
                ),
            )
        except httpx.HTTPError as exc:
            message = redact_sensitive_text(str(exc) or "unknown PayPal error", settings)
            result["reachable"] = False
            result["reason"] = f"could not reach PayPal: {message}"
        else:
            if response.status_code in (401, 403):
                result["reason"] = (
                    f"PayPal rejected these credentials for PAYPAL_ENV={env}. Check that the "
                    "client ID and secret come from the same app and that the app belongs to "
                    "that environment."
                )
            elif response.status_code >= 400:
                result["reason"] = redact_sensitive_text(_extract_paypal_error(response), settings)
            else:
                try:
                    has_token = bool(response.json().get("access_token"))
                except ValueError:
                    has_token = False
                if has_token:
                    result["ok"] = True
                else:
                    result["reason"] = "PayPal returned no access token"

    with _credential_check_lock:
        _credential_check_cache["result"] = dict(result)
        _credential_check_cache["checked_at"] = now
    return dict(result)


def _paypal_request(
    method: str,
    path: str,
    *,
    purpose: str,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> dict:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    url = f"{paypal_api_base_url()}{path}"
    last_error: Optional[str] = None
    for attempt in range(2):
        token = get_paypal_access_token(force_refresh=attempt > 0)
        request_headers["Authorization"] = f"Bearer {token}"
        try:
            response = httpx.request(
                method,
                url,
                json=json_body,
                headers=request_headers,
                timeout=settings.PAYPAL_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            message = redact_sensitive_text(str(exc) or "unknown PayPal error", settings)
            raise PaymentProviderError(f"PayPal {purpose} failed: {message}") from exc
        if response.status_code == 401 and attempt == 0:
            # Access token expired or was revoked; retry once with a fresh one.
            continue
        if response.status_code >= 400:
            last_error = _extract_paypal_error(response)
            raise PaymentProviderError(
                f"PayPal {purpose} failed: {redact_sensitive_text(last_error, settings)}"
            )
        if not response.content:
            return {}
        return response.json()
    raise PaymentProviderError(f"PayPal {purpose} failed: {last_error or 'authentication error'}")


def _extract_paypal_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    name = payload.get("name") or payload.get("error") or f"HTTP {response.status_code}"
    message = payload.get("message") or payload.get("error_description") or ""
    issues = ", ".join(
        issue.get("issue", "") for issue in payload.get("details", []) if isinstance(issue, dict)
    )
    parts = [str(part) for part in (name, message, issues) if part]
    return "; ".join(parts) or f"HTTP {response.status_code}"


def _format_amount(amount_cents: int, currency: str) -> dict:
    return {
        "currency_code": currency.upper(),
        "value": f"{amount_cents // 100}.{amount_cents % 100:02d}",
    }


def _cents_from_value(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        text = str(value)
        if "." in text:
            whole, fraction = text.split(".", 1)
            fraction = (fraction + "00")[:2]
        else:
            whole, fraction = text, "00"
        return int(whole or 0) * 100 + int(fraction)
    except (TypeError, ValueError):
        return None


def encode_custom_id(booking_id: str, metadata: Optional[dict] = None) -> str:
    """Pack booking metadata into PayPal's 127-char custom_id field."""
    payload = {"booking_id": booking_id, **(metadata or {})}
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    if len(encoded) <= 127:
        return encoded
    return booking_id[:127]


def decode_custom_id(custom_id: Optional[str]) -> dict:
    if not custom_id:
        return {}
    try:
        parsed = json.loads(custom_id)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    return {"booking_id": custom_id}


def _can_reuse_paypal_order(order_id: Optional[str]) -> bool:
    if not order_id:
        return False
    # Legacy Stripe intents ("pi_"), stub ids, and admin override references are
    # not PayPal orders and can never be reused.
    return not order_id.startswith(("pi_", "admin_", "re_", "manual_"))


def _create_paypal_order(
    *,
    amount_cents: int,
    currency: str,
    booking_id: str,
    metadata: Optional[dict] = None,
) -> dict:
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": booking_id,
                "custom_id": encode_custom_id(booking_id, metadata),
                "description": "BIPOC Creative Innovation Studio booking",
                "amount": _format_amount(amount_cents, currency),
            }
        ],
        # Studio sessions are a service, not a shipped product — tell PayPal (and
        # the Apple Pay / Google Pay sheets) not to collect a shipping address.
        "application_context": {
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "brand_name": "BIPOC Creative Innovation Studio",
        },
    }
    return _paypal_request(
        "POST",
        "/v2/checkout/orders",
        purpose="payment setup",
        json_body=body,
        headers={"PayPal-Request-Id": f"order-{booking_id}-{uuid4().hex[:12]}"},
    )


def get_paypal_order(order_id: str) -> dict:
    return _paypal_request(
        "GET",
        f"/v2/checkout/orders/{order_id}",
        purpose="order lookup",
    )


def _order_amount_cents(order: dict) -> Optional[int]:
    units = order.get("purchase_units") or []
    if not units:
        return None
    amount = (units[0] or {}).get("amount") or {}
    return _cents_from_value(amount.get("value"))


def create_payment_intent(
    *,
    amount_cents: int,
    currency: str,
    booking_id: str,
    user_email: str,
    metadata: dict | None = None,
) -> PaymentIntentData:
    if _is_paypal_backend():
        _require_paypal_configuration(purpose="checkout")
        order = _create_paypal_order(
            amount_cents=amount_cents,
            currency=currency,
            booking_id=booking_id,
            metadata=metadata,
        )
        order_id = order.get("id")
        if not order_id:
            raise PaymentProviderError("PayPal payment setup failed: no order id returned")
        return PaymentIntentData(intent_id=order_id, client_secret=order_id)

    intent_suffix = uuid4().hex[:18]
    return PaymentIntentData(
        intent_id=f"pi_stub_{intent_suffix}",
        client_secret=f"pi_client_secret_stub_{intent_suffix}",
    )


def get_payment_intent_session(
    *,
    payment_intent_id: str | None,
    amount_cents: int,
    currency: str,
    booking_id: str,
    user_email: str,
    metadata: dict | None = None,
) -> PaymentIntentData:
    if _is_paypal_backend():
        _require_paypal_configuration(purpose="checkout")
        if _can_reuse_paypal_order(payment_intent_id):
            try:
                order = get_paypal_order(payment_intent_id)
            except PaymentProviderError:
                order = None
            if (
                order
                and order.get("status") in _REUSABLE_ORDER_STATUSES
                and _order_amount_cents(order) == amount_cents
            ):
                return PaymentIntentData(intent_id=order["id"], client_secret=order["id"])
        return create_payment_intent(
            amount_cents=amount_cents,
            currency=currency,
            booking_id=booking_id,
            user_email=user_email,
            metadata=metadata,
        )

    if payment_intent_id and payment_intent_id.startswith("pi_stub_"):
        suffix = payment_intent_id.removeprefix("pi_stub_")
    else:
        suffix = uuid4().hex[:18]
    return PaymentIntentData(
        intent_id=f"pi_stub_{suffix}",
        client_secret=f"pi_client_secret_stub_{suffix}",
    )


def _capture_result_from_order(order: dict) -> CaptureResult:
    units = order.get("purchase_units") or [{}]
    unit = units[0] or {}
    captures = ((unit.get("payments") or {}).get("captures")) or []
    capture = captures[0] if captures else {}
    return CaptureResult(
        order_id=order.get("id", ""),
        status=order.get("status", ""),
        capture_id=capture.get("id"),
        metadata=decode_custom_id(unit.get("custom_id") or capture.get("custom_id")),
    )


def capture_payment_order(order_id: str) -> CaptureResult:
    """Capture an approved PayPal order. Idempotent: an already-captured order
    is looked up and returned as COMPLETED instead of failing."""
    if not _is_paypal_backend():
        return CaptureResult(order_id=order_id, status="COMPLETED", capture_id=f"cap_stub_{uuid4().hex[:12]}")

    _require_paypal_configuration(purpose="capture")
    try:
        order = _paypal_request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            purpose="payment capture",
            json_body={},
            headers={"Prefer": "return=representation"},
        )
    except PaymentProviderError as exc:
        if "ORDER_ALREADY_CAPTURED" in str(exc):
            order = get_paypal_order(order_id)
        else:
            raise
    return _capture_result_from_order(order)


def _find_capture_for_order(order_id: str) -> tuple[str, dict]:
    order = get_paypal_order(order_id)
    units = order.get("purchase_units") or []
    for unit in units:
        captures = ((unit.get("payments") or {}).get("captures")) or []
        for capture in captures:
            if capture.get("status") in {"COMPLETED", "PARTIALLY_REFUNDED", "PENDING"}:
                return capture["id"], capture
    raise ValueError("PayPal capture not found for refund")


def create_refund(*, payment_intent_id: str | None, amount_cents: int, currency: str | None = None) -> str:
    if _is_paypal_backend():
        if not payment_intent_id:
            raise ValueError("Payment reference is required for PayPal refunds")
        _require_paypal_configuration(purpose="refunds")
        capture_id, capture = _find_capture_for_order(payment_intent_id)
        capture_currency = ((capture.get("amount") or {}).get("currency_code")) or currency or settings.DEFAULT_CURRENCY
        refund = _paypal_request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            purpose="refund creation",
            json_body={"amount": _format_amount(amount_cents, capture_currency)},
            headers={"PayPal-Request-Id": f"refund-{capture_id}-{uuid4().hex[:12]}"},
        )
        refund_id = refund.get("id")
        if not refund_id:
            raise PaymentProviderError("PayPal refund creation failed: no refund id returned")
        return refund_id

    return f"re_stub_{uuid4().hex[:18]}"


def verify_paypal_webhook_signature(event: dict, headers) -> bool:
    """Ask PayPal to verify a webhook delivery. `headers` is any case-insensitive
    mapping (e.g. Starlette's request.headers)."""
    _require_paypal_configuration(purpose="webhooks", require_webhook_id=True)
    body = {
        "auth_algo": headers.get("paypal-auth-algo", ""),
        "cert_url": headers.get("paypal-cert-url", ""),
        "transmission_id": headers.get("paypal-transmission-id", ""),
        "transmission_sig": headers.get("paypal-transmission-sig", ""),
        "transmission_time": headers.get("paypal-transmission-time", ""),
        "webhook_id": settings.PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }
    result = _paypal_request(
        "POST",
        "/v1/notifications/verify-webhook-signature",
        purpose="webhook verification",
        json_body=body,
    )
    return result.get("verification_status") == "SUCCESS"


def _related_order_id(resource: dict) -> Optional[str]:
    related = ((resource.get("supplementary_data") or {}).get("related_ids")) or {}
    return related.get("order_id") or resource.get("id")


def translate_paypal_webhook_event(event: dict) -> Optional[dict]:
    """Convert a PayPal webhook event into the internal (Stripe-shaped) event
    format consumed by handle_payment_webhook_event. Returns None for event
    types the app doesn't act on."""
    event_type = str(event.get("event_type") or "")
    resource = event.get("resource") or {}
    event_id = str(event.get("id") or f"paypal_{uuid4().hex}")
    metadata = decode_custom_id(resource.get("custom_id"))

    def internal(internal_type: str, object_id: Optional[str], extra: Optional[dict] = None) -> dict:
        data_object = {"id": object_id, "metadata": metadata}
        if extra:
            data_object.update(extra)
        return {"id": event_id, "type": internal_type, "data": {"object": data_object}}

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        return internal("payment_intent.succeeded", _related_order_id(resource))

    if event_type in {"PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"}:
        return internal("payment_intent.payment_failed", _related_order_id(resource))

    if event_type == "PAYMENT.CAPTURE.REFUNDED":
        breakdown = (resource.get("seller_payable_breakdown") or {})
        total_refunded = (breakdown.get("total_refunded_amount") or {}).get("value")
        refunded_cents = _cents_from_value(total_refunded) or _cents_from_value(
            (resource.get("amount") or {}).get("value")
        )
        return internal(
            "charge.refunded",
            _related_order_id(resource),
            {"amount_refunded": refunded_cents, "amount": None},
        )

    return None
