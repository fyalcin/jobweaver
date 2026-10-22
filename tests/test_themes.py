import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES_CSS = os.path.join(REPO, "webapp", "src", "themes.css")
PALETTE_THEMES = [
    "aurora",
    "ember",
    "neon",
    "aurora-ember",
    "aurora-neon",
    "amber-neon",
]


class ThemePaletteTests(unittest.TestCase):
    """The palette themes must exist as real CSS-variable blocks."""

    def setUp(self):
        with open(THEMES_CSS, "r", encoding="utf-8") as f:
            self.css = f.read()

    def test_themes_css_exists(self):
        self.assertTrue(os.path.exists(THEMES_CSS))

    def test_each_palette_theme_has_variable_block(self):
        for tid in PALETTE_THEMES:
            self.assertIn(f'[data-theme="{tid}"] {{', self.css, f"{tid} missing var block")

    def test_blocks_define_core_variables(self):
        for tid in PALETTE_THEMES:
            block = self.css.split(f'[data-theme="{tid}"] {{', 1)[1].split("}", 1)[0]
            for var in ("--bg-color", "--primary-color", "--brand-gradient", "--nav-active-bg"):
                self.assertIn(var, block, f"{tid} missing {var}")

    def test_component_overrides_are_scoped(self):
        total = self.css.count(".job-card {")
        scoped = len(re.findall(r'\[data-theme="[^"]+"\] \.job-card \{', self.css))
        self.assertEqual(total, scoped, "found an unscoped .job-card override in themes.css")


if __name__ == "__main__":
    unittest.main()
