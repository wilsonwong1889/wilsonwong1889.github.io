"""
Centralised pricing engine for membership-tier-based booking costs.

All monetary values are in **cents** (CAD).
A return value of ``None`` means the rate is TBC and must be set manually by an admin.
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Category registry
# ---------------------------------------------------------------------------

USER_CATEGORIES: set[str] = {
    "artist_member",
    "fellowship_artist",
    "artist_in_residence",
    "service_engineer",
    "bipoc_community_member",
    "venture_member",
    "organizational_member",
    "general_public",
}

# ---------------------------------------------------------------------------
# Hourly rates (cents)  — single room booking
# ---------------------------------------------------------------------------

ROOM_HOURLY_RATES: dict[str, Optional[int]] = {
    "artist_member": 5000,           # $50/hr
    "fellowship_artist": 5000,       # $50/hr
    "artist_in_residence": 5000,     # $50/hr
    "service_engineer": 5000,        # $50/hr
    "bipoc_community_member": 7500,  # $75/hr
    "venture_member": 5000,          # $50/hr (after free hours are exhausted)
    "organizational_member": None,   # TBC — admin sets manually
    "general_public": 10000,         # $100/hr
}

# ---------------------------------------------------------------------------
# Hourly rates (cents)  — full-space booking
# ---------------------------------------------------------------------------

FULL_SPACE_HOURLY_RATES: dict[str, Optional[int]] = {
    "artist_member": 10000,           # $100/hr
    "fellowship_artist": 10000,       # $100/hr
    "artist_in_residence": 10000,     # $100/hr
    "service_engineer": 10000,        # $100/hr
    "bipoc_community_member": 15000,  # $150/hr
    "venture_member": 10000,          # $100/hr
    "organizational_member": None,    # TBC
    "general_public": 20000,          # $200/hr
}

# ---------------------------------------------------------------------------
# Membership subscription fees (cents)
# ---------------------------------------------------------------------------

MEMBERSHIP_FEES: dict[str, dict[str, Optional[int]]] = {
    "artist_member": {"monthly_cents": 1500, "annual_cents": 12000},
    "fellowship_artist": {"monthly_cents": 0, "annual_cents": 0},
    "artist_in_residence": {"monthly_cents": 0, "annual_cents": 0},
    "service_engineer": {"monthly_cents": 0, "annual_cents": 0},
    "bipoc_community_member": {"monthly_cents": 0, "annual_cents": 0},
    "venture_member": {"monthly_cents": None, "annual_cents": None},       # TBC
    "organizational_member": {"monthly_cents": None, "annual_cents": None},  # TBC
    "general_public": {"monthly_cents": 0, "annual_cents": 0},
}

# ---------------------------------------------------------------------------
# Deposit amounts
# ---------------------------------------------------------------------------

DEPOSIT_SPACE_ONLY_CENTS: int = 2000   # $20
DEPOSIT_WITH_ENGINEER_CENTS: int = 2000  # $20

# ---------------------------------------------------------------------------
# Booking constraints
# ---------------------------------------------------------------------------

DAILY_HOUR_LIMIT: int = 5
BOOKING_INCREMENT_HOURS: int = 1
MIN_BOOKING_HOURS: int = 1
MAX_BOOKING_HOURS: int = 5

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_hourly_rate(category: str, booking_type: str = "room") -> Optional[int]:
    """Return the hourly rate in cents for *category* and *booking_type*.

    Returns ``None`` when the rate is TBC (must be negotiated / set by admin).
    Falls back to ``general_public`` rate for unknown categories.
    """
    if booking_type == "full_space":
        return FULL_SPACE_HOURLY_RATES.get(
            category, FULL_SPACE_HOURLY_RATES["general_public"]
        )
    return ROOM_HOURLY_RATES.get(category, ROOM_HOURLY_RATES["general_public"])


def calculate_booking_cost(
    category: str,
    duration_minutes: int,
    booking_type: str = "room",
) -> Optional[int]:
    """Return the total booking cost in cents, or ``None`` if the rate is TBC.

    Args:
        category: Member category string (see ``USER_CATEGORIES``).
        duration_minutes: Booking length in minutes (must be a multiple of 60).
        booking_type: ``"room"`` (default) or ``"full_space"``.
    """
    rate = get_hourly_rate(category, booking_type)
    if rate is None:
        return None
    hours = duration_minutes / 60
    return int(rate * hours)


def get_deposit_amount(*, with_engineer: bool) -> int:
    """Return the required deposit in cents."""
    return DEPOSIT_WITH_ENGINEER_CENTS if with_engineer else DEPOSIT_SPACE_ONLY_CENTS
