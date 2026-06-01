import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class Intake(Base):
    """A public lead/application submission.

    One table backs every public intake form. ``intake_type`` discriminates
    between them and the type-specific answers live in ``details`` so the
    table stays narrow as new form types are added.
    """

    __tablename__ = "intakes"

    # Recognised intake types:
    #   membership_interest  — someone interested in a membership (Pricing form)
    #   engineer_application — someone applying to work as a studio engineer
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intake_type = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    details = Column(JSONB, nullable=False, default=dict)
    # Review workflow state: new | reviewed | archived
    status = Column(String, nullable=False, default="new", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
