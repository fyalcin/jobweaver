"""Company job-feed readers: a Jobweaver source that reads employers' own published job feeds (T029).

Each reader turns one employer's feed into rows with the fields the pipeline needs (title, company, location,
job_url, description, id, posted_date, apply_url). Readers never touch the database; `fetch_company_postings`
runs a user's list of companies (`profiles/<user>/companies.json`) and returns rows plus per-company errors.
A company whose reader fails, or whose rows miss a required field, is reported and skipped; the others still run.

Feeds used (all public, no key): Greenhouse board JSON, Personio XML, SuccessFactors RSS, SmartRecruiters
postings API. The first run imports a company's whole open inventory that passes the filters; later runs add
only postings the database does not know yet (the scrape pipeline deduplicates).
"""
import hashlib
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Optional
from urllib.parse import quote, quote_plus

from postings import html_to_text, to_posting
from user_assets import resolve_user_path

logger = logging.getLogger(__name__)

DEFAULT_LOCATION_PATTERN = r"wien|vienna|klosterneuburg|laxenburg|seibersdorf|austria.*remote|remote.*austria"
# A gendered title suffix such as "(m/w/d)" is a strong sign of a German-language ad.
_GERMAN_TITLE_FORMS = re.compile(r"\((?:m/w/d|w/m/d|m/f/d|w/m/x|m/w/x|d/m/w|gn\*?|m/w|w/m)\)", re.I)
USER_AGENT = "Jobweaver-feed-reader/1.0"


class FeedError(Exception):
    """A feed could not be read or did not have the expected shape."""


Fetch = Callable[..., str]


def http_fetch(url: str, headers: Optional[dict] = None, timeout: int = 40) -> str:
    """GET a feed URL and return the body text. Tests replace this with a recorded sample."""
    import requests

    resp = requests.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


# --- text helpers ---------------------------------------------------------------------------------------------

