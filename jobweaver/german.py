"""German-language requirement normalization and compatibility helpers."""

GERMAN_LEVELS = ("none", "A1", "A2", "B1", "B2", "C1", "C2", "native", "unknown")
_LEVEL_RANKS = {level: rank for rank, level in enumerate(GERMAN_LEVELS[:-1])}
_ALIASES = {
    "": "unknown",
    "none": "none",
    "false": "none",
    "no": "none",
    "not required": "none",
    "not specified": "unknown",
    "true": "unknown",
    "yes": "unknown",
    "required": "unknown",
    "basic": "A2",
    "beginner": "A2",
    "elementary": "A2",
    "conversational": "B1",
    "intermediate": "B1",
    "good": "B1",
    "appropriate": "B1",
    "adequate": "B1",
    "corresponding": "B1",
    "suitable": "B1",
    "working proficiency": "B2",
    "fluent": "C1",
    "very good": "C1",
    "native speaker": "native",
}


def normalize_german_level(value) -> str:
    """Return one of the supported levels for LLM, legacy, or user data."""
    if isinstance(value, bool):
        return "unknown" if value else "none"
    if value is None:
        return "unknown"
    raw = str(value).strip()
    key = raw.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    upper = raw.upper()
    if upper in {"A1", "A2", "B1", "B2", "C1", "C2"}:
        return upper
    if key == "native":
        return "native"
    return "unknown"


def german_level_compatible(level, max_level: str = "B1") -> bool:
    """Whether a job's stated requirement is at or below the candidate's level."""
    normalized = normalize_german_level(level)
    maximum = normalize_german_level(max_level)
    if normalized == "unknown" or maximum not in _LEVEL_RANKS:
        return False
    return _LEVEL_RANKS[normalized] <= _LEVEL_RANKS[maximum]


def requires_german(level) -> bool:
    return normalize_german_level(level) != "none"
