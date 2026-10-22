"""JOBWEAVER_DATA_DIR moves the database and profiles/ (used by the demo); templates stay in the repository."""
import os
import subprocess
import sys
import tempfile
import unittest


class DataDirTest(unittest.TestCase):
    def paths(self, env_value):
        env = {k: v for k, v in os.environ.items() if k != "JOBWEAVER_DATA_DIR"}
        if env_value is not None:
            env["JOBWEAVER_DATA_DIR"] = env_value
        code = "import db, user_assets; print(db.DB_PATH); print(user_assets.PROFILES_DIR); print(user_assets.BASE_DIR)"
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        return out.stdout.split()

    def test_default_is_the_repository(self):
        db_path, profiles, base = self.paths(None)
        self.assertEqual(db_path, os.path.join(base, "jobweaver.db"))
        self.assertEqual(profiles, os.path.join(base, "profiles"))

    def test_override_moves_database_and_profiles_only(self):
        with tempfile.TemporaryDirectory() as data:
            db_path, profiles, base = self.paths(data)
        self.assertEqual(db_path, os.path.join(os.path.abspath(data), "jobweaver.db"))
        self.assertEqual(profiles, os.path.join(os.path.abspath(data), "profiles"))
        self.assertNotEqual(base, os.path.abspath(data))


if __name__ == "__main__":
    unittest.main()
