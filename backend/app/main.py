from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.config import (
    get_stripe_configuration_status,
    get_supabase_configuration_status,
    settings,
    validate_runtime_configuration,
)
from app.database import engine
from app.routers import (
    admin,
    auth,
    bookings,
    intake,
    rooms,
    staff,
    staff_application,
    staff_availability,
    staff_bookings,
    staff_portal,
    users,
    webhooks,
)
from app.monitoring import record_request, render_metrics, time_request
from sqlalchemy import text

try:
    import redis
except ImportError:  # pragma: no cover - runtime dependency
    redis = None


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
FRONTEND_PAGES = {
    "/": "index.html",
    "/account": "account.html",
    "/contact": "contact.html",
    "/faq": "faq.html",
    "/info": "info.html",
    "/pricing": "pricing.html",
    "/services": "services.html",
    "/rooms": "rooms.html",
    "/room": "room.html",
    "/reserve": "reserve.html",
    "/staff": "staff.html",
    "/staff-dashboard": "staff-dashboard.html",
    "/bookings": "bookings.html",
    "/booking": "booking.html",
    "/payment-success": "payment-success.html",
    "/admin": "admin.html",
    "/programming": "programming.html",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_configuration()
    yield


app = FastAPI(
    title="BIPOC Creative Innovation Studio",
    version="0.1.0",
    description="Room booking platform for studios",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress text responses (HTML/CSS/JS/JSON). app.css alone is ~250 KB and
# drops to ~40 KB gzipped — a big cut to egress bandwidth on every request.
app.add_middleware(GZipMiddleware, minimum_size=600)


@app.middleware("http")
async def request_metrics_middleware(request, call_next):
    started_at = time_request()
    response = await call_next(request)
    record_request(time_request() - started_at)
    return response

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(staff.router)
app.include_router(bookings.router)
app.include_router(staff_bookings.router)
app.include_router(intake.router)
app.include_router(staff_availability.router)
app.include_router(staff_portal.router)
app.include_router(staff_application.router)
app.include_router(admin.router)
app.include_router(webhooks.router)

# Long-lived media (images/fonts/video/pdf) rarely change and aren't versioned;
# cache them hard so repeat visits don't re-download. Code (css/js) is cached
# briefly so a browsing session reuses one copy while staying fresh; bump the
# ?v= query string in the HTML when shipping a css/js change for instant busting.
# Everything still carries ETag/Last-Modified, so post-expiry requests revalidate
# to a tiny 304 instead of re-sending the body.
_MEDIA_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp4", ".mov", ".webm", ".pdf", ".heic",
)
_CODE_SUFFIXES = (".css", ".js", ".mjs")
_WEBP_SOURCE_SUFFIXES = (".jpg", ".jpeg", ".png")


class CachingStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        lowered = path.lower()
        serve_path = path
        served_webp = False
        # Transparent WebP: if the browser accepts webp and a "<file>.webp" twin
        # exists, serve that instead — same URL, ~60% fewer bytes. The original
        # JPEG/PNG stays the fallback for clients that don't send image/webp.
        if lowered.endswith(_WEBP_SOURCE_SUFFIXES):
            accept = b""
            for key, value in scope.get("headers", []):
                if key == b"accept":
                    accept = value
                    break
            if b"image/webp" in accept and (Path(self.directory) / f"{path}.webp").is_file():
                serve_path = f"{path}.webp"
                served_webp = True

        response = await super().get_response(serve_path, scope)

        if lowered.endswith(_MEDIA_SUFFIXES):
            response.headers["Cache-Control"] = "public, max-age=2592000"
        elif lowered.endswith(_CODE_SUFFIXES):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "public, max-age=300"

        if served_webp:
            response.headers["Content-Type"] = "image/webp"
            # Shared caches must key on Accept so non-webp clients still get JPEG.
            response.headers["Vary"] = "Accept"
        return response


if FRONTEND_DIR.exists():
    app.mount("/assets", CachingStaticFiles(directory=FRONTEND_DIR), name="frontend-assets")

    def build_frontend_handler(filename: str):
        def handler():
            # HTML must revalidate so updated ?v= asset references are picked up;
            # ETag means unchanged pages come back as a tiny 304, not a re-send.
            return FileResponse(
                FRONTEND_DIR / filename,
                headers={"Cache-Control": "no-cache"},
            )

        return handler

    for route_path, filename in FRONTEND_PAGES.items():
        app.add_api_route(route_path, build_frontend_handler(filename), methods=["GET"], include_in_schema=False)

    # Browsers and crawlers auto-request these at the site root; without routes
    # they 404 on every visit. Serve the brand icons with a long cache.
    _ICON_ROUTES = {
        "/favicon.ico": ("media/favicon.ico", "image/x-icon"),
        "/apple-touch-icon.png": ("media/apple-touch-icon.png", "image/png"),
        "/apple-touch-icon-precomposed.png": ("media/apple-touch-icon.png", "image/png"),
    }

    def build_icon_handler(rel_path: str, media_type: str):
        def handler():
            return FileResponse(
                FRONTEND_DIR / rel_path,
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=2592000"},
            )

        return handler

    for route_path, (rel_path, media_type) in _ICON_ROUTES.items():
        app.add_api_route(route_path, build_icon_handler(rel_path, media_type), methods=["GET"], include_in_schema=False)


WELL_KNOWN_DIR = Path(__file__).resolve().parent / "well_known"


# Stripe fetches this file to verify the domain for Apple Pay (payment method
# domains). Re-register domains with Stripe after switching to live keys.
@app.get("/.well-known/apple-developer-merchantid-domain-association", include_in_schema=False)
def apple_pay_domain_association():
    return FileResponse(
        WELL_KNOWN_DIR / "apple-developer-merchantid-domain-association",
        media_type="application/octet-stream",
    )


@app.get("/metrics", include_in_schema=False)
def metrics():
    return PlainTextResponse(render_metrics())


@app.get("/api/public/config", include_in_schema=False)
def public_config(response: Response):
    # Rarely changes; let the browser/CDN reuse it across page navigations
    # instead of re-fetching on every load.
    response.headers["Cache-Control"] = "public, max-age=300"
    stripe_status = get_stripe_configuration_status()
    supabase_status = get_supabase_configuration_status()
    return {
        "app_env": settings.APP_ENV,
        "payment_backend": settings.PAYMENT_BACKEND,
        "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY if stripe_status["stripe_checkout_ready"] else None,
        "stripe_checkout_ready": stripe_status["stripe_checkout_ready"],
        "stripe_webhooks_ready": stripe_status["stripe_webhooks_ready"],
        "stripe_fully_ready": stripe_status["stripe_fully_ready"],
        "supabase_url": settings.SUPABASE_URL if supabase_status["supabase_fully_ready"] else None,
        "supabase_publishable_key": (
            settings.SUPABASE_PUBLISHABLE_KEY if supabase_status["supabase_fully_ready"] else None
        ),
        "supabase_fully_ready": supabase_status["supabase_fully_ready"],
        "app_base_url": settings.APP_BASE_URL,
        "default_currency": settings.DEFAULT_CURRENCY,
        "staff_room_addon_hourly_cents": settings.STAFF_ROOM_ADDON_HOURLY_CENTS,
    }


@app.get("/api/public/features", include_in_schema=False)
def public_features(response: Response):
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "opening_discount": settings.FEATURE_OPENING_DISCOUNT,
        "venture_tiers": settings.FEATURE_VENTURE_TIERS,
        "monthly_packages": settings.FEATURE_MONTHLY_PACKAGES,
        "day_rates": settings.FEATURE_DAY_RATES,
        "equipment_rental": settings.FEATURE_EQUIPMENT_RENTAL,
        "special_projects": settings.FEATURE_SPECIAL_PROJECTS,
        "engineer_profiles": settings.FEATURE_ENGINEER_PROFILES,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "BIPOC Creative Innovation Studio"}


@app.get("/ready", include_in_schema=False)
def ready():
    checks = {"database": False, "redis": False}

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    checks["database"] = True

    if redis is not None:
        redis.Redis.from_url(settings.REDIS_URL, decode_responses=True).ping()
        checks["redis"] = True

    stripe_status = get_stripe_configuration_status()
    checks["stripe"] = True if not stripe_status["stripe_requested"] else stripe_status["stripe_fully_ready"]

    status = "ready" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}
