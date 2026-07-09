import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Date, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
from app.roles import USER_ROLE_CUSTOMER

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    avatar_url = Column(String)
    phone = Column(String)
    birthday = Column(Date)
    billing_address = Column(JSONB)
    emergency_contact = Column(String)
    visible_minority = Column(String)
    city = Column(String)
    stripe_customer_id = Column(String)
    role = Column(String, nullable=False, default=USER_ROLE_CUSTOMER)
    user_category = Column(String, nullable=False, default="general_public")
    opt_in_email = Column(Boolean, default=True)
    opt_in_sms = Column(Boolean, default=False)
    # Opaque per-user token for one-click CASL email unsubscribe links.
    unsubscribe_token = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_method = Column(String, default="email")
    two_factor_code_hash = Column(String)
    two_factor_code_expires_at = Column(DateTime(timezone=True))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
