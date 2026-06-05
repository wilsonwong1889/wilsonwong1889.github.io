from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.promo_code import PromoCode
from app.models.room import Room
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.roles import USER_ROLE_ADMIN_MANAGER, is_admin_role, normalize_user_role
from app.schemas.promo_code import normalize_promo_code


DEFAULT_ROOM_SEEDS: tuple[dict, ...] = (
    # --- Live for May beta launch ---
    {
        "name": "Podcast Studio",
        "description": (
            "A professional podcast-ready space with acoustic treatment, condenser mics, "
            "headphone monitoring, and a broadcast-quality setup — perfect for solo shows, "
            "interviews, and multi-guest recordings."
        ),
        "capacity": 4,
        "hourly_rate_cents": 5000,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": True,
        "coming_soon": False,
    },
    {
        "name": "Sound Engineering / Recording Studio",
        "description": (
            "A full-featured recording studio with an isolation booth, professional DAW workstation, "
            "studio monitors, and a curated mic locker — ideal for music production, voiceover, "
            "and audio post-production."
        ),
        "capacity": 6,
        "hourly_rate_cents": 5000,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": True,
        "coming_soon": False,
    },
    # --- Coming soon (target June) ---
    {
        "name": "Small Photography / Video / Editing Studio",
        "description": (
            "A compact, versatile studio space for headshots, product photography, short-form video, "
            "and on-site editing — equipped with continuous lighting and a seamless backdrop."
        ),
        "capacity": 4,
        "hourly_rate_cents": 5000,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": True,
    },
    {
        "name": "Large Photography / Videography Studio",
        "description": (
            "A spacious, high-ceiling studio built for full productions — fashion shoots, "
            "brand campaigns, and video content — with strobe lighting, modifiers, and ample room "
            "for crew and talent."
        ),
        "capacity": 12,
        "hourly_rate_cents": 7500,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": True,
    },
    {
        "name": "Dance / Movement Studio",
        "description": (
            "A sprung-floor movement studio with mirrored walls, ballet barres, and open space "
            "for choreography, rehearsal, fitness classes, and performance capture."
        ),
        "capacity": 20,
        "hourly_rate_cents": 5000,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": True,
    },
    # --- Hidden (TBC, not yet public) ---
    {
        "name": "Branding & Merchandise Production Area",
        "description": (
            "A dedicated production workspace for print-on-demand, merchandise fulfilment, "
            "and brand prototyping — featuring heat press, vinyl cutter, and design workstations."
        ),
        "capacity": 6,
        "hourly_rate_cents": 5000,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": False,
    },
    {
        "name": "Conference Room",
        "description": (
            "A professional meeting room with presentation display, whiteboard, and seating for "
            "up to 12 — suited for workshops, strategy sessions, and community meetings."
        ),
        "capacity": 12,
        "hourly_rate_cents": 3500,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": False,
    },
    {
        "name": "Co-Working Space",
        "description": (
            "An open, collaborative workspace with high-speed Wi-Fi, standing desks, and a "
            "community atmosphere — available for day passes and hourly drop-in sessions."
        ),
        "capacity": 16,
        "hourly_rate_cents": 2500,
        "max_booking_duration_minutes": 300,
        "photos": [],
        "staff_roles": [],
        "active": False,
        "coming_soon": False,
    },
)

DEFAULT_STAFF_PROFILE_SEEDS: tuple[dict, ...] = (
    {
        "name": "Wilson Wong",
        "description": "Podcast producer and audio storyteller helping creators build consistent, professional shows from concept to final episode.",
        "skills": ["Podcast Production", "Audio Editing", "Show Development"],
        "talents": ["Guest Coaching", "RSS & Distribution", "Sound Design"],
        "service_types": ["Podcast Producer"],
        "booking_rate_cents": 6500,
        "add_on_price_cents": 2000,
        "equipment_rental_cost_cents": 1000,
        "photo_url": "/assets/media/staff/0619eb1aecb74f4d876502e7b35cf5ae.jpg",
        "role_title": "Photography",
        "booking_enabled": True,
        "schedule_published": True,
        "active": True,
    },
)

LEGACY_DEMO_STAFF_PROFILE_NAMES = frozenset(
    {
        "Jordan Lee",
        "Priya Sharma",
        "Marcus Webb",
        "Amara Osei",
        "Tasha Rivera",
        "Devon Clarke",
    }
)

DEFAULT_PROMO_CODE_SEEDS: tuple[dict, ...] = (
    {
        "code": "SUMMER60",
        "description": "Limited time opening discount for public bookings",
        "percent_off": 60,
        "amount_off_cents": None,
        "active": True,
        "max_redemptions": None,
    },
)


