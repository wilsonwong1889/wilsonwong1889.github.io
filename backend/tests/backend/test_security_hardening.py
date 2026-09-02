"""
Backend tests — security hardening.

Regression cover for the findings in the 2026-09-02 security audit: rate-limit
client identification and eviction, upload size limits, and decompression-bomb
rejection.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.base import BaseAppTest


class _FakeRequest:
    """Minimal stand-in — client_identifier only reads headers and .client."""

    class _Client:
        def __init__(self, host):
            self.host = host

    def __init__(self, headers=None, peer="10.0.0.1"):
        self.headers = headers or {}
        self.client = self._Client(peer) if peer else None


class RateLimitIdentityTest(unittest.TestCase):
    def test_falls_back_to_peer_when_no_forwarded_header(self) -> None:
        from app.core.rate_limit import client_identifier

        self.assertEqual(client_identifier(_FakeRequest(peer="8.8.8.8")), "8.8.8.8")

    def test_uses_forwarded_address_instead_of_the_proxy(self) -> None:
        """Behind Render the peer is an internal 10.x address. Bucketing on it
        puts every visitor in one bucket, so one caller could exhaust the auth
        limit and lock everybody out."""
        from app.core.rate_limit import client_identifier

        req = _FakeRequest({"x-forwarded-for": "8.8.8.8"}, peer="10.27.243.135")
        self.assertEqual(client_identifier(req), "8.8.8.8")

    def test_a_spoofed_leading_entry_does_not_win(self) -> None:
        """The leftmost entry is whatever the caller sent. Each proxy appends the
        peer it actually saw, so the rightmost public address is the trustworthy
        one — otherwise anyone could mint unlimited buckets with a header."""
        from app.core.rate_limit import client_identifier

        req = _FakeRequest(
            {"x-forwarded-for": "1.2.3.4, 1.1.1.1"}, peer="10.27.243.135"
        )
        self.assertEqual(client_identifier(req), "1.1.1.1")

    def test_all_private_chain_falls_back_to_peer(self) -> None:
        from app.core.rate_limit import client_identifier

        req = _FakeRequest({"x-forwarded-for": "10.1.1.1, 192.168.0.5"}, peer="10.0.0.9")
        self.assertEqual(client_identifier(req), "10.0.0.9")

    def test_garbage_header_does_not_raise(self) -> None:
        from app.core.rate_limit import client_identifier

        req = _FakeRequest({"x-forwarded-for": "not-an-ip, ;;;"}, peer="10.0.0.9")
        self.assertEqual(client_identifier(req), "10.0.0.9")


class RateLimitEvictionTest(unittest.TestCase):
    def test_keys_are_evicted_once_their_window_passes(self) -> None:
        """The map only ever grew: expired timestamps were trimmed inside each
        deque, but the keys themselves were never removed, so every address that
        ever called became a permanent entry."""
        from app.core import rate_limit

        rate_limit._requests.clear()
        for i in range(500):
            rate_limit._requests[f"auth:key-{i}"].append(0.0)  # long expired
        self.assertEqual(len(rate_limit._requests), 500)

        rate_limit._sweep_locked(window_start=1_000_000.0)
        self.assertEqual(len(rate_limit._requests), 0)

    def test_live_entries_survive_the_sweep(self) -> None:
        from time import time

        from app.core import rate_limit

        rate_limit._requests.clear()
        now = time()
        rate_limit._requests["auth:198.51.100.1"].append(now)
        rate_limit._requests["auth:198.51.100.2"].append(0.0)

        rate_limit._sweep_locked(window_start=now - 60)
        self.assertIn("auth:198.51.100.1", rate_limit._requests)
        self.assertNotIn("auth:198.51.100.2", rate_limit._requests)


class SharedRateLimitTest(unittest.TestCase):
    """Counters must be shared across instances. Production runs two servers, so
    a per-process dict meant the effective limit was a multiple of the
    configured one, and every deploy reset it."""

    def setUp(self) -> None:
        from unittest.mock import patch

        from app.config import settings as app_settings
        from app.core import rate_limit

        self.rate_limit = rate_limit
        rate_limit._requests.clear()
        # The suite disables the limiter (Redis counters persist across it), so
        # turn it back on for the tests that exist to exercise it.
        enabled = patch.object(app_settings, "RATE_LIMIT_ENABLED", True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_redis_is_preferred_when_available(self) -> None:
        from unittest.mock import patch

        calls = []

        def fake_check(key, max_requests, now, window):
            calls.append(key)
            return True

        with patch.object(self.rate_limit, "_check_redis", side_effect=fake_check):
            dep = self.rate_limit.rate_limit_dependency("auth", 5)
            dep(_FakeRequest({"x-forwarded-for": "8.8.8.8"}, peer="10.0.0.1"))

        self.assertEqual(calls, ["ratelimit:auth:8.8.8.8"])
        # Nothing should have been recorded in the per-process fallback.
        self.assertEqual(len(self.rate_limit._requests), 0)

    def test_falls_back_to_memory_when_redis_cannot_answer(self) -> None:
        """A Redis blip must not take sign-in down with it."""
        from unittest.mock import patch

        with patch.object(self.rate_limit, "_check_redis", return_value=None):
            dep = self.rate_limit.rate_limit_dependency("auth", 2)
            req = _FakeRequest({"x-forwarded-for": "8.8.8.8"}, peer="10.0.0.1")
            dep(req)
            dep(req)
            with self.assertRaises(Exception) as ctx:
                dep(req)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 429)

    def test_the_limit_is_enforced_per_caller(self) -> None:
        from unittest.mock import patch

        with patch.object(self.rate_limit, "_check_redis", return_value=None):
            dep = self.rate_limit.rate_limit_dependency("auth", 1)
            dep(_FakeRequest({"x-forwarded-for": "8.8.8.8"}, peer="10.0.0.1"))
            # A different caller behind the same proxy must not be blocked by it.
            dep(_FakeRequest({"x-forwarded-for": "1.1.1.1"}, peer="10.0.0.1"))


class UploadLimitTest(BaseAppTest):
    def test_oversized_upload_is_refused_while_streaming(self) -> None:
        """`await upload.read()` with no argument buffers the whole body before
        any size check, so a huge post exhausts memory before the limit is
        consulted. The capped reader must stop partway."""
        import asyncio

        from fastapi import HTTPException

        from app.core.image_utils import read_upload_within_limit

        class _Upload:
            def __init__(self, total, chunk=64 * 1024):
                self.remaining = total
                self.chunk = chunk
                self.read_bytes = 0

            async def read(self, size=-1):
                if self.remaining <= 0:
                    return b""
                n = min(self.chunk if size == -1 else size, self.remaining)
                self.remaining -= n
                self.read_bytes += n
                return b"\0" * n

        upload = _Upload(total=5 * 1024 * 1024)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.get_event_loop().run_until_complete(
                read_upload_within_limit(upload, max_bytes=1024 * 1024)
            )
        self.assertEqual(ctx.exception.status_code, 413)
        # It must have stopped early, not drained the whole 5 MB.
        self.assertLess(upload.read_bytes, 5 * 1024 * 1024)

    def test_upload_within_the_limit_is_returned_whole(self) -> None:
        import asyncio

        from app.core.image_utils import read_upload_within_limit

        class _Upload:
            def __init__(self, payload):
                self.buf = io.BytesIO(payload)

            async def read(self, size=-1):
                return self.buf.read(64 * 1024 if size == -1 else size)

        payload = b"x" * (300 * 1024)
        got = asyncio.get_event_loop().run_until_complete(
            read_upload_within_limit(_Upload(payload), max_bytes=1024 * 1024)
        )
        self.assertEqual(got, payload)


class DecompressionBombTest(BaseAppTest):
    def test_image_over_the_pixel_ceiling_is_refused_before_decoding(self) -> None:
        """A heavily compressed image can sit well under the 40 MB byte limit and
        still expand to gigabytes of pixels."""
        from unittest.mock import patch

        from fastapi import HTTPException
        from PIL import Image

        from app.core import image_utils

        buf = io.BytesIO()
        Image.new("RGB", (600, 600), (255, 255, 255)).save(buf, format="PNG")
        payload = buf.getvalue()

        # Real bombs are gigapixel; shrink the ceiling instead of building one.
        with patch.object(image_utils, "MAX_IMAGE_PIXELS", 1000):
            with self.assertRaises(HTTPException) as ctx:
                image_utils.to_jpeg_bytes(payload)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("too large", ctx.exception.detail.lower())

    def test_a_normal_photo_still_converts(self) -> None:
        from PIL import Image

        from app.core.image_utils import to_jpeg_bytes

        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (10, 40, 62)).save(buf, format="PNG")
        out = to_jpeg_bytes(buf.getvalue())
        self.assertTrue(out.startswith(b"\xff\xd8"), "expected JPEG magic bytes")


class UploadLimitIsStatedToTheUserTest(BaseAppTest):
    def test_frontend_limit_matches_the_server_limit(self) -> None:
        """The page tells people the maximum before they pick a file. If that
        number drifts from the one the server enforces, we either promise more
        than we accept or refuse uploads we said were fine."""
        import re

        from app.core.image_utils import MAX_PHOTO_BYTES

        js = self.client.get("/assets/js/upload-limits.js").text
        match = re.search(r"MAX_PHOTO_MB\s*=\s*(\d+)", js)
        self.assertIsNotNone(match, "MAX_PHOTO_MB not found in upload-limits.js")
        self.assertEqual(int(match.group(1)) * 1024 * 1024, MAX_PHOTO_BYTES)

    def test_the_limit_helper_is_actually_loaded(self) -> None:
        """A helper nobody imports states the limit to nobody."""
        main_js = self.client.get("/assets/js/main.js").text
        self.assertIn("upload-limits.js", main_js)
        self.assertIn("attachAllPhotoLimits", main_js)

    def test_server_rejection_names_the_limit(self) -> None:
        """The message travels to the browser through FastAPI's `detail`, so it
        has to read as a sentence rather than an error code."""
        import asyncio

        from fastapi import HTTPException

        from app.core.image_utils import MAX_PHOTO_BYTES, read_upload_within_limit

        class _Upload:
            async def read(self, size=-1):
                return b"\0" * (1024 * 1024)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.get_event_loop().run_until_complete(
                read_upload_within_limit(_Upload(), max_bytes=1024)
            )
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("MB or smaller", ctx.exception.detail)


class VendoredSupabaseTest(BaseAppTest):
    def test_supabase_client_is_served_from_our_own_origin(self) -> None:
        """Google sign-in used to fetch the client from esm.sh at the moment
        someone clicked the button, so a CDN outage broke sign-in."""
        resp = self.client.get("/assets/js/vendor/supabase-js-2.114.0.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("javascript", resp.headers["content-type"])
        self.assertIn("createClient", resp.text)

    def test_the_bundle_is_self_contained(self) -> None:
        """esm.sh's own bundle imports /node/process.mjs and /node/buffer.mjs
        from their origin, which would have left the dependency in place. This
        one is built from npm and must reach for nothing."""
        body = self.client.get("/assets/js/vendor/supabase-js-2.114.0.js").text
        self.assertNotIn('"/node/', body)
        self.assertNotIn("esm.sh", body.split("*/", 1)[-1])

    def test_nothing_still_imports_from_the_cdn(self) -> None:
        module = self.client.get("/assets/js/supabase.js").text
        self.assertIn("/assets/js/vendor/supabase-js", module)
        # The word may appear in a comment explaining why; an import must not.
        self.assertNotIn('import("https://esm.sh', module)
        self.assertNotIn("import('https://esm.sh", module)


class ContentSecurityPolicyTest(BaseAppTest):
    def test_policy_is_report_only_until_checkout_has_been_exercised(self) -> None:
        """A policy that blocks the PayPal SDK breaks the one flow that earns
        money. Report-only surfaces the same violations without that risk."""
        headers = self.client.get("/").headers
        self.assertIn("Content-Security-Policy-Report-Only", headers)
        self.assertNotIn("Content-Security-Policy", [k for k in headers if k.lower() == "content-security-policy"])

    def test_policy_allows_what_the_site_actually_loads(self) -> None:
        from app.main import build_csp

        policy = build_csp()
        # PayPal's SDK, its artwork, its API and its frames.
        self.assertIn("https://www.paypal.com", policy)
        self.assertIn("https://www.paypalobjects.com", policy)
        self.assertIn("https://www.sandbox.paypal.com", policy)
        # The embedded map on the homepage.
        self.assertIn("https://www.google.com", policy)
        # Banner artwork hosted on the foundation's own site.
        self.assertIn("https://www.bipocfoundation.org", policy)

    def test_scripts_get_no_inline_exemption(self) -> None:
        """Styles are allowed inline because nine style attributes remain in the
        markup and a style attack is far smaller. Scripts are not."""
        from app.main import build_csp

        policy = build_csp()
        script_directive = [d for d in policy.split("; ") if d.startswith("script-src")][0]
        self.assertNotIn("unsafe-inline", script_directive)
        self.assertNotIn("unsafe-eval", script_directive)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("base-uri 'self'", policy)

    def test_supabase_origin_comes_from_settings(self) -> None:
        """Hard-coding it would silently break auth in any other environment."""
        from unittest.mock import patch

        from app.config import settings as app_settings
        from app.main import build_csp

        with patch.object(app_settings, "SUPABASE_URL", "https://example-project.supabase.co"):
            policy = build_csp()
        self.assertIn("https://example-project.supabase.co", policy)


if __name__ == "__main__":
    unittest.main()
