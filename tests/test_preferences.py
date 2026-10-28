import os
import shutil
import tempfile
import unittest
from unittest import mock

import db

_TMP = tempfile.mkdtemp(prefix="gj-prefs-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

import server  # noqa: E402
import user_assets  # noqa: E402


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class UiPreferencesTest(unittest.TestCase):
    """Test user_assets UI preferences functions and server endpoints."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="gj-prefs-paths-")
        patcher = mock.patch.multiple(
            user_assets,
            BASE_DIR=self.tmp_dir,
            PROFILES_DIR=os.path.join(self.tmp_dir, "profiles"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _user1():
        return {"id": 1, "username": "admin"}

    @staticmethod
    def _user2():
        return {"id": 2, "username": "sam"}

    def test_load_default_preferences(self):
        prefs = user_assets.load_ui_preferences("admin")
        self.assertEqual(prefs, {"theme": "loden-light", "font": "fira-sans"})

    def test_save_and_load_preferences(self):
        user_assets.save_ui_preferences("admin", {"theme": "kanagawa-wave", "font": "geist"})
        prefs = user_assets.load_ui_preferences("admin")
        self.assertEqual(prefs.get("theme"), "kanagawa-wave")
        self.assertEqual(prefs.get("font"), "geist")

        # sam should still be default
        sam_prefs = user_assets.load_ui_preferences("sam")
        self.assertEqual(sam_prefs.get("theme"), "loden-light")
        self.assertEqual(sam_prefs.get("font"), "fira-sans")

    def test_endpoints_get_and_put(self):
        # Initial GET
        res = server.get_ui_preferences(user=self._user1())
        self.assertEqual(res.get("theme"), "loden-light")
        self.assertEqual(res.get("font"), "fira-sans")

        # PUT valid theme & font
        payload = server.UiPreferencesPayload(theme="rose-pine", font="plus-jakarta-sans")
        put_res = server.update_ui_preferences(body=payload, user=self._user1())
        self.assertTrue(put_res["success"])
        self.assertEqual(put_res["preferences"]["theme"], "rose-pine")
        self.assertEqual(put_res["preferences"]["font"], "plus-jakarta-sans")

        # GET confirms persistence
        get_res = server.get_ui_preferences(user=self._user1())
        self.assertEqual(get_res.get("theme"), "rose-pine")
        self.assertEqual(get_res.get("font"), "plus-jakarta-sans")

        # Multi-user isolation: user2 sets catppuccin-latte
        server.update_ui_preferences(body=server.UiPreferencesPayload(theme="catppuccin-latte", font="ibm-plex-sans"), user=self._user2())
        self.assertEqual(server.get_ui_preferences(user=self._user1()).get("theme"), "rose-pine")
        self.assertEqual(server.get_ui_preferences(user=self._user1()).get("font"), "plus-jakarta-sans")
        self.assertEqual(server.get_ui_preferences(user=self._user2()).get("theme"), "catppuccin-latte")
        self.assertEqual(server.get_ui_preferences(user=self._user2()).get("font"), "ibm-plex-sans")

    def test_read_migrates_without_rewriting_saved_preferences(self):
        import json
        profile = user_assets.user_profile_dir("admin")
        os.makedirs(profile)
        path = os.path.join(profile, "ui_preferences.json")
        for old, expected in [("default", "loden-light"), ("aurora-neon", "loden-dark"),
                              ("unknown", "loden-light"), ("kanagawa-lotus", "kanagawa-lotus")]:
            original = json.dumps({"theme": old, "font": "inter"})
            with open(path, "w") as saved:
                saved.write(original)
            self.assertEqual(user_assets.load_ui_preferences("admin"), {"theme": expected, "font": "inter"})
            with open(path) as saved:
                self.assertEqual(saved.read(), original)

    def test_supported_themes_and_dark_toggle_persist(self):
        from ui_preferences import VALID_THEMES, RETIRED_THEMES
        for theme in VALID_THEMES:
            payload = server.UiPreferencesPayload(theme=theme, font="fira-sans")
            server.update_ui_preferences(body=payload, user=self._user1())
            self.assertEqual(server.get_ui_preferences(user=self._user1())["theme"], theme)
        for theme in RETIRED_THEMES:
            self.assertEqual(server.UiPreferencesPayload(theme=theme).theme, "loden-dark")
        self.assertEqual(server.UiPreferencesPayload(theme="default").theme, "loden-light")

    def test_partial_updates_preserve_companion_preference(self):
        server.update_ui_preferences(body=server.UiPreferencesPayload(theme="kanagawa-wave", font="inter"), user=self._user1())
        server.update_ui_preferences(body=server.UiPreferencesPayload(theme="loden-dark"), user=self._user1())
        self.assertEqual(server.get_ui_preferences(user=self._user1()), {"theme": "loden-dark", "font": "inter"})
        server.update_ui_preferences(body=server.UiPreferencesPayload(font="geist"), user=self._user1())
        self.assertEqual(server.get_ui_preferences(user=self._user1()), {"theme": "loden-dark", "font": "geist"})

    def test_invalid_theme_and_font_fallback(self):
        payload = server.UiPreferencesPayload(theme="nonexistent-funky-theme", font="nonexistent-font")
        self.assertEqual(payload.theme, "loden-light")
        self.assertEqual(payload.font, "fira-sans")


if __name__ == "__main__":
    unittest.main()
