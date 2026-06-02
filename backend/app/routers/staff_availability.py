from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_admin_user
from app.database import get_db
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.schemas.staff_availability import (
    StaffAvailabilityExceptionCreate,
    StaffAvailabilityExceptionOut,
    StaffAvailabilityRuleCreate,
    StaffAvailabilityRuleOut,
)
from app.services import staff_availability_service as availability

router = APIRouter(prefix="/api/admin/staff", tags=["Staff Availability"])


def _ensure_staff_exists(db: Session, staff_profile_id: UUID) -> None:
    if not db.query(StaffProfile).filter(StaffProfile.id == staff_profile_id).first():
        raise HTTPException(status_code=404, detail="Staff profile not found")


# ── Weekly rules ─────────────────────────────────────────────────────────────

@router.get("/{staff_profile_id}/availability/rules", response_model=List[StaffAvailabilityRuleOut])
def list_rules(
    staff_profile_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    _ensure_staff_exists(db, staff_profile_id)
    return availability.list_rules(db, staff_profile_id)


@router.post(
    "/{staff_profile_id}/availability/rules",
    response_model=StaffAvailabilityRuleOut,
    status_code=201,
)
def create_rule(
    staff_profile_id: UUID,
    payload: StaffAvailabilityRuleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    _ensure_staff_exists(db, staff_profile_id)
    return availability.create_rule(db, staff_profile_id, payload)


@router.delete("/{staff_profile_id}/availability/rules/{rule_id}", status_code=204)
def delete_rule(
    staff_profile_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    try:
        availability.delete_rule(db, staff_profile_id, rule_id)
    except availability.StaffAvailabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── One-off exceptions ───────────────────────────────────────────────────────

@router.get("/{staff_profile_id}/availability/exceptions", response_model=List[StaffAvailabilityExceptionOut])
def list_exceptions(
    staff_profile_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    _ensure_staff_exists(db, staff_profile_id)
    return availability.list_exceptions(db, staff_profile_id)


@router.post(
    "/{staff_profile_id}/availability/exceptions",
    response_model=StaffAvailabilityExceptionOut,
    status_code=201,
)
def create_exception(
    staff_profile_id: UUID,
    payload: StaffAvailabilityExceptionCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    _ensure_staff_exists(db, staff_profile_id)
    return availability.create_exception(db, staff_profile_id, payload)


@router.delete("/{staff_profile_id}/availability/exceptions/{exception_id}", status_code=204)
def delete_exception(
    staff_profile_id: UUID,
    exception_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    try:
        availability.delete_exception(db, staff_profile_id, exception_id)
    except availability.StaffAvailabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
