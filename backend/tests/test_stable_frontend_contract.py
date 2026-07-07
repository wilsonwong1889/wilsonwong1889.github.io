from pathlib import Path
import re
import unittest


class StableFrontendContractTest(unittest.TestCase):
    """Locked frontend shell contracts.

    These assertions are meant to change only when the shared product shell or
    legal/footer contract changes intentionally.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.frontend_dir = Path(__file__).resolve().parents[1] / "app" / "frontend"
        cls.html_files = sorted(cls.frontend_dir.glob("*.html"))

    def test_all_html_pages_load_shared_app_assets(self) -> None:
        self.assertTrue(self.html_files)

        for html_file in self.html_files:
            content = html_file.read_text(encoding="utf-8")
            self.assertRegex(
                content,
                r'<body[^>]+data-page="[^"]+"',
                f"{html_file.name} should declare a routed data-page marker.",
            )
            self.assertIn(
                '/assets/styles/app.css?v=',
                content,
                f"{html_file.name} should load the shared frontend stylesheet.",
            )
            self.assertIn(
                '/assets/js/main.js?v=',
                content,
                f"{html_file.name} should load the shared frontend entry module.",
            )

    def test_all_html_pages_include_acknowledgement_and_legal_footer(self) -> None:
        self.assertTrue(self.html_files)

        required_strings = (
            "site-acknowledgement",
            "BIPOC Foundation is situated on the unceded, traditional and ancestral Siksikaitsitapii",
            "Powered by BIPOC Foundation.",
        )
        stale_copyright = "Copyright &copy; 2026 - media arts collective. All Rights Reserved."

        for html_file in self.html_files:
            content = html_file.read_text(encoding="utf-8")
            for required in required_strings:
                self.assertIn(required, content, f"{html_file.name} is missing footer text: {required}")
            self.assertNotIn(
                stale_copyright,
                content,
                f"{html_file.name} should use the BIPOC Creative Innovation Studio footer copyright, not stale media arts collective copy.",
            )

    def test_checkout_page_keeps_paypal_checkout_contract(self) -> None:
        booking_page = (self.frontend_dir / "booking.html").read_text(encoding="utf-8")

        self.assertNotIn(
            'https://js.stripe.com/v3/',
            booking_page,
            "booking.html must not load Stripe.js — checkout moved to PayPal.",
        )
        self.assertIn(
            'id="booking-payment-element"',
            booking_page,
            "booking.html should keep the container the PayPal buttons mount into.",
        )
        self.assertIn("PayPal securely handles the payment", booking_page)
        self.assertIn("booking-detail-card", booking_page)
        self.assertIn("Booking summary", booking_page)
        self.assertIn("Payment details", booking_page)