def ensure_admin_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str = "BIPOC Foundation Admin",
    phone: str | None = None,
    role: str = USER_ROLE_ADMIN_MANAGER,
    rotate_password: bool = True,
) -> User:
    normalized_phone = phone.strip() if phone else None
    normalized_role = normalize_user_role(role, is_admin=True)
    admin = db.query(User).filter(User.email == email).first()
    if admin:
        if password and rotate_password:
            admin.password_hash = hash_password(password)
        admin.is_admin = is_admin_role(normalized_role)
        admin.role = normalized_role
        if full_name:
            admin.full_name = full_name
        if normalized_phone:
            admin.phone = normalized_phone
        db.commit()
        db.refresh(admin)
        return admin

    admin = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        phone=normalized_phone,
        role=normalized_role,
        is_admin=is_admin_role(normalized_role),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def ensure_rooms(db: Session, rooms: Sequence[dict] = DEFAULT_ROOM_SEEDS) -> list[Room]:
    created_rooms: list[Room] = []
    for room_payload in rooms:
        existing_room = db.query(Room).filter(Room.name == room_payload["name"]).first()
        if existing_room:
            updated = False
            for field in ("description", "capacity", "hourly_rate_cents"):
                if getattr(existing_room, field) in (None, ""):
                    setattr(existing_room, field, room_payload[field])
                    updated = True
            if not existing_room.photos:
                existing_room.photos = room_payload["photos"]
                updated = True
            # Always sync visibility flags from seed data
            for field in ("active", "coming_soon"):
                if field in room_payload and getattr(existing_room, field) != room_payload[field]:
                    setattr(existing_room, field, room_payload[field])
                    updated = True
            if updated:
                db.add(existing_room)
            continue
        room = Room(**room_payload)
        db.add(room)
        created_rooms.append(room)

    if created_rooms:
        db.commit()
        for room in created_rooms:
            db.refresh(room)
    else:
        db.commit()

    return created_rooms


def deactivate_legacy_demo_staff_profiles(db: Session) -> int:
    legacy_names = {name.lower() for name in LEGACY_DEMO_STAFF_PROFILE_NAMES}
    updated = 0
    for profile in db.query(StaffProfile).all():
        if profile.name.strip().lower() in legacy_names and profile.active:
            profile.active = False
            db.add(profile)
            updated += 1
    if updated:
        db.commit()
    return updated


def ensure_staff_profiles(db: Session, profiles: Sequence[dict] = DEFAULT_STAFF_PROFILE_SEEDS) -> list[StaffProfile]:
    deactivate_legacy_demo_staff_profiles(db)
    created_profiles: list[StaffProfile] = []
    existing_by_name = {profile.name.lower(): profile for profile in db.query(StaffProfile).all()}
    for payload in profiles:
        lookup_key = payload["name"].strip().lower()
        existing = existing_by_name.get(lookup_key)
        if existing:
            updated = False
            if not existing.description and payload.get("description"):
                existing.description = payload["description"]
                updated = True
            if not existing.skills and payload.get("skills"):
                existing.skills = payload["skills"]
                updated = True
            if not existing.talents and payload.get("talents"):
                existing.talents = payload["talents"]
                updated = True
            if not existing.service_types and payload.get("service_types"):
                existing.service_types = payload["service_types"]
                updated = True
            if not existing.services and payload.get("services"):
                existing.services = payload["services"]
                updated = True
            if not existing.photo_url and payload.get("photo_url"):
                existing.photo_url = payload["photo_url"]
                updated = True
            if not existing.role_title and payload.get("role_title"):
                existing.role_title = payload["role_title"]
                updated = True
            if not existing.bio and payload.get("bio"):
                existing.bio = payload["bio"]
                updated = True
            if not existing.portfolio_url and payload.get("portfolio_url"):
                existing.portfolio_url = payload["portfolio_url"]
                updated = True
            if not existing.add_on_price_cents and payload.get("add_on_price_cents"):
                existing.add_on_price_cents = payload["add_on_price_cents"]
                updated = True
            if not existing.booking_rate_cents and payload.get("booking_rate_cents"):
                existing.booking_rate_cents = payload["booking_rate_cents"]
                updated = True
            if not existing.equipment_rental_cost_cents and payload.get("equipment_rental_cost_cents"):
                existing.equipment_rental_cost_cents = payload["equipment_rental_cost_cents"]
                updated = True
            for field in ("active", "booking_enabled", "schedule_published"):
                if field in payload and getattr(existing, field) != payload[field]:
                    setattr(existing, field, payload[field])
                    updated = True
            if updated:
                db.add(existing)
            continue

        profile = StaffProfile(**payload)
        db.add(profile)
        created_profiles.append(profile)

    db.commit()
    for profile in created_profiles:
        db.refresh(profile)
    return created_profiles


def ensure_promo_codes(db: Session, promo_codes: Sequence[dict] = DEFAULT_PROMO_CODE_SEEDS) -> list[PromoCode]:
    created_promo_codes: list[PromoCode] = []
    for payload in promo_codes:
        code = normalize_promo_code(payload["code"])
        existing = db.query(PromoCode).filter(PromoCode.code == code).first()
        if existing:
            updated = False
            for field in (
                "description",
                "percent_off",
                "amount_off_cents",
                "active",
                "max_redemptions",
                "starts_at",
                "expires_at",
            ):
                if field in payload and getattr(existing, field) != payload[field]:
                    setattr(existing, field, payload[field])
                    updated = True
            if updated:
                db.add(existing)
            continue

        promo_code = PromoCode(**{**payload, "code": code})
        db.add(promo_code)
        created_promo_codes.append(promo_code)

    db.commit()
    for promo_code in created_promo_codes:
        db.refresh(promo_code)
    return created_promo_codes
