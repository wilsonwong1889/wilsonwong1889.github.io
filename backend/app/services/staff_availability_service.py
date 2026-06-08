from __future__ import annotations

from datetime import date
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.staff_availability import StaffAvailabilityException, StaffAvailabilityRule
from app.schemas.staff_availability import (
    StaffAvailabilityBulkRuleCreate,
    StaffAvailabilityExceptionCreate,
    StaffAvailabilityRuleCreate,
    StaffWeekdayWindowsUpdate,
)

WHOLE_DAY: Tuple[int, int] = (0, 1440)


class StaffAvailabilityError(ValueError):
    """Raised for invalid availability operations (surfaced as 400/404)."""


# ── CRUD: weekly rules ───────────────────────────────────────────────────────

def list_rules(db: Session, staff_profile_id) -> List[StaffAvailabilityRule]:
    return (
        db.query(StaffAvailabilityRule)
        .filter(StaffAvailabilityRule.staff_profile_id == staff_profile_id)
        .order_by(StaffAvailabilityRule.weekday, StaffAvailabilityRule.start_minute)
        .all()
    )


def create_rule(db: Session, staff_profile_id, payload: StaffAvailabilityRuleCreate) -> StaffAvailabilityRule:
    rule = StaffAvailabilityRule(
        staff_profile_id=staff_profile_id,
        weekday=payload.weekday,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
        active=payload.active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def create_rules_bulk(
    db: Session, staff_profile_id, payload: StaffAvailabilityBulkRuleCreate
) -> List[StaffAvailabilityRule]:
    """Create one window across several weekdays in a single action. Skips a day
    that already has an identical window so re-applying is harmless."""
    existing = {
        (rule.weekday, rule.start_minute, rule.end_minute)
        for rule in list_rules(db, staff_profile_id)
    }
    created: List[StaffAvailabilityRule] = []
    for weekday in sorted(set(payload.weekdays)):
        if (weekday, payload.start_minute, payload.end_minute) in existing:
            continue
        rule = StaffAvailabilityRule(
            staff_profile_id=staff_profile_id,
            weekday=weekday,
            start_minute=payload.start_minute,
            end_minute=payload.end_minute,
            active=payload.active,
        )
        db.add(rule)
        created.append(rule)
    if created:
        db.commit()
        for rule in created:
            db.refresh(rule)
    return created


def set_weekday_rules(
    db: Session, staff_profile_id, weekday: int, payload: StaffWeekdayWindowsUpdate
) -> List[StaffAvailabilityRule]:
    """Replace every window for one weekday with the provided set (Calendly-style
    per-day editor). Empty windows = the day is unavailable."""
    if weekday < 0 or weekday > 6:
        raise StaffAvailabilityError("weekday must be 0 (Monday) through 6 (Sunday)")
    db.query(StaffAvailabilityRule).filter(
        StaffAvailabilityRule.staff_profile_id == staff_profile_id,
        StaffAvailabilityRule.weekday == weekday,
    ).delete()
    created: List[StaffAvailabilityRule] = []
    for window in payload.windows:
        rule = StaffAvailabilityRule(
            staff_profile_id=staff_profile_id,
            weekday=weekday,
            start_minute=window.start_minute,
            end_minute=window.end_minute,
            active=True,
        )
        db.add(rule)
        created.append(rule)
    db.commit()
    for rule in created:
        db.refresh(rule)
    return created


def delete_rule(db: Session, staff_profile_id, rule_id) -> None:
    rule = (
        db.query(StaffAvailabilityRule)
        .filter(StaffAvailabilityRule.id == rule_id, StaffAvailabilityRule.staff_profile_id == staff_profile_id)
        .first()
    )
    if not rule:
        raise StaffAvailabilityError("Availability rule not found")
    db.delete(rule)
    db.commit()


# ── CRUD: one-off exceptions ─────────────────────────────────────────────────

def list_exceptions(db: Session, staff_profile_id) -> List[StaffAvailabilityException]:
    return (
        db.query(StaffAvailabilityException)
        .filter(StaffAvailabilityException.staff_profile_id == staff_profile_id)
        .order_by(StaffAvailabilityException.exception_date.desc())
        .all()
    )


def create_exception(
    db: Session, staff_profile_id, payload: StaffAvailabilityExceptionCreate
) -> StaffAvailabilityException:
    exception = StaffAvailabilityException(
        staff_profile_id=staff_profile_id,
        exception_date=payload.exception_date,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
        is_available=payload.is_available,
        reason=(payload.reason or "").strip() or None,
    )
    db.add(exception)
    db.commit()
    db.refresh(exception)
    return exception


def delete_exception(db: Session, staff_profile_id, exception_id) -> None:
    exception = (
        db.query(StaffAvailabilityException)
        .filter(
            StaffAvailabilityException.id == exception_id,
            StaffAvailabilityException.staff_profile_id == staff_profile_id,
        )
        .first()
    )
    if not exception:
        raise StaffAvailabilityError("Availability exception not found")
    db.delete(exception)
    db.commit()


def has_availability_rules(db: Session, staff_profile_id) -> bool:
    return (
        db.query(StaffAvailabilityRule)
        .filter(StaffAvailabilityRule.staff_profile_id == staff_profile_id, StaffAvailabilityRule.active.is_(True))
        .first()
        is not None
    )


# ── Window computation (business-local minutes) ──────────────────────────────

def _subtract(windows: List[Tuple[int, int]], block: Tuple[int, int]) -> List[Tuple[int, int]]:
    block_start, block_end = block
    result: List[Tuple[int, int]] = []
    for win_start, win_end in windows:
        if block_end <= win_start or block_start >= win_end:
            result.append((win_start, win_end))
            continue
        if block_start > win_start:
            result.append((win_start, block_start))
        if block_end < win_end:
            result.append((block_end, win_end))
    return result


def _merge(windows: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [ordered[0]]
    for win_start, win_end in ordered[1:]:
        last_start, last_end = merged[-1]
        if win_start <= last_end:
            merged[-1] = (last_start, max(last_end, win_end))
        else:
            merged.append((win_start, win_end))
    return merged


def _within_windows(windows: List[Tuple[int, int]], start_minute: int, end_minute: int) -> bool:
    """True if [start_minute, end_minute) fits entirely inside one window."""
    return any(win_start <= start_minute and end_minute <= win_end for win_start, win_end in windows)


def available_windows_for_date(
    db: Session,
    staff_profile_id,
    target_date: date,
    base_windows: List[Tuple[int, int]] | None = None,
) -> List[Tuple[int, int]]:
    """Merged available windows (minutes-from-midnight, business-local) for a
    staff member on a given date: a base (weekly rules for that weekday, or an
    explicit ``base_windows`` fallback), plus extra-available exceptions, minus
    blocked exceptions."""
    if base_windows is None:
        rules = (
            db.query(StaffAvailabilityRule)
            .filter(
                StaffAvailabilityRule.staff_profile_id == staff_profile_id,
                StaffAvailabilityRule.active.is_(True),
                StaffAvailabilityRule.weekday == target_date.weekday(),
            )
            .all()
        )
        windows: List[Tuple[int, int]] = [(rule.start_minute, rule.end_minute) for rule in rules]
    else:
        windows = list(base_windows)

    exceptions = (
        db.query(StaffAvailabilityException)
        .filter(
            StaffAvailabilityException.staff_profile_id == staff_profile_id,
            StaffAvailabilityException.exception_date == target_date,
        )
        .all()
    )

    for exception in exceptions:
        if exception.is_available:
            span = (exception.start_minute, exception.end_minute) if exception.start_minute is not None else WHOLE_DAY
            windows.append(span)
    windows = _merge(windows)

    for exception in exceptions:
        if not exception.is_available:
            block = (exception.start_minute, exception.end_minute) if exception.start_minute is not None else WHOLE_DAY
            windows = _subtract(windows, block)

    return _merge(windows)
