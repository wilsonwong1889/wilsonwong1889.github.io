"""Booking service package.

This package is being split out of what was a single 2,100-line module. To keep
the public import surface stable during that migration, every name defined in
the legacy implementation (now ``core.py``) is re-exported here. Callers can —
and should — keep importing from ``app.services.booking_service`` unchanged
while functions are gradually moved into focused submodules
(``time_rules``, ``pricing``, ``availability``, ``lifecycle``, ``payments``,
``admin``, ``reviews``).

When a function moves into a submodule, import it here in place of the ``core``
name so this facade always reflects the full, stable API.
"""

from app.services.booking_service import core as _core

# Re-export every public AND private name from the legacy module so the package
# namespace is byte-for-byte identical to the old module's namespace. This makes
# the package swap a pure no-op for all existing importers.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

del _name, _core  # keep the package namespace clean; access core via .core
