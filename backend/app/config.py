import re
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
PLACEHOLDER_MARKERS = ("change_me", "change-me", "placeholder", "example.com", "studio.local")
SENSITIVE_SETTING_NAMES = (
    "SECRET_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SENDGRID_API_KEY",
    "SMTP_PASSWORD",
    "TWILIO_AUTH_TOKEN",
    "SUITEDASH_SECRET_KEY",
)
SECRET_TOKEN_PATTERNS = (
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]+\b"),
    re.compile(r"\bpk_(?:live|test)_[A-Za-z0-9]+\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9]+\b"),
    re.compile(r"\bSG\.[A-Za-z0-9._-]+\b"),
)


class RuntimeConfigurationError(RuntimeError):
    pass


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = Field(repr=False)
    APP_ENV: str = "development"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    ALLOWED_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_TIMEOUT_SECONDS: int = 20

    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_SECRET_KEY: str = Field(default="sk_test_placeholder", repr=False)
    STRIPE_WEBHOOK_SECRET: str = Field(default="whsec_placeholder", repr=False)
    STRIPE_API_VERSION: str = "2026-02-25.clover"
    PAYMENT_BACKEND: str = "stub"
    STRIPE_WEBHOOK_TOLERANCE_SECONDS: int = 300

    SENDGRID_API_KEY: str = Field(default="SG.placeholder", repr=False)
    EMAIL_FROM: str = "noreply@yourstudio.com"
    EMAIL_REPLY_TO: str = ""
    EMAIL_BACKEND: str = "console"
    STUDIO_ADMIN_EMAIL: str = "lethsmakeithappen@bipocfoundation.org"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = Field(default="", repr=False)
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_SECONDS: int = 20
    SMS_BACKEND: str = "console"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = Field(default="", repr=False)
    TWILIO_FROM_NUMBER: str = ""
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    SUITEDASH_ENABLED: bool = False
    SUITEDASH_BASE_URL: str = "https://app.suitedash.com"
    SUITEDASH_PUBLIC_ID: str = ""
    SUITEDASH_SECRET_KEY: str = Field(default="", repr=False)
    SUITEDASH_TIMEOUT_SECONDS: int = 20
    SUITEDASH_CONTACT_META_PATH: str = "/contact/meta"
    SUITEDASH_CONTACT_SYNC_PATH: str = "/contact"
    SUITEDASH_CONTACT_SYNC_METHOD: str = "POST"
    SUITEDASH_ROLE_ON_SIGNUP: str = "Lead"
    SUITEDASH_ROLE_ON_BOOKING: str = "Prospect"
    SUITEDASH_ROLE_ON_PAID_BOOKING: str = "Client"

    REDIS_URL: str = "redis://localhost:6379/0"
    RESERVATION_HOLD_MINUTES: int = 5
    CELERY_TASK_ALWAYS_EAGER: bool = True
    ALLOW_INLINE_TASKS_IN_PRODUCTION: bool = False
    REMINDER_HOURS_BEFORE: str = "24,5,1"
    REMINDER_DISPATCH_INTERVAL_MINUTES: int = 30
    PENDING_BOOKING_CLEANUP_INTERVAL_MINUTES: int = 1
    PENDING_BOOKING_EXPIRY_MINUTES: int = 5
    # How long a staff member has to accept a booking request before it expires.
    STAFF_REQUEST_EXPIRY_HOURS: int = 48
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    AUTH_RATE_LIMIT_MAX_REQUESTS: int = 20
    BOOKING_RATE_LIMIT_MAX_REQUESTS: int = 30
    ADMIN_RATE_LIMIT_MAX_REQUESTS: int = 40

    BUSINESS_TIMEZONE: str = "America/Edmonton"
    BOOKING_OPEN_HOUR: int = 12
    BOOKING_CLOSE_HOUR: int = 20
    HOURLY_RATE_CENTS: int = 5000
    # Flat surcharge per staff member added to a room booking ($25/hour each).
    STAFF_ROOM_ADDON_HOURLY_CENTS: int = 2500
    DEFAULT_CURRENCY: str = "CAD"

    # Feature flags for TBC features
    FEATURE_OPENING_DISCOUNT: bool = False
    FEATURE_VENTURE_TIERS: bool = False
    FEATURE_MONTHLY_PACKAGES: bool = False
    FEATURE_DAY_RATES: bool = False
    FEATURE_EQUIPMENT_RENTAL: bool = False
    FEATURE_SPECIAL_PROJECTS: bool = True
    FEATURE_ENGINEER_PROFILES: bool = False

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )

    @property
    def reminder_hours_before_list(self) -> list[int]:
        values = []
        for raw_value in self.REMINDER_HOURS_BEFORE.split(","):
            trimmed = raw_value.strip()
            if not trimmed:
                continue
            values.append(int(trimmed))
        return values

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_CORS_ORIGINS.split(",") if origin.strip()]


