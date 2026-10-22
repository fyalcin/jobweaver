"""user_assets.py — per-user asset resolution with repo-root fallback.

Each household member gets a `profiles/<username>/` directory that can hold
their own CV plaintext, LaTeX templates, CV profiles, scraper config, and
generated outputs/drafts. For shared assets (CV, templates, config) a
per-user file is used when present, otherwise the repo-root original.
Outputs and drafts are always per-user — no root fallback.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Where the database and profiles/ live: this folder by default, or JOBWEAVER_DATA_DIR (the demo, a container
# volume). Templates and other shared files always come from BASE_DIR.
DATA_DIR = os.path.abspath(os.path.expanduser(os.environ.get("JOBWEAVER_DATA_DIR") or BASE_DIR))
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")


def user_profile_dir(username: str | None) -> str:
    """Absolute path of a user's profile directory (repo root for None)."""
    if not username:
        return BASE_DIR
    return os.path.join(PROFILES_DIR, username)


def resolve_user_path(username: str | None, relative: str) -> str:
    """Per-user file path when `profiles/<user>/<relative>` exists, else root."""
    root_path = os.path.join(BASE_DIR, relative)
    if not username:
        return root_path
    user_path = os.path.join(user_profile_dir(username), relative)
    return user_path if os.path.exists(user_path) else root_path


def user_outputs_dir(username: str | None) -> str:
    """Generated application PDFs for a user (always per-user)."""
    return os.path.join(user_profile_dir(username), "outputs")


def user_drafts_dir(username: str | None) -> str:
    """Transient LaTeX/draft artefacts for a user (always per-user)."""
    return os.path.join(user_profile_dir(username), "drafts")


def user_documents_dir(username: str | None) -> str:
    """Standalone CV Studio documents library for a user (always per-user)."""
    return os.path.join(user_profile_dir(username), "documents")


def ensure_user_dirs(username: str) -> None:
    """Create the profile directory skeleton for a new user."""
    for sub in ("outputs", "drafts", "documents"):
        os.makedirs(os.path.join(user_profile_dir(username), sub), exist_ok=True)


def load_standing_notes(username: str | None) -> str:
    """Read a user's standing notes (recent focus, new technologies) if present."""
    notes_path = resolve_user_path(username, "standing_notes.txt")
    if os.path.exists(notes_path):
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""
    return ""


def load_effective_cv(username: str | None) -> str:
    """The text job scoring sees: from the user's career record if they have one (ADR-0004), else their
    CV-plaintext.txt; standing notes are appended either way."""
    import career_record
    record, _ = career_record.for_user(username)
    cv = career_record.scoring_text(record) if record else ""
    cv_path = resolve_user_path(username, "CV-plaintext.txt")
    if not record and os.path.exists(cv_path):
        try:
            with open(cv_path, "r", encoding="utf-8") as f:
                cv = f.read()
        except OSError:
            cv = ""
    notes = load_standing_notes(username)
    if notes:
        return f"{cv}\n\nRecent Experience & Standing Notes:\n{notes}" if cv else notes
    return cv


def load_ui_preferences(username: str | None) -> dict:
    """Load UI preferences for a user (theme, font, visual defaults)."""
    default_prefs = {"theme": "default", "font": "inter"}
    if not username:
        return default_prefs
    path = os.path.join(user_profile_dir(username), "ui_preferences.json")
    if os.path.exists(path):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {**default_prefs, **data}
        except Exception:
            pass
    return default_prefs


def save_ui_preferences(username: str | None, prefs: dict) -> dict:
    """Save UI preferences for a user in profiles/<user>/ui_preferences.json."""
    if not username:
        return {"theme": "default", "font": "inter"}
    current = load_ui_preferences(username)
    current.update(prefs)
    dir_path = user_profile_dir(username)
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, "ui_preferences.json")
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    return current