def _iso(value) -> Optional[str]:
    """Normalise a feed date to an ISO string, or None when it cannot be read."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return None


def _row(connector: str, entry: dict, native_id: str, **fields) -> dict:
    """Build a row; `source` names the reader and `company_feed` the employer entry in companies.json."""
    return {
        "id": f"feed_{connector}_{entry['identifier']}_{native_id}"[:200],
        "company": entry.get("name") or entry["identifier"],
        "apply_type": "external",
        "source": f"Company feed ({connector.replace('_', ' ').title()})",
        "company_feed": entry.get("name") or entry["identifier"],
        **fields,
    }


# --- readers --------------------------------------------------------------------------------------------------

def read_greenhouse(entry: dict, fetch: Fetch, keep: Optional[Callable] = None) -> list:
    url = f"https://boards-api.greenhouse.io/v1/boards/{quote(entry['identifier'])}/jobs?content=true"
    try:
        data = json.loads(fetch(url))
        jobs = data["jobs"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FeedError(f"Greenhouse board '{entry['identifier']}': unexpected response ({exc})")
    rows = []
    for job in jobs:
        rows.append(_row(
            "greenhouse", entry, str(job.get("id")),
            title=(job.get("title") or "").strip(),
            location=((job.get("location") or {}).get("name") or "").strip(),
            job_url=job.get("absolute_url") or "",
            apply_url=job.get("absolute_url") or None,
            # The board returns the ad as HTML that is escaped once more.
            description=html_to_text(html.unescape(job.get("content") or "")),
            posted_date=_iso(job.get("first_published") or job.get("updated_at")),
            language=(job.get("language") or None),
        ))
    return rows


def read_personio(entry: dict, fetch: Fetch, keep: Optional[Callable] = None) -> list:
    ident = entry["identifier"]
    try:
        root = ET.fromstring(fetch(f"https://{quote(ident)}.jobs.personio.de/xml"))
    except ET.ParseError as exc:
        raise FeedError(f"Personio '{ident}': not valid XML ({exc})")
    if root.tag != "workzag-jobs":
        raise FeedError(f"Personio '{ident}': unexpected root element '{root.tag}'")
    rows = []
    for pos in root.findall("position"):
        pid = (pos.findtext("id") or "").strip()
        parts = []
        for block in pos.findall("jobDescriptions/jobDescription"):
            name = (block.findtext("name") or "").strip()
            body = html_to_text(block.findtext("value"))
            parts.append(f"{name}\n{body}" if name else body)
        url = f"https://{ident}.jobs.personio.de/job/{pid}"
        rows.append(_row(
            "personio", entry, pid,
            title=(pos.findtext("name") or "").strip(),
            location=(pos.findtext("office") or "").strip(),
            job_url=url,
            apply_url=url,
            description="\n\n".join(p for p in parts if p),
            posted_date=_iso(pos.findtext("createdAt")),
            type=(pos.findtext("employmentType") or None),
        ))
    return rows


_SF_TRAILING_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")


def read_successfactors_rss(entry: dict, fetch: Fetch, keep: Optional[Callable] = None) -> list:
    """`identifier` is the careers host, e.g. 'careers.omv.com'. Without a keyword the feed holds only the
    newest 20 items, so `location_keyword` (e.g. 'Vienna') is passed as the search keyword."""
    host = entry["identifier"]
    keyword = entry.get("location_keyword", "")
    url = f"https://{host}/services/rss/job/?locale=en_US&keywords={quote_plus(keyword)}"
    try:
        root = ET.fromstring(fetch(url))
        channel = root.find("channel")
        items = channel.findall("item")
    except (ET.ParseError, AttributeError) as exc:
        raise FeedError(f"SuccessFactors feed '{host}': unexpected response ({exc})")
    rows, seen_links, seen_titles = [], set(), set()
    for item in items:
        link = (item.findtext("link") or "").strip().split("?")[0]  # drop the feed's tracking parameters
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        title = (item.findtext("title") or "").strip()
        location = ""
        m = _SF_TRAILING_PAREN.search(title)
        if m and "," in m.group(1):
            location, title = m.group(1).strip(), title[:m.start()].strip()
        # RBI lists each job twice under different ids (two language versions): keep the first.
        title_key = re.sub(r"\W+", " ", title).strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        native = re.search(r"/(\d{5,})/?$", link)
        native_id = native.group(1) if native else hashlib.sha1(link.encode()).hexdigest()[:12]
        rows.append(_row(
            "successfactors_rss", entry, native_id,
            title=title,
            location=location or keyword,
            job_url=link,
            apply_url=link,
            description=html_to_text(item.findtext("description")),
            posted_date=_iso(item.findtext("pubDate")),
        ))
    return rows


def read_smartrecruiters(entry: dict, fetch: Fetch, keep: Optional[Callable] = None) -> list:
    """The list call carries no ad text, so `keep(stub)` decides which postings are worth one detail call each."""
    ident = quote(entry["identifier"])
    stubs, offset = [], 0
    while True:
        try:
            page = json.loads(fetch(f"https://api.smartrecruiters.com/v1/companies/{ident}/postings?limit=100&offset={offset}"))
            content = page["content"]
            if not isinstance(content, list):
                raise TypeError("'content' is not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise FeedError(f"SmartRecruiters '{entry['identifier']}': unexpected response ({exc})")
        stubs.extend(content)
        offset += len(content)
        if not content or offset >= int(page.get("totalFound") or 0):
            break
    rows = []
    for stub in stubs:
        loc = stub.get("location") or {}
        location = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        if loc.get("remote"):
            location = f"{location} (Remote)".strip()
        candidate = {"title": stub.get("name") or "", "location": location}
        if keep and not keep(candidate):
            continue
        try:
            detail = json.loads(fetch(f"https://api.smartrecruiters.com/v1/companies/{ident}/postings/{quote(str(stub['id']))}"))
            sections = (detail.get("jobAd") or {}).get("sections") or {}
        except (ValueError, KeyError, TypeError) as exc:
            raise FeedError(f"SmartRecruiters '{entry['identifier']}' posting {stub.get('id')}: unexpected response ({exc})")
        text = "\n\n".join(
            f"{s.get('title', '')}\n{html_to_text(s.get('text'))}".strip() for s in sections.values() if s.get("text")
        )
        rows.append(_row(
            "smartrecruiters", entry, str(stub["id"]),
            title=candidate["title"].strip(),
            location=location,
            job_url=detail.get("postingUrl") or "",
            apply_url=detail.get("applyUrl") or detail.get("postingUrl") or None,
            description=text,
            posted_date=_iso(stub.get("releasedDate")),
            language=((stub.get("language") or {}).get("code")),
        ))
    return rows


READERS = {
    "greenhouse": read_greenhouse,
    "personio": read_personio,
    "successfactors_rss": read_successfactors_rss,
    "smartrecruiters": read_smartrecruiters,
}


# --- validation and filters -----------------------------------------------------------------------------------

def validate_rows(rows: Iterable[dict], label: str) -> tuple:
    """Split rows into (usable, problems) with the Posting gate's rules (postings.py), so a broken reader is
    reported per company; if a reader breaks, every row is reported and the company yields nothing."""
    good, problems = [], []
    for row in rows:
        _, reason = to_posting(row)
        if reason:
            problems.append(f"{label}: posting '{row.get('title') or row.get('id')}': {reason}")
        else:
            good.append(row)
    return good, problems


def _entry_filters(entry: dict, defaults: dict) -> dict:
    return {**defaults, **{k: v for k, v in entry.items() if k in (
        "location_pattern", "include_titles", "exclude_titles", "english_only", "max_age_days")}}


def matches_filters(row: dict, filters: dict, now: Optional[datetime] = None) -> bool:
    pattern = filters.get("location_pattern") or DEFAULT_LOCATION_PATTERN
    # A remote posting without a location passes; one with neither cannot be placed and fails.
    if not (row.get("remote") is True and not row.get("location")) and not re.search(pattern, row.get("location") or "", re.I):
        return False
    title = row.get("title") or ""
    include, exclude = filters.get("include_titles") or [], filters.get("exclude_titles") or []
    if include and not any(re.search(p, title, re.I) for p in include):
        return False
    if any(re.search(p, title, re.I) for p in exclude):
        return False
    if filters.get("english_only"):
        lang = (row.get("language") or "").lower()
        if lang and not lang.startswith("en"):
            return False
        if _GERMAN_TITLE_FORMS.search(title):
            return False
    max_age = filters.get("max_age_days")
    if max_age and row.get("posted_date"):
        posted = datetime.fromisoformat(row["posted_date"])
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        if posted < (now or datetime.now(timezone.utc)) - timedelta(days=int(max_age)):
            return False
    return True


# --- duplicates of jobs another source already stored ---------------------------------------------------------

def _norm(text) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").lower()).strip()


def _strip_query(url) -> str:
    return str(url or "").split("?")[0].rstrip("/")


def drop_known_elsewhere(rows: list, stored_jobs: Iterable[dict]) -> tuple:
    """Remove feed rows for jobs that LinkedIn, karriere.at etc. already stored.

    The scrape pipeline only recognises a repeat by job_url or id, and the same job has a different URL and id in a
    company feed. A row counts as already known when a stored job from another source has the same apply link, or
    the same title and a company name that equals or contains the feed company's name. Jobs from company feeds are
    left to the pipeline's own repeat detection. Returns (kept rows, number dropped)."""
    apply_urls, by_title = set(), {}
    for job in stored_jobs:
        if str(job.get("source") or "").startswith("Company feed"):
            continue
        if job.get("apply_url"):
            apply_urls.add(_strip_query(job["apply_url"]))
        by_title.setdefault(_norm(job.get("title")), set()).add(_norm(job.get("company")))
    kept = []
    for row in rows:
        company = _norm(row.get("company"))
        known = _strip_query(row.get("job_url")) in apply_urls or any(
            company and other and (company in other or other in company)
            for other in by_title.get(_norm(row.get("title")), ()))
        if not known:
            kept.append(row)
    return kept, len(rows) - len(kept)


