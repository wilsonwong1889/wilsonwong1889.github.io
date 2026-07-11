from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.models.intake import Intake
from app.services import notification_service

logger = logging.getLogger(__name__)

MEMBERSHIP_INTEREST = "membership_interest"
ENGINEER_APPLICATION = "engineer_application"
SERVICE_INQUIRY = "service_inquiry"

VALID_STATUSES = {"new", "reviewed", "archived"}
INTAKE_TYPE_LABELS = {
    MEMBERSHIP_INTEREST: "Membership interest",
    ENGINEER_APPLICATION: "Studio engineer application",
    SERVICE_INQUIRY: "Service inquiry",
}


class IntakeError(ValueError):
    """Raised for invalid intake operations (surfaced as 400 by the router)."""


def _notify_staff(intake: Intake, fields: List[tuple]) -> None:
    """Best-effort staff notification. A mail failure never blocks the save."""
    try:
        notification_service.intake_received_email(
            to_email=settings.STUDIO_ADMIN_EMAIL,
            intake_type_label=INTAKE_TYPE_LABELS.get(intake.intake_type, "Submission"),
            name=intake.name,
            email=intake.email,
            phone=intake.phone,
            fields=fields,
        )
    except Exception:  # pragma: no cover - notification must not break intake
        logger.exception("Failed to send intake notification email for %s", intake.id)


def create_membership_interest(
    db: Session,
    *,
    name: str,
    email: str,
    phone: str,
    membership_interest: str,
    message: Optional[str] = None,
) -> Intake:
    intake = Intake(
        intake_type=MEMBERSHIP_INTEREST,
        name=name.strip(),
        email=email.strip(),
        phone=phone.strip(),
        details={
            "membership_interest": membership_interest.strip(),
            "message": (message or "").strip(),
        },
        status="new",
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    _notify_staff(
        intake,
        [
            ("Membership interest", intake.details.get("membership_interest", "")),
            ("Message", intake.details.get("message", "")),
        ],
    )
    return intake


def create_service_inquiry(
    db: Session,
    *,
    name: str,
    email: str,
    phone: str,
    service_interest: str,
    message: Optional[str] = None,
) -> Intake:
    intake = Intake(
        intake_type=SERVICE_INQUIRY,
        name=name.strip(),
        email=email.strip(),
        phone=phone.strip(),
        details={
            "service_interest": service_interest.strip(),
            "message": (message or "").strip(),
        },
        status="new",
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    _notify_staff(
        intake,
        [
            ("Service interest", intake.details.get("service_interest", "")),
            ("Message", intake.details.get("message", "")),
        ],
    )
    return intake


def create_engineer_application(
    db: Session,
    *,
    name: str,
    email: str,
    phone: str,
    skillset: str,
    equipment: Optional[str] = None,
    why_considered: str = "",
) -> Intake:
    intake = Intake(
        intake_type=ENGINEER_APPLICATION,
        name=name.strip(),
        email=email.strip(),
        phone=phone.strip(),
        details={
            "skillset": skillset.strip(),
            "equipment": (equipment or "").strip(),
            "why_considered": why_considered.strip(),
        },
        status="new",
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    _notify_staff(
        intake,
        [
            ("Skillset", intake.details.get("skillset", "")),
            ("Equipment", intake.details.get("equipment", "")),
            ("Why considered", intake.details.get("why_considered", "")),
        ],
    )
    return intake


def list_intakes(
    db: Session,
    *,
    intake_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Intake]:
    query = db.query(Intake)
    if intake_type:
        query = query.filter(Intake.intake_type == intake_type)
    if status:
        query = query.filter(Intake.status == status)
    return query.order_by(Intake.created_at.desc()).all()


def update_intake_status(db: Session, intake_id: UUID, status: str) -> Intake:
    if status not in VALID_STATUSES:
        raise IntakeError(f"Invalid status '{status}'")
    intake = db.query(Intake).filter(Intake.id == intake_id).first()
    if intake is None:
        raise IntakeError("Intake not found")
    intake.status = status
    db.commit()
    db.refresh(intake)
    return intake
