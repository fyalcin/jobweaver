"""
salary.py — Numeric salary normalization for the sortable `salary_yearly` field.

Austrian postings usually state a gross MONTHLY salary (the 14-salary
convention: 12 months + Urlaubs-/Weihnachtsremuneration). Jobs carry a
`salary_yearly` integer (EUR gross per year) next to the raw `salary` text;
unknown is None/absent, which the UI sorts last.

Two entry points:
- `salary_yearly_eur(amount, period)` — normalizes an AI-extracted
  (salary_amount, salary_period) pair from the analysis prompt.
- `parse_salary_yearly(text)` — deterministically parses a raw salary string
  (as scraped into `job.salary`) for the recent-jobs backfill
  (`scripts/backfill_salary_yearly.py`).
"""

import math
import re
from datetime import date, timedelta
from typing import Iterable, Optional

# Austria: monthly gross x 14 (12 + vacation + Christmas bonus).
MONTHS_PER_YEAR = 14

# Plausibility bounds for a full-year gross EUR figure; anything outside is
# treated as garbage (e.g. a leaked hourly rate) rather than a salary.
MIN_YEARLY = 5_000
MAX_YEARLY = 1_000_000

# Without an explicit period marker, amounts below this are assumed monthly
# (typical Austrian monthly gross) and at/above it annual.
MONTHLY_HINT_THRESHOLD = 10_000

_PERIOD_MONTH = re.compile(r"monat|mtl\b|monthly|per\s+month|a\s+month|/month", re.I)
_PERIOD_YEAR = re.compile(r"jahr|j[äa]hr|year|annual|annum|yearly", re.I)
_PERIOD_OTHER = re.compile(
    r"stund|stunden\b|/h\b|/std\b|hour|woche[ns]?\b|weekly|/week|tagessatz|/day|per\s+day", re.I)
_NON_EUR = re.compile(r"\b(?:usd|gbp|chf)\b|[$£]", re.I)

# Workload qualifiers are not wage periods: "38.5 h/Woche", "20 Stunden/Woche",
# "(40 Std / Woche)", "based on 30 hours", "auf 40 Stunden Basis". Stripped
# before period detection so "… pro Monat … 20 h/Woche" stays monthly.
_WORKLOAD_QUALIFIER = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:h|std\.?|stunden?|hours?)\s*(?:/\s*)?(?:pro\s+|per\s+|a\s+|an\s+)?"
    r"(?:woche[n]?|week|basis|base)\b",
    re.I,
)
# Apprenticeship-year qualifiers ("im 1. Lehrjahr", "im ersten Lehrjahr",
# "in the 1st year") — "Jahr/year" here is not a salary period. Stripped so
# "€ 1.200,- im 1. Lehrjahr" falls through to the monthly heuristic.
_APPRENTICESHIP_YEAR = re.compile(
    r"\b(?:\d+\.\s*|\d+\s*|(?:ersten?|zweiten?|dritten?|1st|2nd|3rd|first|second|third)\s+)"
    r"(?:lehr)?jahrs?\b",
    re.I,
)
# Swiss-style apostrophe thousands separator (2’251).
_APOSTROPHE_THOUSANDS = re.compile(r"(?<=\d)[\u2019\u2018\u02bc\u00b4`](?=\d)")

# 1.234 / 1,234 / 1 234 / 1.234.567 / 1,234.56 / 2.349,59
# 'k' thousands notation (49.2k, 49,2k, 85K, 70k, 100k€, 80-100k).
_NUM_K = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:k\s*€|k\b|[-–—/]\s*\d+(?:[.,]\d+)?\s*k\b)", re.I)
_NUM_GROUPS = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?")
_NUM_PLAIN = re.compile(r"\d+(?:[.,]\d{1,2})?")


def _bounded(value: float) -> Optional[int]:
    if value is None or not (MIN_YEARLY <= value <= MAX_YEARLY):
        return None
    return int(round(value))


def _token_to_number(token: str) -> Optional[float]:
    """Convert a number token with German or English separators to a float."""
    t = token.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    seps = list(re.finditer(r"[.,]", t))
    if not seps:
        return float(t)
    last = seps[-1]
    frac_digits = len(t) - last.end()
    if frac_digits == 3 and len(seps) == 1:
        # Single separator followed by exactly 3 digits: a thousands separator
        # in both German ("88.000") and English ("88,000") salary writing.
        return float(t.replace(last.group(), ""))
    if frac_digits in (1, 2):
        # Last separator is the decimal point ("2.349,59", "4,000.00").
        integer = re.sub(r"[.,]", "", t[: last.start()])
        return float(f"{integer}.{t[last.end():]}")
    # Multiple groups, all thousands separators ("1.234.567").
    return float(re.sub(r"[.,]", "", t))


