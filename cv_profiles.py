"""Deterministic CV profile selection for document generation.

Profiles can be overridden per user by placing a `cv_profiles.py` (defining
a PROFILES dict with the same shape) inside `profiles/<username>/`. When a
user has no override, the repo-root profiles defined here are used.

Each PROFILES entry supports:
- label / template / compact_template / instruction (required)
- terms (set[str]): keywords scored against the job text for automatic
  selection; a profile without terms never wins automatically
- hints (set[str]): optional tiebreak keywords checked when all profiles
  are tied (first profile whose hints match wins)
- default (bool): optional; profile preferred when everything is tied and
  no hints match
"""

import importlib.util
import os
from typing import Any

from user_assets import user_profile_dir

RESEARCH_TERMS = {"research", "scientific computing", "scientific software", "computational", "physics", "materials science", "hpc", "slurm", "simulation", "postdoc", "phd", "doctoral", "laboratory", "academia"}
INDUSTRY_TERMS = {"backend", "python developer", "software developer", "automation", "api", "rest", "web application", "data engineer", "data processing", "docker", "database", "microservice", "pytest", "platform engineer"}

PROFILES = {
    "research": {
        "label": "Research Software Engineer",
        "template": "base-cv-tex/base-cv-research.tex",
        "compact_template": "base-cv-tex/base-cv-research-compact.tex",
        "instruction": "Prioritize research software engineering, scientific computing, Python, HPC/Slurm, simulation workflows, reproducibility, and research tooling.",
        "terms": RESEARCH_TERMS,
        "hints": {"research", "scientific", "physics"},
    },
    "industry": {
        "label": "Python Automation / Backend Developer",
        "template": "base-cv-tex/base-cv-industry.tex",
        "compact_template": "base-cv-tex/base-cv-industry-compact.tex",
        "instruction": "Prioritize Python automation, backend development, APIs, data processing, Docker/Linux, testing, databases, and transferable engineering outcomes.",
        "terms": INDUSTRY_TERMS,
        "default": True,
    },
}

_user_profiles_cache: dict[str, dict] = {}


def _profiles_for_user(user: str | None) -> dict:
    """Return the PROFILES dict applicable to a user (root definition by default)."""
    if not user:
        return PROFILES
    if user in _user_profiles_cache:
        return _user_profiles_cache[user]
    override_path = os.path.join(user_profile_dir(user), "cv_profiles.py")
    if not os.path.exists(override_path):
        _user_profiles_cache[user] = PROFILES
        return PROFILES
    try:
        spec = importlib.util.spec_from_file_location(f"_user_cv_profiles_{user}", override_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        profiles = getattr(module, "PROFILES", PROFILES)
    except Exception:
        profiles = PROFILES
    _user_profiles_cache[user] = profiles
    return profiles


def select_cv_profile(job: dict[str, Any], override: str | None = None, user: str | None = None) -> dict[str, Any]:
    profiles = _profiles_for_user(user)
    if override in profiles:
        return {"profile": override, "scores": {name: 0 for name in profiles}, "confidence": 1.0, "reason": f"Manual profile override: {profiles[override]['label']}"}
    text = " ".join(str(job.get(key, "") or "") for key in ("title", "description", "skills")).lower()
    scores = {name: sum(term in text for term in profile.get("terms", ())) for name, profile in profiles.items()}
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner, winning = ordered[0]
    runner = ordered[1][1] if len(ordered) > 1 else winning
    confidence = round(max(0.0, (winning - runner) / max(sum(scores.values()), 1)), 3)
    if winning == 0 or winning == runner:
        # Everything tied: first profile whose hints match, else the flagged
        # default, else the first defined profile.
        hinted = next((name for name, profile in profiles.items() if any(hint in text for hint in profile.get("hints", ()))), None)
        winner = hinted or next((name for name, profile in profiles.items() if profile.get("default")), ordered[0][0])
        confidence = 0.0
    terms_matched = sorted(term for term in profiles[winner].get("terms", ()) if term in text)
    reason = f"Automatic selection: {profiles[winner]['label']}"
    reason += f" based on {', '.join(terms_matched[:5])}." if terms_matched else ". Low-confidence match; review manually."
    return {"profile": winner, "scores": scores, "confidence": confidence, "reason": reason}


def _profile_entry(profile: str, user: str | None = None) -> dict:
    """Resolve a profile entry, falling back to the default profile, then the first defined."""
    profiles = _profiles_for_user(user)
    if profile in profiles:
        return profiles[profile]
    fallback = profiles.get(DEFAULT_PROFILE) or next(iter(profiles.values()))
    return fallback


def profile_template(profile: str, user: str | None = None) -> str:
    return _profile_entry(profile, user)["template"]


def profile_compact_template(profile: str, user: str | None = None) -> str:
    return _profile_entry(profile, user)["compact_template"]


def profile_instruction(profile: str, user: str | None = None) -> str:
    return _profile_entry(profile, user)["instruction"]


def profile_label(profile: str, user: str | None = None) -> str:
    return _profile_entry(profile, user)["label"]


def available_profiles(user: str | None = None) -> list[dict[str, str]]:
    profiles = _profiles_for_user(user)
    return [{"id": key, "label": value["label"]} for key, value in profiles.items()]


__all__ = ["PROFILES", "select_cv_profile", "profile_template", "profile_compact_template", "profile_instruction", "profile_label", "available_profiles"]

DEFAULT_PROFILE = "research"


def normalize_profile(profile: str | None, user: str | None = None) -> str | None:
    return profile if profile in _profiles_for_user(user) else None


__all__ += ["DEFAULT_PROFILE", "normalize_profile"]
