import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import payment_service


def _paypal_settings(**overrides):
    values = {
        "PAYMENT_BACKEND": "paypal",
        "PAYPAL_CLIENT_ID": "AeXAMPLEclientIDvalue1234567890",
        "PAYPAL_CLIENT_SECRET": "EExAMPLEsecretVALUE1234567890",
        "PAYPAL_WEBHOOK_ID": "4JH86294D6297924G",
        "PAYPAL_ENV": "sandbox",
        "PAYPAL_TIMEOUT_SECONDS": 20,
        "DEFAULT_CURRENCY": "CAD",
        "SECRET_KEY": "app-secret",
        "SENDGRID_API_KEY": "",
        "RESEND_API_KEY": "",
        "EMAIL_FUNCTION_SECRET": "",
        "SMTP_PASSWORD": "",
        "TWILIO_AUTH_TOKEN": "",
        "SUITEDASH_SECRET_KEY": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PaymentServiceTest(unittest.TestCase):
    def test_paypal_checkout_requires_real_credentials(self) -> None:
        fake_settings = _paypal_settings(
            PAYPAL_CLIENT_ID="change_me",
            PAYPAL_CLIENT_SECRET="change_me",
        )

        with patch.object(payment_service, "settings", fake_settings):
            with self.assertRaises(payment_service.PaymentConfigurationError):
                payment_service.get_payment_intent_session(
                    payment_intent_id=None,
                    amount_cents=5000,
                    currency="CAD",
                    booking_id="booking_123",
                    user_email="user@example.com",
                )

    def test_paypal_create_payment_intent_returns_order_id(self) -> None:
        fake_settings = _paypal_settings()
        fake_order = {"id": "5O190127TN364715T", "status": "CREATED"}

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(payment_service, "get_paypal_access_token", return_value="token"):
                with patch.object(
                    payment_service, "_paypal_request", return_value=fake_order
                ) as request_mock:
                    result = payment_service.create_payment_intent(
                        amount_cents=8500,
                        currency="CAD",
                        booking_id="booking_123",
                        user_email="user@example.com",
                    )

        self.assertEqual(result.intent_id, "5O190127TN364715T")
        self.assertEqual(result.client_secret, "5O190127TN364715T")
        request_mock.assert_called_once()
        body = request_mock.call_args.kwargs["json_body"]
        self.assertEqual(body["intent"], "CAPTURE")
        self.assertEqual(body["purchase_units"][0]["amount"]["value"], "85.00")
        self.assertEqual(body["purchase_units"][0]["amount"]["currency_code"], "CAD")

    def test_paypal_payment_session_recreates_stub_intents(self) -> None:
        fake_settings = _paypal_settings()
        fake_order = {"id": "8XY12345AB678901C", "status": "CREATED"}

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(payment_service, "get_paypal_order") as lookup_mock:
                with patch.object(
                    payment_service, "_paypal_request", return_value=fake_order
                ) as create_mock:
                    result = payment_service.get_payment_intent_session(
                        payment_intent_id="pi_stub_existing",
                        amount_cents=8500,
                        currency="CAD",
                        booking_id="booking_123",
                        user_email="user@example.com",
                    )

        lookup_mock.assert_not_called()
        create_mock.assert_called_once()
        self.assertEqual(result.intent_id, "8XY12345AB678901C")

    def test_paypal_payment_session_reuses_payable_order(self) -> None:
        fake_settings = _paypal_settings()
        existing_order = {
            "id": "5O190127TN364715T",
            "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "CAD", "value": "85.00"}}],
        }

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(
                payment_service, "get_paypal_order", return_value=existing_order
            ) as lookup_mock:
                with patch.object(payment_service, "_paypal_request") as create_mock:
                    result = payment_service.get_payment_intent_session(
                        payment_intent_id="5O190127TN364715T",
                        amount_cents=8500,
                        currency="CAD",
                        booking_id="booking_123",
                        user_email="user@example.com",
                    )

        lookup_mock.assert_called_once_with("5O190127TN364715T")
        create_mock.assert_not_called()
        self.assertEqual(result.intent_id, "5O190127TN364715T")

    def test_stub_backend_returns_stub_intents(self) -> None:
        fake_settings = _paypal_settings(PAYMENT_BACKEND="stub")
        with patch.object(payment_service, "settings", fake_settings):
            result = payment_service.create_payment_intent(
                amount_cents=5000,
                currency="CAD",
                booking_id="booking_123",
                user_email="user@example.com",
            )
        self.assertTrue(result.intent_id.startswith("pi_stub_"))
        self.assertTrue(result.client_secret.startswith("pi_client_secret_stub_"))

    def test_custom_id_roundtrip(self) -> None:
        encoded = payment_service.encode_custom_id(
            "booking_123", {"booking_type": "staff", "staff_booking_id": "booking_123"}
        )
        self.assertLessEqual(len(encoded), 127)
        decoded = payment_service.decode_custom_id(encoded)
        self.assertEqual(decoded["booking_id"], "booking_123")
        self.assertEqual(decoded["booking_type"], "staff")
        # A bare (non-JSON) custom id degrades to just the booking id.
        self.assertEqual(payment_service.decode_custom_id("booking_9"), {"booking_id": "booking_9"})

    def test_translate_capture_completed_event(self) -> None:
        event = {
            "id": "WH-58D329510W468432D-8HN650336L201105X",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {
                "id": "3C679366HH908993F",
                "custom_id": '{"booking_id":"booking_123"}',
                "supplementary_data": {"related_ids": {"order_id": "5O190127TN364715T"}},
            },
        }
        internal = payment_service.translate_paypal_webhook_event(event)
        self.assertEqual(internal["type"], "payment_intent.succeeded")
        self.assertEqual(internal["id"], "WH-58D329510W468432D-8HN650336L201105X")
        self.assertEqual(internal["data"]["object"]["id"], "5O190127TN364715T")
        self.assertEqual(internal["data"]["object"]["metadata"]["booking_id"], "booking_123")

    def test_translate_refund_event_carries_amount(self) -> None:
        event = {
            "id": "WH-refund-1",
            "event_type": "PAYMENT.CAPTURE.REFUNDED",
            "resource": {
                "id": "1JU08902781691411",
                "custom_id": '{"booking_id":"booking_123"}',
                "amount": {"currency_code": "CAD", "value": "10.99"},
                "seller_payable_breakdown": {
                    "total_refunded_amount": {"currency_code": "CAD", "value": "10.99"}
                },
            },
        }
        internal = payment_service.translate_paypal_webhook_event(event)
        self.assertEqual(internal["type"], "charge.refunded")
        self.assertEqual(internal["data"]["object"]["amount_refunded"], 1099)

    def test_translate_ignores_unhandled_events(self) -> None:
        event = {"id": "WH-x", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {}}
        self.assertIsNone(payment_service.translate_paypal_webhook_event(event))

    def test_provider_error_redacts_secret_like_tokens(self) -> None:
        fake_settings = _paypal_settings(PAYPAL_CLIENT_SECRET="super-secret-paypal-value")

        class FakeResponse:
            status_code = 400
            content = b"{}"

            def json(self):
                return {
                    "name": "INVALID_REQUEST",
                    "message": "bad credential super-secret-paypal-value",
                }

        with patch.object(payment_service, "settings", fake_settings):
            with patch.object(payment_service, "get_paypal_access_token", return_value="token"):
                with patch.object(
                    payment_service.httpx, "request", return_value=FakeResponse()
                ):
                    with self.assertRaises(payment_service.PaymentProviderError) as context:
                        payment_service._paypal_request(
                            "POST", "/v2/checkout/orders", purpose="payment setup", json_body={}
                        )

        self.assertNotIn("super-secret-paypal-value", str(context.exception))


if __name__ == "__main__":
    unittest.main()
