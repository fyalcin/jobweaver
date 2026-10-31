"""Supported appearance choices and read-time migration of older IDs."""

DEFAULT_THEME = "loden-light"
DEFAULT_FONT = "fira-sans"
VALID_THEMES = {
    "loden-light", "loden-dark", "kanagawa-wave", "kanagawa-dragon",
    "kanagawa-lotus", "catppuccin-mocha", "catppuccin-latte", "rose-pine", "nord",
}
VALID_FONTS = {
    "fira-sans", "inter", "geist", "plus-jakarta-sans", "dm-sans", "ibm-plex-sans", "manrope",
}
RETIRED_THEMES = {"aurora", "ember", "neon", "aurora-ember", "aurora-neon", "amber-neon"}


def normalize_theme(value) -> str:
    theme = value.strip().lower() if isinstance(value, str) else ""
    if theme in RETIRED_THEMES:
        return "loden-dark"
    return theme if theme in VALID_THEMES else DEFAULT_THEME


def normalize_font(value) -> str:
    font = value.strip().lower() if isinstance(value, str) else ""
    return font if font in VALID_FONTS else DEFAULT_FONT


def normalize_preferences(prefs: dict) -> dict:
    return {**prefs, "theme": normalize_theme(prefs.get("theme")), "font": normalize_font(prefs.get("font"))}
