import os
import secrets
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.config import (
    get_payment_backend,
    get_paypal_configuration_status,
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
    notifications,
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
    "/staff-respond": "staff-respond.html",
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
app.include_router(notifications.router)
app.include_router(staff_availability.router)
app.include_router(staff_portal.router)
app.include_router(staff_application.router)
app.include_router(admin.router)
app.include_router(webhooks.router)

# Long-lived media (images/fonts/video/pdf) rarely change and aren't versioned;
# cache them hard so repeat visits don't re-download. Code (css/js) must
# revalidate on every load: the HTML's ?v= only busts main.js, and its ES-module
# imports (views/*.js) carry no version, so a max-age here would serve stale
# modules until it expired. "no-cache" keeps the file cached but forces an
# ETag revalidation each load — unchanged files come back as a tiny 304, changed
# files (e.g. after a deploy) are picked up immediately.
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
            response.headers["Cache-Control"] = "no-cache"
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

    # HEAD as well as GET: uptime monitors probe with HEAD by default, and
    # FastAPI's APIRoute — unlike Starlette's plain Route — does not add it
    # alongside GET on its own. Without it every monitor check reads as 405.
    for route_path, filename in FRONTEND_PAGES.items():
        app.add_api_route(
            route_path,
            build_frontend_handler(filename),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )

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
        app.add_api_route(
            route_path,
            build_icon_handler(rel_path, media_type),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )

WELL_KNOWN_DIR = Path(__file__).resolve().parent / "well_known"


# Apple Pay domain verification requires this standard well-known file.
@app.get("/.well-known/apple-developer-merchantid-domain-association", include_in_schema=False)
def apple_pay_domain_association():
    return FileResponse(
        WELL_KNOWN_DIR / "apple-developer-merchantid-domain-association",
        media_type="application/octet-stream",
    )


# Crawlers request this on every visit. Keep the booking flow and the
# signed-in areas out of search results; the marketing pages are fair game.
ROBOTS_TXT = """User-agent: *
Disallow: /account
Disallow: /admin
Disallow: /booking
Disallow: /bookings
Disallow: /payment-success
Disallow: /reserve
Disallow: /staff-dashboard
Disallow: /staff-respond
Disallow: /api/
"""

# The marketing pages worth indexing. /room is deliberately absent: without a
# room id it is an empty shell, so it carries its own meta tags for link
# previews but is not a destination we ask search engines to crawl.
SITEMAP_PATHS = (
    "/",
    "/rooms",
    "/pricing",
    "/services",
    "/staff",
    "/programming",
    "/info",
    "/faq",
    "/contact",
)


def _site_base_url() -> str:
    return (settings.APP_BASE_URL or "").rstrip("/")


@app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
def robots_txt():
    # Point crawlers at the sitemap so they do not have to guess the URL set.
    body = f"{ROBOTS_TXT}\nSitemap: {_site_base_url()}/sitemap.xml\n"
    return PlainTextResponse(
        body,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Google Search Console proves domain ownership by fetching this exact file
# from the site root. The token is not a secret — it only asserts that whoever
# controls this domain also controls that Search Console property — so it lives
# in the source rather than the environment. Served inline for the same reason
# robots.txt is: one line of content is not worth a file to misplace.
GOOGLE_SITE_VERIFICATION_FILENAME = "google80489ce95ca215bd.html"
GOOGLE_SITE_VERIFICATION_BODY = "google-site-verification: google80489ce95ca215bd.html"


@app.api_route(
    f"/{GOOGLE_SITE_VERIFICATION_FILENAME}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def google_site_verification():
    return Response(
        content=GOOGLE_SITE_VERIFICATION_BODY,
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def sitemap_xml():
    """The public page list, for search engines.

    No <lastmod>: the HTML ships inside the image, so its mtime is the build
    time and would claim every page changed on every deploy. Google ignores a
    lastmod it cannot trust, so an honest omission beats a misleading date."""
    base = _site_base_url()
    urls = "".join(f"  <url><loc>{base}{path}</loc></url>\n" for path in SITEMAP_PATHS)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.api_route("/metrics", methods=["GET", "HEAD"], include_in_schema=False)
def metrics(authorization: str = Header(default="")):
    """Operational counters, behind a shared secret.

    These describe traffic and booking volume, which is nobody else's business,
    so the endpoint is off unless METRICS_TOKEN is configured. A scraper sends
    it as a bearer token."""
    expected = (settings.METRICS_TOKEN or "").strip()
    if not expected:
        # Not enabled — look no different from a route that does not exist.
        raise HTTPException(status_code=404, detail="Not Found")

    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(presented.strip(), expected):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return PlainTextResponse(render_metrics())


@app.get("/api/public/config", include_in_schema=False)
def public_config(response: Response):
    # Rarely changes; let the browser/CDN reuse it across page navigations
    # instead of re-fetching on every load.
    response.headers["Cache-Control"] = "public, max-age=300"
    paypal_status = get_paypal_configuration_status()
    supabase_status = get_supabase_configuration_status()
    return {
        "app_env": settings.APP_ENV,
        "payment_backend": get_payment_backend(settings),
        "paypal_client_id": settings.PAYPAL_CLIENT_ID if paypal_status["paypal_checkout_ready"] else None,
        "paypal_env": settings.PAYPAL_ENV,
        "paypal_checkout_ready": paypal_status["paypal_checkout_ready"],
        "paypal_webhooks_ready": paypal_status["paypal_webhooks_ready"],
        "paypal_fully_ready": paypal_status["paypal_fully_ready"],
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


# Render injects RENDER_GIT_COMMIT at build time; surfacing it lets us confirm
# exactly which commit a running instance was built from (deploy verification).
BUILD_COMMIT = (os.environ.get("RENDER_GIT_COMMIT") or "")[:12] or "unknown"


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {
        "status": "ok",
        "service": "BIPOC Creative Innovation Studio",
        "commit": BUILD_COMMIT,
    }


@app.api_route("/ready", methods=["GET", "HEAD"], include_in_schema=False)
def ready():
    # Each dependency is probed independently and never allowed to raise: an
    # unhandled error here would surface as a 500, and if a platform health
    # check is pointed at this route a momentary database blip would escalate
    # into an instance restart — which cannot fix a database, and can loop.
    # Report degraded honestly instead. Liveness belongs on /health.
    checks = {"database": False, "redis": False}
    errors: dict[str, str] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:  # noqa: BLE001 - report, never propagate
        errors["database"] = type(exc).__name__

    if redis is not None:
        try:
            redis.Redis.from_url(settings.REDIS_URL, decode_responses=True).ping()
            checks["redis"] = True
        except Exception as exc:  # noqa: BLE001 - report, never propagate
            errors["redis"] = type(exc).__name__

    paypal_status = get_paypal_configuration_status()
    checks["paypal"] = True if not paypal_status["paypal_requested"] else paypal_status["paypal_fully_ready"]

    status = "ready" if all(checks.values()) else "degraded"
    payload = {"status": status, "checks": checks}
    if errors:
        payload["errors"] = errors
    return payload
