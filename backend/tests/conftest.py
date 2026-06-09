"""Pytest-wide test isolation.

The app reads Supabase config from `.env`, and when a service key is present
`store_media()` uploads to real Supabase Storage. Tests must never depend on
that (it makes live network calls and writes objects to the real bucket), so we
force the local-disk fallback for every test. The Supabase upload/delete path is
covered separately by tests/test_media_storage.py with mocked HTTP calls.
"""
import pytest


@pytest.fixture(autouse=True)
def _force_local_media_storage():
    # Import inside the fixture, not at module load: BaseAppTest.setUpClass purges
    # and re-imports all app.* modules, creating a fresh settings instance. We must
    # mutate the *current* one the app uses, not a stale module-load-time reference.
    from app.config import settings

    original_url = settings.SUPABASE_URL
    original_key = settings.SUPABASE_SERVICE_KEY
    # Clearing the service key makes media_storage.supabase_storage_enabled()
    # return False -> uploads go to the local media dir (deterministic, no network).
    settings.SUPABASE_SERVICE_KEY = ""
    try:
        yield
    finally:
        settings.SUPABASE_URL = original_url
        settings.SUPABASE_SERVICE_KEY = original_key
