from pathlib import Path
import re
import unittest

from jobweaver.ui_preferences import RETIRED_THEMES, VALID_THEMES

REPO = Path(__file__).resolve().parents[1]


def contrast(first, second):
    def luminance(color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in rgb]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class ThemePaletteTests(unittest.TestCase):
    """Supported palettes have real tokens and Loden controls remain readable."""

    @classmethod
    def setUpClass(cls):
        cls.css = (REPO / "webapp/src/index.css").read_text()

    def tokens(self, theme):
        selector = ":root" if theme == "loden-light" else f'[data-theme="{theme}"]'
        block = self.css.split(selector + " {", 1)[1].split("}", 1)[0]
        return dict(re.findall(r'(--[\w-]+):\s*(#[0-9a-f]{6})\s*;', block))

    def test_supported_palette_blocks_and_color_schemes(self):
        for theme in VALID_THEMES:
            tokens = self.tokens(theme)
            for name in ("--bg-color", "--primary-color", "--text-primary", "--surface-card"):
                self.assertIn(name, tokens, theme)
            selector = ":root" if theme == "loden-light" else f'[data-theme="{theme}"]'
            block = self.css.split(selector + " {", 1)[1].split("}", 1)[0]
            mode = "light" if theme in {"loden-light", "kanagawa-lotus", "catppuccin-latte"} else "dark"
            self.assertIn(f"color-scheme: {mode};", block, theme)

    def test_retired_palettes_have_no_css_definitions(self):
        for theme in RETIRED_THEMES:
            self.assertNotIn(f'[data-theme="{theme}"]', self.css)
        self.assertFalse((REPO / "webapp/src/themes.css").exists())

    def test_community_palette_identity_is_retained(self):
        accents = {
            "kanagawa-wave": "#7e9cd8", "kanagawa-dragon": "#8ba4b0", "kanagawa-lotus": "#5d57a0",
            "catppuccin-mocha": "#cba6f7", "catppuccin-latte": "#8839ef", "rose-pine": "#ebbcba", "nord": "#88c0d0",
        }
        for theme, accent in accents.items():
            self.assertEqual(self.tokens(theme)["--primary-color"], accent)

    def test_loden_text_controls_and_score_bands_have_contrast(self):
        for theme in ("loden-light", "loden-dark"):
            tokens = self.tokens(theme)
            for background in ("--bg-color", "--surface-bg", "--surface-card"):
                for text in ("--text-primary", "--text-secondary", "--text-muted", "--primary-color",
                             "--success-color", "--warning-color", "--danger-color"):
                    self.assertGreaterEqual(contrast(tokens[text], tokens[background]), 4.5, (theme, text, background))
                self.assertGreaterEqual(contrast(tokens["--control-border"], tokens[background]), 3, theme)
            self.assertGreaterEqual(contrast(tokens["--primary-text"], tokens["--primary-color"]), 4.5, theme)
            for level in ("high", "med", "low"):
                self.assertGreaterEqual(contrast(tokens[f"--score-{level}-text"], tokens[f"--score-{level}-bg"]), 4.5, theme)


if __name__ == "__main__":
    unittest.main()
