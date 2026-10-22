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
        self.assertEqual(prefs, {"theme": "default", "font": "inter"})

    def test_save_and_load_preferences(self):
        user_assets.save_ui_preferences("admin", {"theme": "kanagawa-wave", "font": "geist"})
        prefs = user_assets.load_ui_preferences("admin")
        self.assertEqual(prefs.get("theme"), "kanagawa-wave")
        self.assertEqual(prefs.get("font"), "geist")

        # sam should still be default
        sam_prefs = user_assets.load_ui_preferences("sam")
        self.assertEqual(sam_prefs.get("theme"), "default")
        self.assertEqual(sam_prefs.get("font"), "inter")

    def test_endpoints_get_and_put(self):
        # Initial GET
        res = server.get_ui_preferences(user=self._user1())
        self.assertEqual(res.get("theme"), "default")
        self.assertEqual(res.get("font"), "inter")

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

    def test_invalid_theme_and_font_fallback(self):
        payload = server.UiPreferencesPayload(theme="nonexistent-funky-theme", font="nonexistent-font")
        self.assertEqual(payload.theme, "default")
        self.assertEqual(payload.font, "inter")


if __name__ == "__main__":
    unittest.main()
