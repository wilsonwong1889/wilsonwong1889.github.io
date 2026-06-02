from __future__ import annotations

USER_ROLE_CUSTOMER = "Customer"
USER_ROLE_STAFF = "Staff"
USER_ROLE_ADMIN = "Admin"
USER_ROLE_ADMIN_MANAGER = "AdminManager"

USER_ROLES = {
    USER_ROLE_CUSTOMER,
    USER_ROLE_STAFF,
    USER_ROLE_ADMIN,
    USER_ROLE_ADMIN_MANAGER,
}
ADMIN_ROLES = {
    USER_ROLE_ADMIN,
    USER_ROLE_ADMIN_MANAGER,
}


def normalize_user_role(value: str | None, *, is_admin: bool = False) -> str:
    raw_value = (value or "").strip().replace(" ", "").replace("_", "")
    lowered = raw_value.lower()
    if lowered in {"adminmanager", "manager", "techadmin", "superadmin"}:
        return USER_ROLE_ADMIN_MANAGER
    if lowered == "admin":
        return USER_ROLE_ADMIN
    if lowered in {"staff", "engineer", "serviceengineer"}:
        return USER_ROLE_STAFF
    if lowered == "customer":
        return USER_ROLE_CUSTOMER
    return USER_ROLE_ADMIN if is_admin else USER_ROLE_CUSTOMER


def is_admin_role(role: str | None) -> bool:
    return normalize_user_role(role) in ADMIN_ROLES


def is_admin_manager_role(role: str | None) -> bool:
    return normalize_user_role(role) == USER_ROLE_ADMIN_MANAGER


def is_staff_role(role: str | None) -> bool:
    return normalize_user_role(role) == USER_ROLE_STAFF


def user_has_admin_access(user) -> bool:
    return bool(getattr(user, "is_admin", False)) or is_admin_role(getattr(user, "role", None))


def user_has_admin_manager_access(user) -> bool:
    return is_admin_manager_role(getattr(user, "role", None))


def user_has_staff_access(user) -> bool:
    """Staff portal access: explicit Staff role, or any admin."""
    return is_staff_role(getattr(user, "role", None)) or user_has_admin_access(user)
