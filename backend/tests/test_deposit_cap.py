"""The deposit charged up front is capped at the (post-discount) total, so a
100%-off promo makes a booking free instead of hard-charging $21."""
import unittest
from types import SimpleNamespace

from app.services.booking_service.core import upfront_charge_cents


class DepositCapTest(unittest.TestCase):
    @staticmethod
    def _booking(price_cents, deposit_amount_cents):
        return SimpleNamespace(
            price_cents=price_cents, deposit_amount_cents=deposit_amount_cents
        )

    def test_full_price_pays_capped_deposit(self) -> None:
        # $105 total, $20 deposit + 5% GST = $21 due now.
        self.assertEqual(upfront_charge_cents(self._booking(10500, 2000)), 2100)

    def test_hundred_percent_off_is_free(self) -> None:
        # 100%-off promo -> $0 total -> $0 due now (not a hardcoded $21).
        self.assertEqual(upfront_charge_cents(self._booking(0, 2000)), 0)

    def test_total_below_deposit_pays_full_total(self) -> None:
        # A big discount that leaves the total under the deposit is paid in full.
        self.assertEqual(upfront_charge_cents(self._booking(1000, 2000)), 1000)

    def test_no_deposit_configured_pays_full_total(self) -> None:
        self.assertEqual(upfront_charge_cents(self._booking(5000, 0)), 5000)


if __name__ == "__main__":
    unittest.main()
