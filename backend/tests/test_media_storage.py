"""Durable media storage: Supabase Storage when configured, local disk fallback.

Guards the fix for images vanishing on Render deploys — uploads must go to
object storage (which survives deploys), not the container's ephemeral disk.
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.core import media_storage


class MediaStorageTest(unittest.TestCase):
    def setUp(self):
        self._orig = (
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY,
            settings.SUPABASE_STORAGE_BUCKET,
        )

    def tearDown(self):
        (
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY,
            settings.SUPABASE_STORAGE_BUCKET,
        ) = self._orig

    def _configure_supabase(self):
        settings.SUPABASE_URL = "https://proj.supabase.co"
        settings.SUPABASE_SERVICE_KEY = "service-key"
        settings.SUPABASE_STORAGE_BUCKET = "media"

    def test_local_fallback_when_supabase_unconfigured(self):
        settings.SUPABASE_URL = ""
        settings.SUPABASE_SERVICE_KEY = ""
        self.assertFalse(media_storage.supabase_storage_enabled())
        with TemporaryDirectory() as tmp:
            with mock.patch.object(media_storage, "FRONTEND_MEDIA_DIR", Path(tmp)):
                url = media_storage.store_media(b"hello-bytes", folder="staff")
                rel = url[len("/assets/media/"):]
                self.assertTrue((Path(tmp) / rel).exists())
        self.assertTrue(url.startswith("/assets/media/staff/"))
        self.assertTrue(url.endswith(".jpg"))

    def test_uploads_to_supabase_when_configured(self):
        self._configure_supabase()
        self.assertTrue(media_storage.supabase_storage_enabled())
        fake = mock.Mock(status_code=200, text="")
        with mock.patch.object(media_storage.httpx, "post", return_value=fake) as post:
            url = media_storage.store_media(b"img", folder="staff")
        post.assert_called_once()
        upload_url = post.call_args.args[0]
        self.assertIn("/storage/v1/object/media/staff/", upload_url)
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer service-key")
        self.assertEqual(headers["x-upsert"], "true")
        # Returned URL is the public, deploy-proof Supabase URL stored in the DB.
        self.assertTrue(
            url.startswith(
                "https://proj.supabase.co/storage/v1/object/public/media/staff/"
            )
        )

    def test_supabase_upload_failure_raises(self):
        self._configure_supabase()
        fake = mock.Mock(status_code=403, text="permission denied")
        with mock.patch.object(media_storage.httpx, "post", return_value=fake):
            with self.assertRaises(RuntimeError):
                media_storage.store_media(b"img", folder="staff")

    def test_delete_local_file(self):
        settings.SUPABASE_URL = ""
        settings.SUPABASE_SERVICE_KEY = ""
        with TemporaryDirectory() as tmp:
            with mock.patch.object(media_storage, "FRONTEND_MEDIA_DIR", Path(tmp)):
                url = media_storage.store_media(b"img", folder="rooms")
                path = Path(tmp) / url[len("/assets/media/"):]
                self.assertTrue(path.exists())
                media_storage.delete_media(url)
                self.assertFalse(path.exists())

    def test_delete_supabase_parses_bucket_and_path(self):
        self._configure_supabase()
        public = (
            "https://proj.supabase.co/storage/v1/object/public/media/staff/abc.jpg"
        )
        fake = mock.Mock(status_code=200, text="")
        with mock.patch.object(media_storage.httpx, "request", return_value=fake) as req:
            media_storage.delete_media(public)
        req.assert_called_once()
        method, url = req.call_args.args[0], req.call_args.args[1]
        self.assertEqual(method, "DELETE")
        self.assertEqual(
            url, "https://proj.supabase.co/storage/v1/object/media/staff/abc.jpg"
        )

    def test_delete_media_ignores_blank(self):
        # Should be a no-op, never raise.
        media_storage.delete_media(None)
        media_storage.delete_media("")


if __name__ == "__main__":
    unittest.main()
