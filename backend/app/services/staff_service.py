from __future__ import annotations

from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.room import Room
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.roles import USER_ROLE_STAFF, user_has_admin_access
from app.schemas.staff import StaffProfileCreate, StaffProfileUpdate
from app.staffing import build_staff_snapshot, normalize_staff_roles, normalize_string_list

STAFF_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media" / "staff"


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _link_staff_account(db: Session, profile: StaffProfile, email: str | None) -> None:
    """Link a login account to the staff profile by email and grant the Staff
    role (without demoting an existing admin). Empty email is a no-op."""
    cleaned = (email or "").strip()
    if not cleaned:
        return
    user = db.query(User).filter(func.lower(User.email) == cleaned.lower()).first()
    if not user:
        raise ValueError(f"No account found for {cleaned}")
    profile.user_id = user.id
    if not user_has_admin_access(user):
        user.role = USER_ROLE_STAFF


def _normalize_profile_name(value: str | None) -> str:
    name = (value or "").strip()
    if len(name) < 2:
        raise ValueError("Staff profile name must be at least 2 characters")
    return name


def _ensure_unique_name(db: Session, name: str, exclude_profile_id=None) -> None:
    query = db.query(StaffProfile).filter(func.lower(StaffProfile.name) == name.lower())
    if exclude_profile_id:
        query = query.filter(StaffProfile.id != exclude_profile_id)
    if query.first():
        raise ValueError("A staff profile with that name already exists")


def _remove_staff_from_rooms(db: Session, profile_id: str) -> None:
    for room in db.query(Room).all():
        room_staff = normalize_staff_roles(room.staff_roles)
        updated_staff = [staff_member for staff_member in room_staff if staff_member["id"] != profile_id]
        if len(updated_staff) != len(room_staff):
            room.staff_roles = updated_staff


def _sync_staff_snapshot_to_rooms(db: Session, profile: StaffProfile) -> None:
    snapshot = build_staff_snapshot(profile)
    for room in db.query(Room).all():
        room_staff = normalize_staff_roles(room.staff_roles)
        replaced = False
        updated_staff = []
        for staff_member in room_staff:
            if staff_member["id"] == snapshot["id"]:
                if profile.active:
                    updated_staff.append(snapshot)
                replaced = True
            else:
                updated_staff.append(staff_member)
        if replaced:
            room.staff_roles = updated_staff


def _delete_photo_if_unused(db: Session, photo_url: str | None, exclude_profile_id=None) -> None:
    if not photo_url or not photo_url.startswith("/assets/media/staff/"):
        return

    query = db.query(StaffProfile).filter(StaffProfile.photo_url == photo_url)
    if exclude_profile_id:
        query = query.filter(StaffProfile.id != exclude_profile_id)
    if query.first():
        return

    photo_path = STAFF_MEDIA_DIR / photo_url.rsplit("/", 1)[-1]
    if photo_path.exists():
        photo_path.unlink()


def list_staff_profiles(db: Session) -> list[StaffProfile]:
    return db.query(StaffProfile).order_by(StaffProfile.active.desc(), StaffProfile.name.asc()).all()


