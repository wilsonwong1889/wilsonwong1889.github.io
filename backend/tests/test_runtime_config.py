import unittest
from types import SimpleNamespace

from app.config import (
    RuntimeConfigurationError,
    get_payment_backend,
    get_paypal_configuration_status,
    get_supabase_configuration_status,
    mask_secret,
    redact_sensitive_text,
    Settings,
    validate_runtime_configuration,
)


class RuntimeConfigurationTest(unittest.TestCase):
    def test_development_allows_local_stub_settings(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="development",
            SECRET_KEY="change-me-use-a-long-random-secret-key",
            APP_BASE_URL="http://localhost:8000",
            PAYMENT_BACKEND="stub",
            EMAIL_BACKEND="console",
            CELERY_TASK_ALWAYS_EAGER=True,
            cors_origins=["http://localhost:3000"],
            PAYPAL_CLIENT_ID="",
            PAYPAL_CLIENT_SECRET="",
            PAYPAL_WEBHOOK_ID="",
            PAYPAL_ENV="sandbox",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="noreply@example.com",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_rejects_placeholder_settings(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="change-me-use-a-long-random-secret-key",
            APP_BASE_URL="http://localhost:8000",
            PAYMENT_BACKEND="stub",
            EMAIL_BACKEND="console",
            CELERY_TASK_ALWAYS_EAGER=True,
            cors_origins=["http://localhost:3000"],
            PAYPAL_CLIENT_ID="change_me",
            PAYPAL_CLIENT_SECRET="change_me",
            PAYPAL_WEBHOOK_ID="change_me",
            PAYPAL_ENV="sandbox",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="noreply@example.com",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        with self.assertRaises(RuntimeConfigurationError):
            validate_runtime_configuration(settings_obj)

    def test_payment_backend_is_normalized(self) -> None:
        settings_obj = SimpleNamespace(PAYMENT_BACKEND=" PayPal ")

        self.assertEqual(get_payment_backend(settings_obj), "paypal")

    def test_production_accepts_normalized_paypal_backend(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND=" PayPal ",
            EMAIL_BACKEND="disabled",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_accepts_realistic_settings(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="sendgrid",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.realistic_key_value",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="twilio",
            TWILIO_ACCOUNT_SID="ACrealisticvalue1234567890",
            TWILIO_AUTH_TOKEN="twilio_auth_token_realistic",
            TWILIO_FROM_NUMBER="+14035550123",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_accepts_sandbox_paypal_for_test_mode(self) -> None:
        # The live site intentionally runs test-mode payments until real
        # payouts start, so sandbox credentials must pass validation.
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="disabled",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticSandboxClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticSandboxSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="sandbox",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_rejects_stub_payment_backend(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="stub",
            EMAIL_BACKEND="disabled",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="",
            PAYPAL_CLIENT_SECRET="",
            PAYPAL_WEBHOOK_ID="",
            PAYPAL_ENV="sandbox",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        with self.assertRaises(RuntimeConfigurationError) as context:
            validate_runtime_configuration(settings_obj)
        self.assertIn("PAYMENT_BACKEND must be paypal in production (current: stub)", str(context.exception))

    def test_production_rejects_missing_paypal_webhook_id(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="disabled",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        with self.assertRaises(RuntimeConfigurationError):
            validate_runtime_configuration(settings_obj)

    def test_production_accepts_inline_tasks_when_explicitly_allowed(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="disabled",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=True,
            ALLOW_INLINE_TASKS_IN_PRODUCTION=True,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_rejects_placeholder_twilio_settings(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="sendgrid",
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.realistic_key_value",
            EMAIL_FROM="bookings@studio.example.ca",
            SMS_BACKEND="twilio",
            TWILIO_ACCOUNT_SID="AC_change_me",
            TWILIO_AUTH_TOKEN="change_me",
            TWILIO_FROM_NUMBER="+15551234567",
        )

        with self.assertRaises(RuntimeConfigurationError):
            validate_runtime_configuration(settings_obj)

    def test_production_accepts_realistic_smtp_settings(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="smtp",
            SMTP_HOST="smtp.gmail.com",
            SMTP_PORT=587,
            SMTP_USERNAME="bookings@studio.ca",
            SMTP_PASSWORD="realistic_app_password_123",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        validate_runtime_configuration(settings_obj)

    def test_production_rejects_missing_smtp_password(self) -> None:
        settings_obj = SimpleNamespace(
            APP_ENV="production",
            SECRET_KEY="super-long-live-secret-with-entropy-1234567890",
            APP_BASE_URL="https://studio.example.ca",
            PAYMENT_BACKEND="paypal",
            EMAIL_BACKEND="smtp",
            SMTP_HOST="smtp.gmail.com",
            SMTP_PORT=587,
            SMTP_USERNAME="bookings@studio.ca",
            SMTP_PASSWORD="",
            CELERY_TASK_ALWAYS_EAGER=False,
            cors_origins=["https://studio.example.ca"],
            PAYPAL_CLIENT_ID="AeRealisticLiveClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticLiveSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
            PAYPAL_ENV="live",
            SENDGRID_API_KEY="SG.change-me",
            EMAIL_FROM="bookings@studio.ca",
            SMS_BACKEND="console",
            TWILIO_ACCOUNT_SID="",
            TWILIO_AUTH_TOKEN="",
            TWILIO_FROM_NUMBER="",
        )

        with self.assertRaises(RuntimeConfigurationError):
            validate_runtime_configuration(settings_obj)

    def test_paypal_configuration_status_flags_stub_mode_as_not_ready(self) -> None:
        settings_obj = SimpleNamespace(
            PAYMENT_BACKEND="stub",
            PAYPAL_CLIENT_ID="change_me",
            PAYPAL_CLIENT_SECRET="change_me",
            PAYPAL_WEBHOOK_ID="change_me",
        )

        status = get_paypal_configuration_status(settings_obj)

        self.assertFalse(status["paypal_requested"])
        self.assertFalse(status["paypal_checkout_ready"])
        self.assertFalse(status["paypal_webhooks_ready"])
        self.assertFalse(status["paypal_fully_ready"])

    def test_paypal_configuration_status_requires_real_keys(self) -> None:
        settings_obj = SimpleNamespace(
            PAYMENT_BACKEND="paypal",
            PAYPAL_CLIENT_ID="AeRealisticClientId1234567890",
            PAYPAL_CLIENT_SECRET="EeRealisticSecret1234567890",
            PAYPAL_WEBHOOK_ID="4JH86294D6297924G",
        )

        status = get_paypal_configuration_status(settings_obj)

        self.assertTrue(status["paypal_requested"])
        self.assertTrue(status["paypal_payments_ready"])
        self.assertTrue(status["paypal_checkout_ready"])
        self.assertTrue(status["paypal_webhooks_ready"])
        self.assertTrue(status["paypal_fully_ready"])

    def test_supabase_configuration_status_requires_url_and_publishable_key(self) -> None:
        settings_obj = SimpleNamespace(
            SUPABASE_URL="https://project.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_key",
        )

        status = get_supabase_configuration_status(settings_obj)

        self.assertTrue(status["supabase_url_ready"])
        self.assertTrue(status["supabase_publishable_key_ready"])
        self.assertTrue(status["supabase_fully_ready"])

    def test_settings_repr_hides_secret_fields(self) -> None:
        settings_obj = Settings(
            DATABASE_URL="sqlite:///test.db",
            SECRET_KEY="super-secret-app-key",
            PAYPAL_CLIENT_ID="AeVisibleClientIdValue",
            PAYPAL_CLIENT_SECRET="paypal-hidden-secret-value",
        )

        settings_repr = repr(settings_obj)

        self.assertIn("PAYPAL_CLIENT_ID='AeVisibleClientIdValue'", settings_repr)
        self.assertNotIn("super-secret-app-key", settings_repr)
        self.assertNotIn("paypal-hidden-secret-value", settings_repr)

    def test_redact_sensitive_text_masks_known_secret_values(self) -> None:
        settings_obj = SimpleNamespace(
            SECRET_KEY="super-secret-app-key",
            PAYPAL_CLIENT_SECRET="paypal-hidden-secret-value",
            SENDGRID_API_KEY="SG.hidden-value",
            SMTP_PASSWORD="smtp-secret-password",
            TWILIO_AUTH_TOKEN="twilio-secret-token",
            SUITEDASH_SECRET_KEY="suitedash-secret",
        )

        text = (
            "paypal=paypal-hidden-secret-value "
            "sendgrid=SG.hidden-value app=super-secret-app-key"
        )
        redacted = redact_sensitive_text(text, settings_obj)

        self.assertNotIn("paypal-hidden-secret-value", redacted)
        self.assertNotIn("SG.hidden-value", redacted)
        self.assertNotIn("super-secret-app-key", redacted)
        self.assertIn(mask_secret("super-secret-app-key"), redacted)


if __name__ == "__main__":
    unittest.main()