def _extract_amount(text: str) -> tuple[Optional[float], tuple[int, int]]:
    """First number in the string (the lower bound when a range is given).

    Returns (amount, span) — the span lets period-keyword selection judge
    distance to the amount instead of matching anywhere in the string.
    """
    mk = _NUM_K.search(text)
    if mk:
        try:
            val_str = mk.group(1).replace(",", ".")
            return float(val_str) * 1000, mk.span()
        except (ValueError, OverflowError):
            pass
    m = _NUM_GROUPS.search(text) or _NUM_PLAIN.search(text)
    if not m:
        return None, (0, 0)
    try:
        return _token_to_number(m.group(0)), m.span()
    except (ValueError, OverflowError):
        return None, m.span()


def _closest_period_keyword(text: str, num_span: tuple[int, int]) -> Optional[str]:
    """Explicit period keyword nearest to the amount: 'month' | 'year' | 'other'.

    Posting wording often carries a second, qualifying year/month mention
    ("per month in the 1st year", "paid 14 times annually") — proximity to the
    amount disambiguates the stated period. Ties favour month > year > other.
    """
    best = None
    for kind, pattern in (("month", _PERIOD_MONTH), ("year", _PERIOD_YEAR), ("other", _PERIOD_OTHER)):
        for m in pattern.finditer(text):
            dist = min(abs(m.start() - num_span[1]), abs(m.end() - num_span[0]))
            if best is None or dist < best[0]:
                best = (dist, kind)
    return best[1] if best else None


def salary_yearly_eur(amount, period) -> Optional[int]:
    """Yearly EUR gross figure from an AI-extracted amount + period.

    `amount` may be a number or a numeric string; `period` is "month" or
    "year" (lenient aliases accepted). Monthly figures are multiplied by
    MONTHS_PER_YEAR (14, Austria). Returns None for anything unusable or
    implausible.
    """
    if amount is None or isinstance(amount, bool):
        return None
    if isinstance(amount, (int, float)):
        value = float(amount)
    elif isinstance(amount, str) and amount.strip():
        value = _extract_amount(_APOSTROPHE_THOUSANDS.sub(",", amount.replace("\u00a0", " ")))[0]
    else:
        value = None
    if value is None or not math.isfinite(value):
        return None

    p = (str(period) if period is not None else "").strip().lower()
    if p in ("month", "monthly", "monatlich", "monat", "m"):
        return _bounded(value * MONTHS_PER_YEAR)
    if p in ("year", "yearly", "annual", "annually", "jahr", "jährlich"):
        return _bounded(value)
    return None


def parse_salary_yearly(text) -> Optional[int]:
    """Deterministically parse a raw salary string into EUR gross per year.

    Handles German and English number formats (incl. Swiss apostrophe
    thousands), explicit monthly/yearly keywords (monthly x 14 for Austria,
    weighted by proximity to the amount), and falls back to a magnitude
    heuristic when no period is stated (< 10,000 assumed monthly). Workload
    qualifiers ("20 h/Woche") and apprenticeship-year mentions ("1. Lehrjahr")
    are not treated as wage periods. Returns None for non-EUR currencies,
    hourly/weekly/daily wages, and unparseable or implausible input.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.replace("\u00a0", " ").strip()
    t = _APOSTROPHE_THOUSANDS.sub(",", t)
    if _NON_EUR.search(t):
        return None
    t = _WORKLOAD_QUALIFIER.sub(" ", t)
    t = _APPRENTICESHIP_YEAR.sub(" ", t)
    amount, span = _extract_amount(t)
    if amount is None:
        return None
    kind = _closest_period_keyword(t, span)
    if kind == "other":
        return None
    if kind == "year":
        return _bounded(amount)
    if kind == "month":
        return _bounded(amount * MONTHS_PER_YEAR)
    # No period marker: magnitude heuristic.
    if amount < MONTHLY_HINT_THRESHOLD:
        return _bounded(amount * MONTHS_PER_YEAR)
    return _bounded(amount)


def backfill_cutoff(days: int = 7, today: Optional[date] = None) -> str:
    """Earliest `date_scraped` (ISO, inclusive) considered recent enough."""
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def select_backfill_updates(jobs: Iterable[dict], days: Optional[int] = 7, today: Optional[date] = None, force: bool = False) -> dict:
    """Plan the salary backfill for already-loaded job records.

    Returns {job_id: salary_yearly} for processed, non-one-off jobs scraped
    within the last `days` days (or all jobs if `days` is None or <= 0) whose
    raw salary text yields a plausible yearly figure. If `force` is False,
    jobs that already have a numeric salary are skipped.
    """
    cutoff = backfill_cutoff(days, today) if (days is not None and days > 0) else None
    updates: dict = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("is_one_off"):
            continue
        if not job.get("processed"):
            continue
        yearly = job.get("salary_yearly")
        if not force and yearly is not None and not (isinstance(yearly, float) and math.isnan(yearly)):
            continue
        scraped = job.get("date_scraped")
        if cutoff:
            if not isinstance(scraped, str) or not scraped or scraped < cutoff:
                continue
        parsed = parse_salary_yearly(job.get("salary"))
        if parsed is not None:
            if force and yearly == parsed:
                continue
            updates[str(job.get("id"))] = parsed
    return updates