def create_staff_profile(db: Session, payload: StaffProfileCreate) -> StaffProfile:
    name = _normalize_profile_name(payload.name)
    _ensure_unique_name(db, name)
    profile = StaffProfile(
        name=name,
        description=payload.description.strip() if payload.description else None,
        bio=payload.bio.strip() if payload.bio else None,
        skills=normalize_string_list(payload.skills),
        talents=normalize_string_list(payload.talents),
        services=normalize_string_list(payload.services),
        photo_url=payload.photo_url,
        headshot_urls=normalize_string_list(payload.headshot_urls),
        portfolio_url=payload.portfolio_url.strip() if payload.portfolio_url else None,
        add_on_price_cents=payload.add_on_price_cents,
        booking_rate_cents=payload.booking_rate_cents,
        equipment_rental_cost_cents=payload.equipment_rental_cost_cents,
        service_types=normalize_string_list(payload.service_types),
        role_title=_clean(payload.role_title),
        notification_email=_clean(payload.notification_email),
        notification_phone=_clean(payload.notification_phone),
        notify_by_email=payload.notify_by_email,
        notify_by_sms=payload.notify_by_sms,
        booking_requires_approval=payload.booking_requires_approval,
        booking_enabled=payload.booking_enabled,
        active=payload.active,
    )
    _link_staff_account(db, profile, payload.linked_user_email)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_staff_profile(db: Session, profile_id: str, payload: StaffProfileUpdate) -> StaffProfile:
    profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
    if not profile:
        raise ValueError("Staff profile not found")

    update_data = payload.model_dump(exclude_unset=True)
    previous_photo_url = profile.photo_url
    if "name" in update_data and update_data["name"] is not None:
        profile.name = _normalize_profile_name(update_data["name"])
        _ensure_unique_name(db, profile.name, exclude_profile_id=profile.id)
    if "description" in update_data:
        profile.description = update_data["description"].strip() if update_data["description"] else None
    if "bio" in update_data:
        profile.bio = update_data["bio"].strip() if update_data["bio"] else None
    if "skills" in update_data and update_data["skills"] is not None:
        profile.skills = normalize_string_list(update_data["skills"])
    if "talents" in update_data and update_data["talents"] is not None:
        profile.talents = normalize_string_list(update_data["talents"])
    if "services" in update_data and update_data["services"] is not None:
        profile.services = normalize_string_list(update_data["services"])
    if "photo_url" in update_data:
        profile.photo_url = update_data["photo_url"]
    if "headshot_urls" in update_data and update_data["headshot_urls"] is not None:
        profile.headshot_urls = normalize_string_list(update_data["headshot_urls"])
    if "portfolio_url" in update_data:
        profile.portfolio_url = update_data["portfolio_url"].strip() if update_data["portfolio_url"] else None
    if "add_on_price_cents" in update_data and update_data["add_on_price_cents"] is not None:
        profile.add_on_price_cents = update_data["add_on_price_cents"]
    if "booking_rate_cents" in update_data and update_data["booking_rate_cents"] is not None:
        profile.booking_rate_cents = update_data["booking_rate_cents"]
    if "equipment_rental_cost_cents" in update_data and update_data["equipment_rental_cost_cents"] is not None:
        profile.equipment_rental_cost_cents = update_data["equipment_rental_cost_cents"]
    if "service_types" in update_data and update_data["service_types"] is not None:
        profile.service_types = normalize_string_list(update_data["service_types"])
    if "role_title" in update_data:
        profile.role_title = _clean(update_data["role_title"])
    if "notification_email" in update_data:
        profile.notification_email = _clean(update_data["notification_email"])
    if "notification_phone" in update_data:
        profile.notification_phone = _clean(update_data["notification_phone"])
    if "notify_by_email" in update_data and update_data["notify_by_email"] is not None:
        profile.notify_by_email = update_data["notify_by_email"]
    if "notify_by_sms" in update_data and update_data["notify_by_sms"] is not None:
        profile.notify_by_sms = update_data["notify_by_sms"]
    if "booking_requires_approval" in update_data and update_data["booking_requires_approval"] is not None:
        profile.booking_requires_approval = update_data["booking_requires_approval"]
    if "linked_user_email" in update_data:
        _link_staff_account(db, profile, update_data["linked_user_email"])
    if "booking_enabled" in update_data and update_data["booking_enabled"] is not None:
        profile.booking_enabled = update_data["booking_enabled"]
    if "active" in update_data and update_data["active"] is not None:
        profile.active = update_data["active"]

    _sync_staff_snapshot_to_rooms(db, profile)
    db.commit()
    db.refresh(profile)
    if previous_photo_url != profile.photo_url:
        _delete_photo_if_unused(db, previous_photo_url, exclude_profile_id=profile.id)
    return profile


def delete_staff_profile(db: Session, profile_id: str) -> None:
    profile = db.query(StaffProfile).filter(StaffProfile.id == profile_id).first()
    if not profile:
        raise ValueError("Staff profile not found")

    photo_url = profile.photo_url
    _remove_staff_from_rooms(db, str(profile.id))
    db.delete(profile)
    db.commit()
    _delete_photo_if_unused(db, photo_url)
