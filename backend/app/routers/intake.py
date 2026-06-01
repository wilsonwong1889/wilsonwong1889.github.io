from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.user import User
from app.schemas.intake import (
    EngineerApplicationCreate,
    IntakeOut,
    IntakeStatusUpdate,
    MembershipInterestCreate,
)
from app.services.intake_service import (
    IntakeError,
    create_engineer_application,
    create_membership_interest,
    list_intakes,
    update_intake_status,
)

router = APIRouter(prefix="/api", tags=["Intake"])

intake_rate_limit = rate_limit_dependency("intake", settings.AUTH_RATE_LIMIT_MAX_REQUESTS)


# ── Public intake forms ─────────────────────────────────────────────────────

@router.post(
    "/intake/membership-interest",
    response_model=IntakeOut,
    status_code=201,
    dependencies=[Depends(intake_rate_limit)],
)
def submit_membership_interest(
    payload: MembershipInterestCreate,
    db: Session = Depends(get_db),
):
    return create_membership_interest(db, **payload.model_dump())


@router.post(
    "/intake/engineer-application",
    response_model=IntakeOut,
    status_code=201,
    dependencies=[Depends(intake_rate_limit)],
)
def submit_engineer_application(
    payload: EngineerApplicationCreate,
    db: Session = Depends(get_db),
):
    return create_engineer_application(db, **payload.model_dump())


# ── Admin review ─────────────────────────────────────────────────────────────

@router.get("/admin/intakes", response_model=List[IntakeOut])
def admin_list_intakes(
    intake_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    return list_intakes(db, intake_type=intake_type, status=status)


@router.patch("/admin/intakes/{intake_id}", response_model=IntakeOut)
def admin_update_intake(
    intake_id: UUID,
    payload: IntakeStatusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    try:
        return update_intake_status(db, intake_id, payload.status)
    except IntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
