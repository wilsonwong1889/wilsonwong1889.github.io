from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.membership import UserMembership
from app.models.user import User
from app.roles import USER_ROLE_ADMIN, USER_ROLE_ADMIN_MANAGER, is_admin_manager_role, normalize_user_role


# Membership categories an admin can assign, most-common first.
MEMBERSHIP_CATEGORIES = (
    "general_public",
    "artist_member",
    "fellowship_artist",
    "artist_in_residence",
    "service_engineer",
    "bipoc_community_member",
    "venture_member",
    "organizational_member",
)


def get_membership_category(db: Session, user_id) -> Optional[str]:
    membership = (
        db.query(UserMembership)
        .filter(UserMembership.user_id == user_id)
        .order_by(UserMembership.created_at.desc())
        .first()
    )
    return membership.category if membership else None


def set_user_membership(db: Session, user: User, category: str) -> str:
    if category not in MEMBERSHIP_CATEGORIES:
        raise ValueError("Unknown membership category")
    membership = (
        db.query(UserMembership)
        .filter(UserMembership.user_id == user.id)
        .order_by(UserMembership.created_at.desc())
        .first()
    )
    if membership:
        membership.category = category
    else:
        membership = UserMembership(user_id=user.id, category=category)
        db.add(membership)
    db.flush()
    return category


def list_accounts_for_admin(db: Session) -> list[dict]:
    booking_stats_rows = (
        db.query(
            Booking.user_id,
            func.count(Booking.id),
            func.max(Booking.start_time),
        )
        .filter(Booking.user_id.isnot(None))
        .group_by(Booking.user_id)
        .all()
    )
    booking_stats_by_user_id = {
        str(user_id): {
            "booking_count": booking_count,
            "last_booking_at": last_booking_at,
        }
        for user_id, booking_count, last_booking_at in booking_stats_rows
        if user_id is not None
    }

    users = (
        db.query(User)
        .order_by(User.is_admin.desc(), User.created_at.desc(), User.email.asc())
        .all()
    )

    # Latest membership category per user, in one pass.
    membership_by_user_id: dict[str, str] = {}
    for membership in (
        db.query(UserMembership)
        .filter(UserMembership.user_id.isnot(None))
        .order_by(UserMembership.created_at.desc())
        .all()
    ):
        membership_by_user_id.setdefault(str(membership.user_id), membership.category)

    return sorted(
        [
            serialize_admin_account(
                user,
                booking_stats_by_user_id.get(str(user.id)),
                membership_category=membership_by_user_id.get(str(user.id)),
            )
            for user in users
        ],
        key=lambda account: (
            0 if account["role"] == "AdminManager" else 1 if account["is_admin"] else 2,
            account["created_at"],
            account["email"],
        ),
    )


def serialize_admin_account(
    user: User, booking_stats: Optional[dict] = None, membership_category: Optional[str] = None
) -> dict:
    stats = booking_stats or {}
    role = normalize_user_role(getattr(user, "role", None), is_admin=user.is_admin)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "phone": user.phone,
        "birthday": user.birthday,
        "billing_address": user.billing_address,
        "opt_in_email": user.opt_in_email,
        "opt_in_sms": user.opt_in_sms,
        "is_admin": user.is_admin,
        "role": role,
        "membership_category": membership_category,
        "booking_count": stats.get("booking_count", 0) or 0,
        "last_booking_at": stats.get("last_booking_at"),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def can_delete_admin_account(db: Session, user: User) -> bool:
    if not user.is_admin:
        return True
    remaining_admins = (
        db.query(User)
        .filter(User.is_admin.is_(True), User.id != user.id)
        .count()
    )
    if remaining_admins <= 0:
        return False
    if not is_admin_manager_role(getattr(user, "role", None)):
        return True
    remaining_managers = (
        db.query(User)
        .filter(User.role == "AdminManager", User.id != user.id)
        .count()
    )
    return remaining_managers > 0


def count_admin_managers(db: Session, *, exclude_user_id=None) -> int:
    query = db.query(User).filter(User.role == "AdminManager")
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def apply_user_role(user: User, role: str) -> str:
    normalized_role = normalize_user_role(role, is_admin=user.is_admin)
    user.role = normalized_role
    user.is_admin = normalized_role in {USER_ROLE_ADMIN, USER_ROLE_ADMIN_MANAGER}
    return normalized_role


def delete_user_account(db: Session, user: User) -> None:
    db.delete(user)
    db.flush()
