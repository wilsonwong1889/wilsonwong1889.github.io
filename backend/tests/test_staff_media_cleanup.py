"""Media cleanup on staff profile edit/delete: removed headshots are cleaned up,
and an image still referenced elsewhere is never deleted."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffMediaCleanupTest(BaseAppTest):
    def _create(self, db, **kwargs):
        from app.schemas.staff import StaffProfileCreate
        from app.services.staff_service import create_staff_profile
        return create_staff_profile(db, StaffProfileCreate(**kwargs))

    def test_removed_headshot_is_deleted(self) -> None:
        from app.schemas.staff import StaffProfileUpdate
        from app.services.staff_service import update_staff_profile

        with self.SessionLocal() as db:
            profile = self._create(
                db,
                name="Media Eng",
                photo_url="/assets/media/staff/avatar.jpg",
                headshot_urls=["/assets/media/staff/h1.jpg", "/assets/media/staff/h2.jpg"],
            )
            pid = profile.id

        with patch("app.services.staff_service.delete_media") as del_media:
            with self.SessionLocal() as db:
                update_staff_profile(
                    db, pid,
                    StaffProfileUpdate(headshot_urls=["/assets/media/staff/h1.jpg"]),
                )
        # Only the dropped headshot h2 is deleted; avatar + kept headshot survive.
        deleted = {call.args[0] for call in del_media.call_args_list}
        self.assertEqual(deleted, {"/assets/media/staff/h2.jpg"})

    def test_changed_avatar_still_used_as_headshot_is_not_deleted(self) -> None:
        from app.schemas.staff import StaffProfileUpdate
        from app.services.staff_service import update_staff_profile

        shared = "/assets/media/staff/shared.jpg"
        with self.SessionLocal() as db:
            profile = self._create(
                db, name="Shared Eng", photo_url=shared, headshot_urls=[shared],
            )
            pid = profile.id

        with patch("app.services.staff_service.delete_media") as del_media:
            with self.SessionLocal() as db:
                # Change the avatar but keep the same image as a headshot.
                update_staff_profile(
                    db, pid,
                    StaffProfileUpdate(photo_url="/assets/media/staff/new.jpg"),
                )
        # The shared image is still referenced (as a headshot) -> must NOT be deleted.
        deleted = {call.args[0] for call in del_media.call_args_list}
        self.assertNotIn(shared, deleted)

    def test_image_referenced_by_another_profile_is_not_deleted(self) -> None:
        from app.schemas.staff import StaffProfileUpdate
        from app.services.staff_service import delete_staff_profile, update_staff_profile

        shared = "/assets/media/staff/team.jpg"
        with self.SessionLocal() as db:
            a = self._create(db, name="Eng A", headshot_urls=[shared])
            self._create(db, name="Eng B", photo_url=shared)
            a_id = a.id

        with patch("app.services.staff_service.delete_media") as del_media:
            with self.SessionLocal() as db:
                # A drops the shared headshot, but B still uses it as its avatar.
                update_staff_profile(db, a_id, StaffProfileUpdate(headshot_urls=[]))
                delete_staff_profile(db, a_id)
        deleted = {call.args[0] for call in del_media.call_args_list}
        self.assertNotIn(shared, deleted)
