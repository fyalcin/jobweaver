"""
scrapers.py — Core scraping logic decoupled from the FastAPI app.

Both server.py (via background tasks) and daily_scraper.py import from here,
eliminating the circular dependency that previously existed.
"""

import json
import logging
import os
from input_limits import ScrapeInput, ShortText, SourceLabel, validate_collection_config
from pydantic import TypeAdapter
from itertools import islice
import re
from datetime import datetime, timedelta
from typing import Optional, Callable

import pandas as pd
from dotenv import load_dotenv

import db
import demo_mode
from operation_budget import operation, current, check, OperationTerminated
import postings
from german import normalize_german_level, requires_german
from salary import parse_salary_yearly, salary_yearly_eur
from generators import AIContentFilterError, AITruncatedError, run_ai_prompt
from user_assets import resolve_user_path
from job_policy import match_rating, judgement_calls, fingerprint, analysis_response_format, description_incomplete
from analysis_validation import AnalysisValidationError, validate_extraction, save_failure

load_dotenv()
logger = logging.getLogger(__name__)



def _load_scraper_settings(user: str | None = None) -> dict:
    path = resolve_user_path(user, "scraper_config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


# Description-denoising is applied per source bucket. Config key
# `denoise_sources` lists the buckets to clean (default: manual only);
# scraper variants (browser/Apify) map onto their platform bucket.
DEFAULT_DENOISE_SOURCES = ["manual"]

_SOURCE_BUCKETS = {
    "linkedin": "linkedin",
    "linkedin-apify": "linkedin",
    "LinkedIn (Apify)": "linkedin",
    "karriere": "karriere",
    "karriere-apify": "karriere",
    "Karriere (Apify)": "karriere",
    "manual": "manual",
    # Company feeds deliver clean text from the employer's own system: no denoising.
    "company-feeds": "company_feeds",
    "Company feed (Greenhouse)": "company_feeds",
    "Company feed (Personio)": "company_feeds",
    "Company feed (Successfactors Rss)": "company_feeds",
    "Company feed (Smartrecruiters)": "company_feeds",
}


def resolve_source_bucket(source: Optional[str]) -> Optional[str]:
    """Map a scrape param or stored job source label to its config bucket.

    Returns None for unknown labels (legacy data) — callers treat that as
    denoise-enabled to preserve pre-toggle behaviour.
    """
    return _SOURCE_BUCKETS.get((source or "").strip())


def denoise_sources_for(username: Optional[str]) -> list:
    settings = _load_scraper_settings(username)
    val = settings.get("denoise_sources")
    if not isinstance(val, list):
        return list(DEFAULT_DENOISE_SOURCES)
    return val


def denoise_enabled(username: Optional[str], source: Optional[str]) -> bool:
    bucket = resolve_source_bucket(source)
    if bucket is None:
        return True
    return bucket in denoise_sources_for(username)


def _parse_llm_json_object(raw: str) -> dict:
    """Strip markdown fences and parse JSON; retry on inner `{...}` if needed."""
    t = raw.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i = t.find("{")
        j = t.rfind("}")
        if i >= 0 and j > i:
            return json.loads(t[i : j + 1])
        raise


def _karriere_job_id_from_url(url: str) -> str:
    """karriere.at's own job number as a stable ID, or "" (the gate then rejects the record: a random ID
    would store the same posting again on every run)."""
    m = re.search(r"/jobs/(\d+)", url) if isinstance(url, str) else None
    return f"karriere_{m.group(1)}" if m else ""


def _karriere_apify_item_to_job(item: dict) -> dict:
    """Map a blackfalcondata/karriere-at-scraper record to the job schema.

    Structured salary (salaryMin + salaryPeriod) feeds salary_yearly directly;
    the free-text salaryText is the fallback (same parser as the backfill).
    The id derivation matches the selenium scraper (same /jobs/<id> space), so
    dedup and upserts stay stable when the source switches.
    """
    url = item.get("url") or ""
    yearly = salary_yearly_eur(item.get("salaryMin"), item.get("salaryPeriod"))
    if yearly is None:
        yearly = parse_salary_yearly(item.get("salaryText"))
    return {
        "job_url": url,
        "title": item.get("title") or "",
        "company": item.get("company") or "",
        "location": item.get("location") or "",
        "description": item.get("description") or "",
        "salary": item.get("salaryText") or None,
        "salary_yearly": yearly,
        "posted_date": item.get("postedDate") or None,
        "type": item.get("employmentType"),
        "id": _karriere_job_id_from_url(url),
    }


LINKEDIN_ACTOR_BEBITY = "bebity/linkedin-jobs-scraper"
# curious_coder/linkedin-jobs-scraper: same public pages, but its applyUrl was empty in 247 of
# 247 items (checked 11.10.2026). Kept as the fallback when the bebity actor fails or is empty.
LINKEDIN_ACTOR_LEGACY = "hKByXkMQaC5Qt9UMN"


def _linkedin_search_urls(keywords: str, location: str, hours_old: int, distance: int) -> list:
    """One LinkedIn job-search URL (full-time, posted within `hours_old`) per comma-separated phrase."""
    from urllib.parse import quote_plus

    phrases = [k.strip() for k in keywords.split(",") if k.strip()] or [keywords]
    tpr = hours_old * 3600
    return [
        (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={quote_plus(kw)}"
            f"&location={quote_plus(location)}"
            f"&f_TPR=r{tpr}"
            f"&f_JT=F"
            f"&distance={distance}"
        )
        for kw in phrases
    ]


def _linkedin_legacy_item_to_job(item: dict) -> dict:
    """Map a curious_coder/linkedin-jobs-scraper record to the job schema (no apply link)."""
    return {
        "job_url":     item.get("link", ""),
        "title":       item.get("title", ""),
        "company":     item.get("companyName", ""),
        "location":    item.get("location", ""),
        "description": item.get("descriptionText") or "",
        "salary":      ", ".join(item.get("salaryInfo") or []) or None,
        "id":          f"li_{item['id']}" if item.get("id") else "",
    }


def _linkedin_bebity_item_to_job(item: dict) -> dict:
    """Map a bebity/linkedin-jobs-scraper record to the job schema.

    The actor labels every job EASY_APPLY or EXTERNAL. For EXTERNAL jobs it usually returns the
    company's own application URL (49 of 51 in the tests of 12.10.2026). `apply_url` is set only
    for that case: for Easy Apply, `applyUrl` is just the LinkedIn page again. `apply_type` is
    'external' or 'easy_apply'; an external job with `apply_url` None means the actor found no link.
    """
    from urllib.parse import urlparse

    apply_type = (item.get("applyType") or "").strip().lower() or None
    url = (item.get("applyUrl") or "").strip()
    company_url = bool(url) and "linkedin.com" not in urlparse(url).netloc.lower()
    return {
        "job_url":     item.get("jobUrl") or "",
        "title":       item.get("title") or "",
        "company":     item.get("companyName") or "",
        "location":    item.get("location") or "",
        "description": item.get("description") or "",
        "salary":      item.get("salary") or None,
        "id":          f"li_{item['id']}" if item.get("id") else "",
        "apply_type":  apply_type,
        "apply_url":   url if apply_type == "external" and company_url else None,
    }


def _filter_by_posted_age(df: "pd.DataFrame", hours_old: int, log_fn: Callable) -> "pd.DataFrame":
    """Drop rows whose ISO posted_date is older than `hours_old` hours.

    Rows without a parseable posted_date are kept (lenient: the age filter
    must not silently discard data when the portal didn't expose a date).
    """
    if df is None or df.empty or not hours_old or "posted_date" not in df.columns:
        return df
    now = datetime.now().astimezone()

    def _fresh(val) -> bool:
        if not val:
            return True
        try:
            posted = datetime.fromisoformat(str(val))
        except ValueError:
            return True
        if posted.tzinfo is None:
            posted = posted.astimezone()
        return posted >= now - timedelta(hours=hours_old)

    mask = df["posted_date"].apply(_fresh)
    dropped = int((~mask).sum())
    if dropped:
        log_fn(f"Karriere Apify: dropped {dropped} listing(s) older than {hours_old}h (postedDate).", "info")
    return df[mask].copy()


# ---------------------------------------------------------------------------
# Shared request validation without importing FastAPI or the server.
# ---------------------------------------------------------------------------

class ScrapeParams:
    def __init__(
        self,
        results_limit: int = 5,
        hours_old: int = 48,
        distance: int = 10,
        keywords: str = "python OR backend developer",
        source: str = "linkedin-apify",
        label: str | None = None,
        lane: str | None = None,
    ):
        validated = ScrapeInput(results_limit=results_limit, hours_old=hours_old,
                                distance=distance, keywords=keywords, source=source)
        self.results_limit = validated.results_limit
        self.hours_old = validated.hours_old
        self.distance = validated.distance
        self.keywords = validated.keywords
        # `source` dispatches the scraper branch; `label` is what gets STORED, so probe runs
        # can be told apart from the main lane without pretending to be a different actor.
        self.source = validated.source
        self.label = TypeAdapter(SourceLabel).validate_python(label) if label is not None else None
        # `lane` tags stored rows with a search lane (e.g. "bridge") so the UI can show them apart.
        self.lane = TypeAdapter(ShortText).validate_python(lane) if lane is not None else None


# ---------------------------------------------------------------------------
# AI analysis helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Job-description cleanup
# ---------------------------------------------------------------------------

# Bare language-name lines belong to page language selectors (REWE-style
# "Sprache auswählen" blocks). Only dropped when they appear in a run of
# two or more — a lone line that happens to read like a language name is
# kept (it might be content).
_LANGUAGE_LIST_WORDS = {
    "german", "english", "croatian", "serbian", "slovakian", "czech",
    "hungarian", "turkish", "italian", "slovenian", "french", "spanish",
    "polish", "dutch", "portuguese", "russian", "ukrainian", "romanian",
    "bulgarian", "greek", "danish", "swedish", "norwegian", "finnish",
}

_BOILERPLATE_LINE_PATTERNS = [
    re.compile(r"^sprache ausw[äa]hlen\b", re.I),
    re.compile(r"^(select|choose) (your )?language\b", re.I),
    re.compile(r"^language selection\b", re.I),
    re.compile(r"^information zur übersetzung\b", re.I),
    re.compile(r"^die übersetzung erfolgt automatisch\b", re.I),
    re.compile(r"^the translation (is done|happens) automatically\b", re.I),
    re.compile(r"google translate", re.I),
    re.compile(r"keine gew[äa]hr f[üu]r richtigkeit", re.I),
    re.compile(r"^cookie", re.I),
    re.compile(r"wir verwenden cookies", re.I),
    re.compile(r"^(impressum|datenschutz|datenschutzerklärung|agb|sitemap)\b", re.I),
    re.compile(r"^(teilen|drucken|merken|report this job|share this job|print this job|save this job)\b", re.I),
    re.compile(r"^öffnet in neuem fenster", re.I),
    re.compile(r"^jetzt bewerben$", re.I),
    re.compile(r"^(apply now|apply online)$", re.I),
]


def clean_job_description_noise(text: str) -> str:
    """Deterministically strip page furniture from a fetched/scraped description.

    Removal-only and conservative: language-selector blocks, translation
    notices, cookie/consent lines and common portal chrome. Content lines are
    never rewritten or dropped by pattern unless they clearly match boilerplate.
    Returns the original text if cleaning would leave too little behind.
    """
    if not text:
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    is_lang = [ln.strip().lower() in _LANGUAGE_LIST_WORDS for ln in lines]

    out = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if is_lang[idx]:
            in_run = (idx > 0 and is_lang[idx - 1]) or (idx + 1 < len(lines) and is_lang[idx + 1])
            if in_run:
                continue
        if stripped and any(p.search(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            continue
        out.append(line)

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    # Safety floor: if over-stripping left almost nothing, keep the original.
    return cleaned if len(cleaned) >= 200 else text


_GERMAN_LEVEL_RULES = """
For german_level, return the lowest level clearly required by the job. Use
"none" when German is not required, and "unknown" only when the description
does not provide enough evidence. Infer from wording when no explicit CEFR
level is given: basic/beginner -> A2, conversational/intermediate -> B1,
good/appropriate/adequate German without a CEFR level -> B1, working
proficiency -> B2, fluent/very good -> C1, and native speaker -> native.
When German is explicitly required but the wording is vague, return unknown.
Use unknown
when the description gives genuinely insufficient evidence to assess the
requirement. Mark preferred German as preferred, not mandatory, and
do not turn a company location or a German-language job description alone into
a German requirement.
"""


_SALARY_RULES = """
For salary_amount / salary_period report the gross salary stated in the posting
as a number plus its period. Austrian postings usually state a gross MONTHLY
salary (collective-agreement style, e.g. "€ 3.400,- monatl." or a KV minimum) —
report that monthly figure with salary_period "month"; the app converts it to a
yearly figure (14 salaries). Annual figures ("60.000 € brutto/Jahr",
"€60,000 per year") get salary_period "year". If the posting gives a range,
report the lower bound. Never convert between periods yourself and never invent
a figure: report exactly what is stated. Hourly, weekly or daily wages have
salary_amount null and salary_period null. When no salary is stated at all,
both are null.
"""


_MATCHING_RULES = """
For match_checks, list every stated requirement once. Use must for firm requirements, nice for optional or unclear requirements.
posting_quote must be the shortest contiguous verbatim posting quote that states the requirement and its weight.
coverage is shown when the CV states the skill directly, related for transferable experience, missing without CV evidence.
cv_quote must be a contiguous verbatim CV quote supporting shown or related; use an empty string for missing.
Do not substitute the posting, paraphrases or inferred skills for CV evidence.
For preference_conflicts, use only the explicit Standing Notes section of the CV, never employment-history prose.
Quote both the Standing Notes and posting verbatim. Hard severity requires explicit must-language in the notes
(only, never, must, not willing, requires); other preferences are soft. Omit conflicts without both quotes.
Do not rate the job overall. The app computes the rating from the verified evidence. match_analysis is display-only prose.
"""


def _build_analysis_prompt(description: str, cv_text: Optional[str], include_cleanup: bool) -> str:
    fields = [
        '"german_strength": "required" | "preferred" | "none" | "unknown"',
        '"german_evidence": "Exact supporting quote from the posting, or empty string"',
        '"constraints": [{"kind": "german" | "work_country" | "work_authorization" | "other", "strength": "required" | "preferred" | "unknown", "value": "Required value (ISO country code for country)", "evidence": "Exact quote"}]',
        '"salary_currency": "EUR" | "USD" | "GBP" | "CHF" | "unknown"',
        '"salary_country": "ISO jurisdiction code, or empty string"',
        '"salary_payments": "Explicit annual payment count or null; never assume 14 outside Austria"',
        '"german_level": "none" | "A1" | "A2" | "B1" | "B2" | "C1" | "C2" | "native" | "unknown"',
        '"minimum_salary": "The salary exactly as stated in the posting (raw text), or \'Not Specified\'"',
        '"salary_amount": Number or null — the (lowest) gross salary amount stated in the posting',
        '"salary_period": "month" | "year" | null — the period of salary_amount',
        '"skills": "Comma-separated list of required skills, or \'Not Specified\'"',
        '"summary": "1-2 sentence punchy overview of the role, core responsibilities, and top perks/mission (no company names or locations)"',
        '"work_model": "Full-time" | "Part-time" | "Hybrid (Home Office)" | "Remote" | "On-site" | "Unknown"',
        '"experience_years": "e.g. \'3 years\', \'Entry-level\', \'5+ years\', or \'Not Specified\'"',
        '"education_level": "e.g. \'Bachelor\\\'s degree\', \'Master\\\'s degree\', \'Technical degree\', or \'Not Specified\'"',
        '"tools_technologies": ["Array", "of", "concrete", "technical", "tools", "libraries", "languages", "or", "frameworks"]',
        '"requirements": ["Array", "of", "clean", "bulleted", "qualification", "and", "requirement", "points"]',
        '"tasks": ["Array", "of", "clean", "bulleted", "responsibility", "and", "task", "points"]',
        '"company_summary": "1-2 sentence summary of what the company does and its core field/industry, or null if unknown"',
        '"company_contact": "Full name and title of the recruiter or contact person if explicitly named in the posting (e.g. \'Frau Ursula Popp\', \'Dr. Thomas Meier\'), or null if no specific person is named"',
    ]
    if include_cleanup:
        fields.append(
            '"cleaned_description": "The job description, cleaned up: remove leftover page noise (navigation elements, '
            'cookie/consent notices, language selectors, image alt-texts, button labels, repeated headers/footers) and '
            'fix obvious line-break damage so the text reads like a proper job posting. IMPORTANT: This is removal-only '
            'editing — keep ALL substantive content (tasks, responsibilities, requirements, qualifications, benefits, '
            'salary, location, working hours, application instructions) verbatim, in the original order and wording. '
            'NEVER summarize, shorten, paraphrase or drop content."'
        )
    if cv_text:
        fields.append('"match_checks": [{"requirement": "Short requirement", "importance": "must" | "nice", "posting_quote": "Exact posting quote", "coverage": "shown" | "related" | "missing", "cv_quote": "Exact CV quote or empty string"}]')
        fields.append('"preference_conflicts": [{"preference": "Short preference", "notes_quote": "Exact Standing Notes quote", "posting_quote": "Exact posting quote", "severity": "hard" | "soft"}]')
        fields.append(
            '"match_analysis": {\n'
            '    "synthesis": "2-3 sentence overarching evaluation explaining why this candidate fits and the primary tradeoff/growth area",\n'
            '    "strengths": [{"title": "Short bold title", "detail": "1-2 sentences referencing candidate background aligning with requirements"}],\n'
            '    "gaps": [{"title": "Short bold title", "detail": "1-2 sentences describing missing or less demonstrated skills or logistics"}],\n'
            '    "tips": [{"title": "Action title", "detail": "1-2 sentences tactical advice for application or interview to overcome gaps"}]\n'
            '  }'
        )
    prompt = (
        "Analyze this job description and extract the following information.\n"
        "Respond ONLY with a valid JSON object. Do not include markdown formatting like ```json.\n\n"
        "Posting evidence must be a contiguous, verbatim quote from the Job Description in its ORIGINAL language. "
        "Never translate, paraphrase, change case/punctuation, join separate excerpts, or quote the Candidate CV. "
        "Whitespace differences alone are tolerated; copy the original whitespace when possible. "
        "Omit absent constraints (use an empty constraints array); constraint strength must NEVER be 'none'. "
        "Do not infer work authorization from a company location.\n\n"
        "Required JSON structure:\n{\n  " + ",\n  ".join(fields) + "\n}\n\n"
        + _GERMAN_LEVEL_RULES
        + "\n" + _SALARY_RULES
    )
    if cv_text:
        prompt += "\n" + _MATCHING_RULES
    prompt += "\nJob Description:\n" + description
    if cv_text:
        prompt += "\n\nCandidate CV:\n" + cv_text
    return prompt


def _validated_salary(data):
    currency = data.salary_currency
    if currency == 'unknown' and ('€' in data.minimum_salary or 'EUR' in data.minimum_salary.upper()):
        currency = 'EUR'
    if currency != 'EUR':
        return None
    if data.salary_period == 'year':
        return salary_yearly_eur(data.salary_amount, 'year')
    payments = data.salary_payments or (14 if data.salary_country.upper() == 'AT' else None)
    if data.salary_period == 'month' and payments and data.salary_amount is not None:
        return salary_yearly_eur(data.salary_amount * payments, 'year')
    return None


_TRUNCATED_FEEDBACK = (
    '\n\nPrevious response was cut off at the length limit. Return a complete, shorter JSON object: '
    'at most 8 entries in each list, one sentence per detail, and do not repeat the job description.'
)


@operation('interactive')
def process_job_with_ai(
    description: str,
    cv_text: Optional[str] = None,

    model_name: str = "z-ai/glm-5.3-flash",
    denoise: bool = True,
) -> dict:
    try:
        raw_description = description or ''
        if denoise:
            description = clean_job_description_noise(description or "")

        include_cleanup = denoise
        feedback = ''
        # One shared budget for schema/evidence correction and JSON cleanup fallback.
        # Provider/auth/client/network exceptions are not output-validation errors.
        validated = None
        for attempt in (1, 2):
            try:
                text = run_ai_prompt(
                    _build_analysis_prompt(description, cv_text, include_cleanup=include_cleanup) + feedback,
                    model_name=model_name, max_retries=1, label='Posting analysis',
                    response_format=analysis_response_format(bool(cv_text), include_cleanup),
                )
            except AIContentFilterError:
                # Preserve the existing cleanup-echo fallback, but share the budget.
                if attempt == 1 and include_cleanup:
                    include_cleanup = False
                    feedback = ''
                    continue
                raise
            except AITruncatedError:
                # A cut-off answer is an output failure like invalid JSON: one
                # shorter retry within the same budget, without the echo.
                if attempt == 1:
                    include_cleanup = False
                    feedback = _TRUNCATED_FEEDBACK
                    continue
                raise
            try:
                data = _parse_llm_json_object(text)
            except json.JSONDecodeError:
                issues = [{'path': '<response>', 'type': 'invalid_json',
                           'message': 'Response must be a valid JSON object'}]
                save_failure(raw_description, model_name, attempt, None, text, issues)
                if attempt == 1:
                    include_cleanup = False
                    feedback = '\n\nPrevious response was invalid JSON. Return a complete valid JSON object.'
                    continue
                raise ValueError('AI response was invalid JSON') from None
            try:
                validated = validate_extraction(data, raw_description, bool(cv_text), cv_text or '')
                break
            except AnalysisValidationError as error:
                # Save the INITIAL rejection before the correction call can replace it.
                save_failure(raw_description, model_name, attempt, data, text, error.issues)
                if attempt == 2:
                    raise
                feedback = (
                    '\n\nValidation feedback for the previous response:\n' + str(error) +
                    '\nReturn the entire corrected JSON object. Correct only against the Job Description; '
                    'never use candidate facts as posting evidence. Evidence must be original-language '
                    'contiguous verbatim quotes (case and punctuation unchanged); omit absent constraints. '
                    'Do not emit constraint strength none. Supply every requirement once with verified posting and CV quotes. '
                )
        assert validated is not None  # Every exhausted failure above raises.
        german_level = validated.german_level

        # Trust but verify the AI cleanup: a cleaned description that lost more
        # than 40% of its length is treated as over-eager summarizing and
        # discarded in favour of the (pre-cleaned) original.
        cleaned = data.get("cleaned_description")
        # Accept only a verbatim subsequence of original lines, never invented replacement text.
        original_lines = iter(line.strip() for line in description.splitlines())
        removal_only = isinstance(cleaned, str) and all(any(line == candidate.strip() for line in original_lines)
            for candidate in cleaned.strip().splitlines() if candidate.strip())
        if removal_only and cleaned.strip() and len(cleaned.strip()) >= max(200, int(len(description) * 0.6)):
            description = cleaned.strip()

        # Parse and normalize structured fields safely
        checks = [c.model_dump() for c in validated.match_checks or []]
        conflicts = [c.model_dump() for c in validated.preference_conflicts]
        label = match_rating(checks, conflicts) if cv_text else None
        match_analysis = validated.match_analysis.model_dump() if validated.match_analysis else None
        if not isinstance(match_analysis, dict):
            match_analysis = {
                "tier": label,
                "synthesis": data.get("summary", ""),
                "strengths": [],
                "gaps": [],
                "tips": [],
            }
        else:
            match_analysis.setdefault("tier", label)
            match_analysis.setdefault("synthesis", data.get("summary", ""))
            match_analysis.setdefault("strengths", [])
            match_analysis.setdefault("gaps", [])
            match_analysis.setdefault("tips", [])
        match_analysis['tier'] = label

        tools_technologies = data.get("tools_technologies")
        if not isinstance(tools_technologies, list):
            raw_skills = str(data.get("skills", "")).split(",")
            tools_technologies = [s.strip() for s in raw_skills if s.strip() and s.strip().lower() != "not specified"]

        requirements_list = data.get("requirements")
        if not isinstance(requirements_list, list):
            requirements_list = []

        tasks_list = data.get("tasks")
        if not isinstance(tasks_list, list):
            tasks_list = []

        return {
            "raw_description": raw_description,
            "normalized_description": description,
            "normalization_version": 1,
            "analysis_state": "complete",
            "analysis_fingerprint": fingerprint(cv_text, model_name),
            "analysis_model": model_name,
            "german_strength": validated.german_strength,
            "german_evidence": validated.german_evidence,
            "constraints": [c.model_dump() for c in validated.constraints],
            "german_level": german_level,
            "requires_german": requires_german(german_level),
            "salary": data.get("minimum_salary") or "Not Specified",
            "salary_yearly": _validated_salary(validated),
            "salary_currency": validated.salary_currency,
            "salary_country": validated.salary_country,
            "salary_payments": validated.salary_payments,
            "skills": data.get("skills", "Not Specified"),
            "summary": data.get("summary", "Summarization Failed"),
            "work_model": data.get("work_model") or "Unknown",
            "experience_years": data.get("experience_years") or "Not Specified",
            "education_level": data.get("education_level") or "Not Specified",
            "tools_technologies": tools_technologies,
            "requirements": requirements_list,
            "tasks": tasks_list,
            "company_summary": data.get("company_summary") or None,
            "company_contact": data.get("company_contact") or None,
            "match_score": None,
            "analysis_schema": 2,
            "match_rating": label,
            "match_checks": checks,
            "preference_conflicts": conflicts,
            "judgement_calls": judgement_calls(checks, conflicts) if cv_text else [],
            "grounding_status": 'adjusted' if validated.grounding_issues else 'verified',
            "grounding_issues": validated.grounding_issues,
            "match_analysis": match_analysis,
            "description": description,
        }
    except Exception as e:
        # Exception bodies may contain model input, provider headers or candidate prose.
        logger.error('AI processing error (%s)', type(e).__name__)
        raise


NO_DESCRIPTION_ERROR = 'Posting description unavailable; acquisition incomplete'


@operation('interactive')
def analyse_stored_job(job: dict, user: dict, cv_text: Optional[str], model_name: str) -> tuple[bool, Optional[str]]:
    """Analyse one job already in the DB and store the result.

    Shared by "Process Now" and the daily retry. A job without a description
    can never succeed, so it is marked `skipped` (out of the pending queue)
    instead of `failed`. Returns (success, error message).
    """
    user_id = user["id"]
    jid = job.get("id", "")
    desc = job.get("raw_description", job.get("description", ""))
    if not isinstance(desc, str) or not desc.strip():
        db.update_job_fields(jid, user_id=user_id, processed=0, analysis_state='skipped',
                             analysis_error=NO_DESCRIPTION_ERROR)
        return False, NO_DESCRIPTION_ERROR
    try:
        ai_data = process_job_with_ai(
            desc, cv_text, model_name=model_name,
            denoise=denoise_enabled(user.get("username"), job.get("source", "")),
        )
        update_kwargs = {
            **{key: ai_data.get(key) for key in ('raw_description', 'normalized_description', 'analysis_state',
                 'analysis_fingerprint', 'analysis_model', 'analysis_schema', 'match_rating', 'match_checks', 'preference_conflicts', 'judgement_calls', 'grounding_status', 'grounding_issues', 'german_strength', 'german_evidence', 'constraints',
                 'salary_currency', 'salary_country', 'salary_payments') if key in ai_data},
            "processed": 1,
            "german_level": ai_data["german_level"],
            "requires_german": ai_data["requires_german"],
            "salary": job.get("salary") or ai_data["salary"],
            "salary_yearly": job.get("salary_yearly") or ai_data.get("salary_yearly"),
            "skills": ai_data["skills"],
            "summary": ai_data["summary"],
            "match_score": ai_data["match_score"],
            "work_model": ai_data.get("work_model"),
            "experience_years": ai_data.get("experience_years"),
            "education_level": ai_data.get("education_level"),
            "tools_technologies": ai_data.get("tools_technologies", []),
            "requirements": ai_data.get("requirements", []),
            "tasks": ai_data.get("tasks", []),
            "company_summary": ai_data.get("company_summary"),
            "match_analysis": ai_data.get("match_analysis", {}),
        }
        if ai_data.get("company_contact"):
            update_kwargs["company_contact"] = ai_data["company_contact"]
        db.update_job_fields(jid, user_id=user_id, **update_kwargs)
        return True, None
    except Exception as e:
        db.update_job_fields(jid, user_id=user_id, processed=0, analysis_state='failed', analysis_error=str(e))
        if isinstance(e, OperationTerminated):
            raise
        return False, str(e)


@operation('collection')
def retry_failed_analyses(user: dict, cv_text: Optional[str], model_name: str,
                          days: int = 3, limit: int = 15) -> tuple[int, int]:
    """Give recently failed analyses another try (daily run).

    Bounded twice: only jobs scraped in the last `days` days (so a job is
    retried at most `days` times by the cron) and at most `limit` per run
    (each costs up to two model calls). Returns (succeeded, still failed).
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    jobs = [j for j in db.load_unprocessed_jobs(user["id"])
            if j.get("analysis_state") == 'failed' and str(j.get("date_scraped") or "") >= since][:limit]
    succeeded = failed = 0
    for job in jobs:
        check()
        ok, err = analyse_stored_job(job, user, cv_text, model_name)
        if ok:
            succeeded += 1
        else:
            failed += 1
            logger.error("Retry failed for job %s: %s", job.get("id"), err)
    return succeeded, failed


# ---------------------------------------------------------------------------
# Core scrape logic
# ---------------------------------------------------------------------------

LOCATION = "Vienna, AT"


def _present(record: dict) -> dict:
    """Drop the empty cells a DataFrame adds for fields a Posting does not have."""
    return {k: v for k, v in record.items() if not (v is None or (isinstance(v, float) and v != v))}


@operation('collection')
def scrape_new_jobs(
    params: ScrapeParams,
    log_fn: Optional[Callable] = None,
    cv_text: Optional[str] = None,

    model_name: str = "z-ai/glm-5.3-flash",
    async_task_id: Optional[str] = None,
    user: Optional[dict] = None,
) -> dict:
    """
    Scrape jobs, process with AI, and upsert into the DB — scoped to `user`
    (a dict with at least {"id", "username"}). Each user has their own job
    pool, dedup index, and CV-based analysis.
    Returns a dict with success/message/new_jobs_count.
    """
    demo_mode.refuse_if_enabled()
    # Revalidate at execution too: callers may retain and modify this mutable object.
    ScrapeInput.model_validate(vars(params))
    if not user or "id" not in user:
        raise ValueError("scrape_new_jobs requires a user dict with an 'id' (multi-user storage)")
    user_id = user["id"]
    username = user.get("username")
    if log_fn is None:
        log_fn = lambda msg, level="info": db.add_log(msg, level, user_id=user_id)

    log_fn(f"Started scraping '{params.keywords}' (limit {params.results_limit}, distance {params.distance}km).", "info")

    settings = validate_collection_config(_load_scraper_settings(username))
    linkedin_location = (settings.get("linkedin_location") or "").strip() or LOCATION
    karriere_region = (settings.get("karriere_region") or "").strip() or "wien-und-umgebung"
    denoise = denoise_enabled(username, params.source)

    jobs_df = None
    source_errors = []

    if params.source == "linkedin-apify":
        APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
        if not APIFY_API_TOKEN:
            log_fn("APIFY_API_TOKEN not found. LinkedIn Apify scrape failed.", "error")
            return {"success": False, "message": "APIFY_API_TOKEN not found."}
        try:
            from apify_client import ApifyClient

            apify_client = ApifyClient(APIFY_API_TOKEN)
            urls = _linkedin_search_urls(params.keywords, linkedin_location, params.hours_old, params.distance)
            log_fn(f"LinkedIn Apify: {len(urls)} keyword URL(s), count={params.results_limit} each.", "info")
            for u in urls:
                log_fn(f"  → {u}", "info")

            attempts = [
                (LINKEDIN_ACTOR_BEBITY,
                 {"startUrls": [{"url": u} for u in urls], "maxRowsPerUrl": params.results_limit},
                 _linkedin_bebity_item_to_job),
                (LINKEDIN_ACTOR_LEGACY,
                 {"urls": urls, "scrapeCompany": False, "count": params.results_limit},
                 _linkedin_legacy_item_to_job),
            ]
            records, actor_errors = [], []
            for actor_id, run_input, to_job in attempts:
                try:
                    run = apify_client.actor(actor_id).call(run_input=run_input)
                    items = list(islice(apify_client.dataset(run["defaultDatasetId"]).iterate_items(),
                                        params.results_limit * len(urls)))
                except Exception as e:
                    logger.error(f"LinkedIn Apify actor {actor_id} failed: {e}")
                    actor_errors.append(f"{actor_id}: {e}")
                    log_fn(f"LinkedIn Apify: actor {actor_id} failed ({e}); trying the next one.", "warning")
                    continue
                if items:
                    records = [to_job(item) for item in items]
                    break
                log_fn(f"LinkedIn Apify: actor {actor_id} returned no jobs; trying the next one.", "warning")
            if records:
                jobs_df = pd.DataFrame(records)
                jobs_df["source"] = params.label or "LinkedIn (Apify)"
            elif actor_errors:
                source_errors.extend(actor_errors)
                log_fn("LinkedIn Apify scrape error: " + "; ".join(actor_errors), "error")
        except Exception as e:
            logger.error(f"LinkedIn Apify scrape error: {e}")
            source_errors.append(str(e))
            log_fn(f"LinkedIn Apify scrape error: {e}", "error")

    elif params.source == "karriere-apify":
        APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
        if not APIFY_API_TOKEN:
            log_fn("APIFY_API_TOKEN not found. Apify scrape failed.", "error")
            return {"success": False, "message": "APIFY_API_TOKEN not found."}
        try:
            from apify_client import ApifyClient

            client = ApifyClient(APIFY_API_TOKEN)
            keywords_list = [k.strip() for k in params.keywords.split(",") if k.strip()] or [params.keywords]
            # Incremental state is per user + keyword + region: the actor's
            # key-value store emits only NEW/UPDATED listings per tracked
            # search universe, so two users must never share a stateKey.
            frames = []
            for kw in keywords_list:
                state_key = f"gj-{username or 'shared'}-karriere-{karriere_region}-{kw}"[:200]
                log_fn(f"Karriere Apify: actor run for '{kw}' (limit {params.results_limit}, incremental).", "info")
                run = client.actor("blackfalcondata/karriere-at-scraper").call(run_input={
                    "query": kw,
                    "location": karriere_region,
                    "radius": str(params.distance),
                    "maxResults": params.results_limit,
                    "includeDetails": True,  # descriptions + postedDate are detail-level fields
                    "descriptionFormat": "text",
                    "excludeEmptyFields": True,
                    "incrementalMode": True,
                    "stateKey": state_key,
                })
                items = list(islice(client.dataset(run["defaultDatasetId"]).iterate_items(), params.results_limit))
                log_fn(f"Karriere Apify: {len(items)} listing(s) for '{kw}'.", "info")
                if items:
                    frames.append(pd.DataFrame([_karriere_apify_item_to_job(item) for item in items]))
            if frames:
                jobs_df = pd.concat(frames, ignore_index=True)
                jobs_df["source"] = "Karriere (Apify)"
        except Exception as e:
            logger.error(f"Karriere Apify scrape error: {e}")
            source_errors.append(str(e))
            log_fn(f"Karriere Apify scrape error: {e}", "error")

    elif params.source == "company-feeds":
        import company_feeds

        try:
            feed_config = company_feeds.load_companies(username)
            log_fn(f"Company feeds: {len(feed_config['companies'])} compan(y/ies) in companies.json.", "info")
            feed_rows, feed_errors = company_feeds.fetch_company_postings(feed_config, log_fn=log_fn)
            source_errors.extend(feed_errors)
            # The same job may already be stored from LinkedIn or karriere.at under another URL and id.
            stored = db.load_jobs(user_id)
            feed_rows, dup_count = company_feeds.drop_known_elsewhere(
                feed_rows, stored.to_dict(orient="records") if stored is not None and not stored.empty else [])
            if dup_count:
                log_fn(f"Company feeds: skipped {dup_count} posting(s) that another source already stored.", "info")
            if feed_rows:
                jobs_df = pd.DataFrame(feed_rows)  # each row already carries its source label
        except Exception as e:
            logger.error(f"Company feeds error: {e}")
            source_errors.append(str(e))
            log_fn(f"Company feeds error: {e}", "error")

    else:
        message = (f"Unknown source '{params.source}'. Sources: linkedin-apify, karriere-apify, company-feeds; "
                   "other Sources plug in through postings.py.")
        log_fn(message, "error")
        return {"success": False, "state": "failed", "message": message, "errors": [message]}

    if jobs_df is None or jobs_df.empty:
        log_fn("No jobs found from scraper.", "warning")
        return {"success": not source_errors, "state": "failed" if source_errors else "empty", "message": "Source failed." if source_errors else "No new jobs found.", "errors": source_errors}

    # The gate (ADR-0006): only records with every required field, and only schema fields, go further.
    gate_result = postings.gate(jobs_df.to_dict(orient="records"), params.label or params.source)
    gate_summary = gate_result.summary()
    if gate_summary:
        level, message = gate_summary
        log_fn(message, level)
        if level == "error":
            source_errors.append(message)
    if gate_result.short_descriptions:
        log_fn(f"{gate_result.short_descriptions} posting(s) have a description under {postings.SHORT_DESCRIPTION} "
               "characters; the Source may have cut them off.", "warning")
    if not gate_result.postings:
        return {"success": False, "state": "failed", "message": "No record passed the gate.",
                "errors": source_errors, "rejected": gate_result.rejected}
    jobs_df = pd.DataFrame(gate_result.postings)

    # Apify Karriere listings carry an ISO postedDate (detail-page field);
    # honour params.hours_old as a true age gate there (the karriere.at site
    # itself has no age filter).
    if params.source == "karriere-apify":
        jobs_df = _filter_by_posted_age(jobs_df, params.hours_old, log_fn)
        if jobs_df.empty:
            log_fn("No jobs left after posting-age filter.", "warning")
            return {"success": not source_errors, "state": 'partial' if source_errors else 'empty', "source_errors": source_errors, "message": "No new jobs within the age window."}

    raw_count = len(jobs_df)
    log_fn(f"Scraper returned {raw_count} raw results.", "info")

    if 'job_url' in jobs_df.columns:
        # Collapse duplicates before saving or paying for analysis.
        nonempty = jobs_df['job_url'].fillna('').astype(str).str.strip() != ''
        jobs_df = pd.concat([jobs_df[nonempty].drop_duplicates('job_url', keep='last'), jobs_df[~nonempty]])
    selected = []
    now = datetime.now().isoformat()
    for _, row in jobs_df.iterrows():
        record = _present(row.to_dict())
        previous = db.get_job_by_url(record.get('job_url'), user_id) if record.get('job_url') else None
        if previous is None and record.get('id'):
            # LinkedIn URLs carry per-search tracking parameters, so the same job can arrive under a
            # different URL; its id is the stable identity.
            previous = db.get_job_by_id(str(record['id']), user_id)
        if previous and previous.get('raw_description', previous.get('description')) == record.get('description'):
            db.update_job_fields(previous['id'], user_id=user_id, last_seen=now)
            continue
        if previous:
            record['id'] = previous['id']
            record['first_seen'] = previous.get('first_seen', previous.get('date_scraped'))
        selected.append(record)
    new_jobs = pd.DataFrame(selected)

    dedup_skipped = raw_count - len(new_jobs)
    if dedup_skipped:
        log_fn(f"Deduplication: skipped {dedup_skipped} already-in-DB, {len(new_jobs)} remaining.", "info")

    if new_jobs.empty:
        log_fn(f"All {raw_count} scraped jobs already in DB.", "warning")
        return {"success": not source_errors, "state": 'partial' if source_errors else 'empty', "source_errors": source_errors, "message": "No new jobs after deduplication."}

    # Retain incomplete observations; lack of description is not a successful extraction.
    dropped_empty = 0
    if 'description' not in new_jobs.columns:
        new_jobs['description'] = ''

    # --- Step 1: Save all new jobs to DB immediately with processed=0 ---
    today = datetime.now().strftime("%Y-%m-%d")
    staged_ids = []
    for index, job in new_jobs.iterrows():
        # A field this Posting lacks must not erase what an earlier sighting stored.
        job_data = _present(job.to_dict())
        job_data.setdefault("status", "new")
        job_data.setdefault("applied", False)
        job_data.setdefault("application_date", None)
        job_data.setdefault("application_method", None)
        job_data.setdefault("response_status", None)
        job_data.setdefault("company_contact", None)
        job_data["date_scraped"] = today
        job_data['raw_description'] = job_data.get('description') or ''
        job_data['first_seen'] = job_data.get('first_seen') or datetime.now().isoformat()
        job_data['last_seen'] = datetime.now().isoformat()
        job_data['acquisition_state'] = 'complete' if job_data['raw_description'] else 'incomplete'
        job_data['description_incomplete'] = description_incomplete(job_data['raw_description'])
        if params.lane:
            job_data['lane'] = params.lane
        job_data['analysis_state'] = 'pending'
        job_data['match_score'] = None
        job_data['match_rating'] = None
        job_data["processed"] = 0
        db.upsert_job(job_data, user_id=user_id)
        canonical = db.get_job_by_url(job_data.get('job_url'), user_id) if job_data.get('job_url') else None
        if canonical:
            new_jobs.at[index, 'id'] = canonical['id']
        staged_ids.append(str(canonical['id'] if canonical else job_data.get('id', '')))

    log_fn(f"Saved {len(staged_ids)} raw jobs to DB. Starting AI analysis…", "info")

    analysis_total = len(new_jobs)
    if async_task_id:
        db.async_task_update(async_task_id, stage='analysing', total=analysis_total, processed=0, failed=0)

    # --- Step 2: Analyze each job and mark processed=1 on success ---
    processed_count = 0
    analysis_errors = 0
    
    from background_queue import bounded_results
    import threading
    update_lock = threading.Lock()
    
    def _process_job(job_row):
        job_id = str(job_row.get("id", ""))
        desc = job_row.get("description", "")
        title = job_row.get("title", "unknown")

        if not isinstance(desc, str) or not desc.strip():
            # Can never succeed: keep it out of the pending queue.
            db.update_job_fields(job_id, user_id=user_id, analysis_state='skipped',
                                 analysis_error=NO_DESCRIPTION_ERROR, processed=0)
            return False, NO_DESCRIPTION_ERROR, title
        try:
            ai_data = process_job_with_ai(str(desc), cv_text, model_name=model_name, denoise=denoise)
            # A scraper-derived salary_yearly (e.g. structured salaryMin from
            # the Karriere Apify actor) is authoritative — the AI value only
            # fills jobs where the scraper couldn't provide one.
            row_yearly = job_row.get("salary_yearly")
            if row_yearly is None or (isinstance(row_yearly, float) and pd.isna(row_yearly)):
                row_yearly = None
            row_salary = job_row.get("salary")
            if row_salary is None or (isinstance(row_salary, float) and pd.isna(row_salary)):
                row_salary = None
            update_kwargs = {
                **{key: ai_data.get(key) for key in ('raw_description', 'normalized_description', 'normalization_version',
                     'analysis_state', 'analysis_fingerprint', 'analysis_model', 'analysis_schema', 'match_rating', 'match_checks', 'preference_conflicts', 'judgement_calls', 'grounding_status', 'grounding_issues', 'german_strength', 'german_evidence', 'constraints',
                     'salary_currency', 'salary_country', 'salary_payments') if key in ai_data},
                "processed": 1,
                "german_level": ai_data["german_level"],
                "requires_german": ai_data["requires_german"],
                "salary": row_salary or ai_data["salary"],
                "salary_yearly": row_yearly or ai_data.get("salary_yearly"),
                "skills": ai_data["skills"],
                "summary": ai_data["summary"],
                "match_score": ai_data["match_score"],
                "description": ai_data.get("description", desc),
                "work_model": ai_data.get("work_model"),
                "experience_years": ai_data.get("experience_years"),
                "education_level": ai_data.get("education_level"),
                "tools_technologies": ai_data.get("tools_technologies", []),
                "requirements": ai_data.get("requirements", []),
                "tasks": ai_data.get("tasks", []),
                "company_summary": ai_data.get("company_summary"),
                "match_analysis": ai_data.get("match_analysis", {}),
            }
            if ai_data.get("company_contact"):
                update_kwargs["company_contact"] = ai_data["company_contact"]
            db.update_job_fields(job_id, user_id=user_id, **update_kwargs)
            return True, None, title
        except Exception as e:
            db.update_job_fields(job_id, user_id=user_id, analysis_state='failed', analysis_error=str(e), processed=0)
            if isinstance(e, OperationTerminated):
                raise
            return False, str(e), title

    def cancelled():
        if not async_task_id:
            return False
        row = db.async_task_get_scrape(async_task_id, user_id)
        return bool(row and row['cancelled'])

    max_workers = 2
    with bounded_results(_process_job, (row for _, row in new_jobs.iterrows()),
                         max_workers, cancelled=cancelled) as results:
        for success, err, title in results:
            with update_lock:
                if success:
                    processed_count += 1
                else:
                    analysis_errors += 1
                    logger.error(f"Failed to process job '{title}' with AI: {err}")
                    log_fn(f"AI analysis error for '{title}': {err}", "error")
                if async_task_id:
                    db.async_task_update(async_task_id, processed=processed_count, failed=analysis_errors)

    if analysis_errors:
        log_fn(f"{analysis_errors} jobs failed AI analysis — they remain in DB and can be retried.", "warning")

    log_fn(
        f"Done: {raw_count} scraped → {dedup_skipped} dupes → {dropped_empty} incomplete observations discarded → {analysis_errors} AI errors → {processed_count} processed.",
        "warning" if source_errors or analysis_errors else "success"
    )
    return {"success": not source_errors and not analysis_errors, "state": 'partial' if source_errors or analysis_errors else 'complete',
            "message": f"Processed {processed_count} jobs; {analysis_errors} failed.", "new_jobs_count": processed_count,
            "failed_count": analysis_errors, "source_errors": source_errors}