# --- companies file and the run -------------------------------------------------------------------------------

def load_companies(username: Optional[str]) -> dict:
    """Read `profiles/<user>/companies.json`: {"filters": {...}, "companies": [{name, connector, identifier, ...}]}.
    A missing file means no companies. A malformed entry raises, so a typo is never silently ignored."""
    path = resolve_user_path(username, "companies.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"filters": {}, "companies": []}
    companies = data.get("companies") or []
    for i, entry in enumerate(companies):
        if entry.get("connector") not in READERS:
            raise FeedError(f"companies.json entry {i} ('{entry.get('name')}'): unknown connector '{entry.get('connector')}'")
        if not entry.get("identifier"):
            raise FeedError(f"companies.json entry {i} ('{entry.get('name')}'): no identifier")
    return {"filters": data.get("filters") or {}, "companies": companies}


def fetch_company_postings(config: dict, fetch: Optional[Fetch] = None,
                           log_fn: Optional[Callable] = None, now: Optional[datetime] = None) -> tuple:
    """Run every company in `config` and return (rows, errors). One company failing never stops the others."""
    fetch = fetch or http_fetch  # looked up now, so tests can replace it
    log_fn = log_fn or (lambda msg, level="info": logger.info(msg))
    defaults = config.get("filters") or {}
    rows, errors = [], []
    for entry in config.get("companies", []):
        if entry.get("enabled") is False:
            continue
        label = f"{entry.get('name') or entry['identifier']} [{entry['connector']}]"
        filters = _entry_filters(entry, defaults)
        try:
            found = READERS[entry["connector"]](
                entry, fetch, keep=lambda stub, f=filters: matches_filters(stub, f, now))
            found, problems = validate_rows(found, label)
            for problem in problems:
                errors.append(problem)
                log_fn(f"Company feed {problem}", "error")
        except FeedError as exc:
            errors.append(str(exc))
            log_fn(f"Company feed {label} failed: {exc}", "error")
            continue
        except Exception as exc:  # network errors and anything a reader did not anticipate
            errors.append(f"{label}: {exc}")
            log_fn(f"Company feed {label} failed: {exc}", "error")
            continue
        kept = [r for r in found if matches_filters(r, filters, now)]
        log_fn(f"Company feed {label}: {len(found)} open, {len(kept)} after filters.", "info")
        rows.extend(kept)
    return rows, errors