def _looks_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def mask_secret(value: str, *, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_prefix + visible_suffix:
        return "*" * len(value)
    return f"{value[:visible_prefix]}...{value[-visible_suffix:]}"


def redact_sensitive_text(value: str, settings_obj: Optional[Settings] = None) -> str:
    current = settings_obj or settings
    redacted = value
    for pattern in SECRET_TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for setting_name in SENSITIVE_SETTING_NAMES:
        secret_value = getattr(current, setting_name, "") or ""
        if secret_value and secret_value in redacted:
            redacted = redacted.replace(secret_value, mask_secret(secret_value))
    return redacted


def _is_configured(value: str) -> bool:
    return bool(value.strip()) and not _looks_placeholder(value)


def get_stripe_configuration_status(settings_obj: Optional[Settings] = None) -> dict[str, bool]:
    current = settings_obj or settings
    stripe_requested = current.PAYMENT_BACKEND == "stripe"
    publishable_key_ready = _is_configured(current.STRIPE_PUBLISHABLE_KEY)
    secret_key_ready = _is_configured(current.STRIPE_SECRET_KEY)
    webhook_secret_ready = _is_configured(current.STRIPE_WEBHOOK_SECRET)
    return {
        "stripe_requested": stripe_requested,
        "stripe_publishable_key_ready": publishable_key_ready,
        "stripe_secret_key_ready": secret_key_ready,
        "stripe_webhook_secret_ready": webhook_secret_ready,
        "stripe_payments_ready": stripe_requested and secret_key_ready,
        "stripe_checkout_ready": stripe_requested and publishable_key_ready and secret_key_ready,
        "stripe_webhooks_ready": stripe_requested and webhook_secret_ready,
        "stripe_fully_ready": stripe_requested
        and publishable_key_ready
        and secret_key_ready
        and webhook_secret_ready,
    }


def get_supabase_configuration_status(settings_obj: Optional[Settings] = None) -> dict[str, bool]:
    current = settings_obj or settings
    url_ready = _is_configured(current.SUPABASE_URL)
    publishable_key_ready = _is_configured(current.SUPABASE_PUBLISHABLE_KEY)
    return {
        "supabase_url_ready": url_ready,
        "supabase_publishable_key_ready": publishable_key_ready,
        "supabase_fully_ready": url_ready and publishable_key_ready,
    }


def validate_runtime_configuration(settings_obj: Optional[Settings] = None) -> None:
    current = settings_obj or settings
    environment = current.APP_ENV.lower().strip()
    if environment != "production":
        return

    errors: list[str] = []

    if len(current.SECRET_KEY) < 32 or _looks_placeholder(current.SECRET_KEY):
        errors.append("SECRET_KEY must be a strong non-placeholder value in production")
    if not current.APP_BASE_URL.startswith("https://"):
        errors.append("APP_BASE_URL must use https in production")
    if current.PAYMENT_BACKEND != "stripe":
        errors.append("PAYMENT_BACKEND must be stripe in production")
    if current.EMAIL_BACKEND not in {"disabled", "sendgrid", "smtp"}:
        errors.append("EMAIL_BACKEND must be disabled, sendgrid, or smtp in production")
    if current.CELERY_TASK_ALWAYS_EAGER and not getattr(current, "ALLOW_INLINE_TASKS_IN_PRODUCTION", False):
        errors.append(
            "CELERY_TASK_ALWAYS_EAGER must be false in production unless ALLOW_INLINE_TASKS_IN_PRODUCTION is true"
        )
    if any("localhost" in origin or "127.0.0.1" in origin for origin in current.cors_origins):
        errors.append("ALLOWED_CORS_ORIGINS must not include localhost in production")
    supabase_url = getattr(current, "SUPABASE_URL", "") or ""
    supabase_publishable_key = getattr(current, "SUPABASE_PUBLISHABLE_KEY", "") or ""
    if supabase_url or supabase_publishable_key:
        if not supabase_url or _looks_placeholder(supabase_url):
            errors.append("SUPABASE_URL must be configured when Supabase auth is enabled")
        if not supabase_publishable_key or _looks_placeholder(supabase_publishable_key):
            errors.append("SUPABASE_PUBLISHABLE_KEY must be configured when Supabase auth is enabled")
    if current.PAYMENT_BACKEND == "stripe":
        if not current.STRIPE_PUBLISHABLE_KEY or _looks_placeholder(current.STRIPE_PUBLISHABLE_KEY):
            errors.append("STRIPE_PUBLISHABLE_KEY must be configured when PAYMENT_BACKEND is stripe")
        if _looks_placeholder(current.STRIPE_SECRET_KEY):
            errors.append("STRIPE_SECRET_KEY must be configured when PAYMENT_BACKEND is stripe")
        if _looks_placeholder(current.STRIPE_WEBHOOK_SECRET):
            errors.append("STRIPE_WEBHOOK_SECRET must be configured when PAYMENT_BACKEND is stripe")
    if current.EMAIL_BACKEND == "sendgrid":
        if _looks_placeholder(current.SENDGRID_API_KEY):
            errors.append("SENDGRID_API_KEY must be configured in production")
    if current.EMAIL_BACKEND == "smtp":
        if not current.SMTP_HOST or _looks_placeholder(current.SMTP_HOST):
            errors.append("SMTP_HOST must be configured when EMAIL_BACKEND is smtp")
        if not current.SMTP_PORT or current.SMTP_PORT <= 0:
            errors.append("SMTP_PORT must be a positive integer when EMAIL_BACKEND is smtp")
        if not current.SMTP_USERNAME or _looks_placeholder(current.SMTP_USERNAME):
            errors.append("SMTP_USERNAME must be configured when EMAIL_BACKEND is smtp")
        if not current.SMTP_PASSWORD or _looks_placeholder(current.SMTP_PASSWORD):
            errors.append("SMTP_PASSWORD must be configured when EMAIL_BACKEND is smtp")
    if _looks_placeholder(current.EMAIL_FROM):
        errors.append("EMAIL_FROM must use a real sender address in production")
    if current.SMS_BACKEND == "twilio":
        if not current.TWILIO_ACCOUNT_SID or _looks_placeholder(current.TWILIO_ACCOUNT_SID):
            errors.append("TWILIO_ACCOUNT_SID must be configured when SMS_BACKEND is twilio")
        if not current.TWILIO_AUTH_TOKEN or _looks_placeholder(current.TWILIO_AUTH_TOKEN):
            errors.append("TWILIO_AUTH_TOKEN must be configured when SMS_BACKEND is twilio")
        if not current.TWILIO_FROM_NUMBER or _looks_placeholder(current.TWILIO_FROM_NUMBER):
            errors.append("TWILIO_FROM_NUMBER must be configured when SMS_BACKEND is twilio")

    if errors:
        raise RuntimeConfigurationError("; ".join(errors))

settings = Settings()
