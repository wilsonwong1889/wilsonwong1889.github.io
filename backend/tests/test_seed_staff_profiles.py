"""Seed-data contracts for launch staff profiles."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.base import BaseAppTest


class StaffSeedProfileTest(BaseAppTest):
    def test_default_staff_seed_is_wilson_only_and_deactivates_legacy_demos(self) -> None:
        from app.models.staff_profile import StaffProfile
        from app.services.seed_service import DEFAULT_STAFF_PROFILE_SEEDS, ensure_staff_profiles

        with self.SessionLocal() as db:
            db.add(StaffProfile(name="Jordan Lee", active=True))
            db.add(StaffProfile(name="Local Artist", active=True))
            db.commit()

            ensure_staff_profiles(db)
            profiles = {profile.name: profile.active for profile in db.query(StaffProfile).all()}

        self.assertEqual([profile["name"] for profile in DEFAULT_STAFF_PROFILE_SEEDS], ["Wilson Wong"])
        self.assertTrue(profiles["Wilson Wong"])
        self.assertFalse(profiles["Jordan Lee"])
        self.assertTrue(profiles["Local Artist"])
