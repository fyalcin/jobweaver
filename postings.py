"""Postings: the one shape every Source's records take before they are stored (ADR-0006, GLOSSARY.md).

A Connector fetches raw records from a Source; a Mapping turns each one into a dict with the field names below;
`gate` then checks it. A record that has every required field becomes a Posting: text trimmed, dates as ISO
strings, HTML turned into text, and every field the schema does not name dropped. The rest become Rejected
records, each with its Source and the reason. Bad optional values (an unreadable date, a salary that is not a
number) become empty; they never cost a Posting.

This module is the plug-in contract for new Sources: produce dicts with these fields and pass them through
`gate`.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

from bs4 import BeautifulSoup

# `id` is Jobweaver's ID for the posting, built from the Source and the Source's own ID (for example
# "li_4012345678"). It must be stable: the same posting seen again must get the same ID.
REQUIRED = ("id", "source", "job_url", "title", "company", "description")
TEXT_FIELDS = ("location", "apply_type", "type", "salary", "language", "company_feed")
URL_FIELDS = ("apply_url",)
DATE_FIELDS = ("posted_date",)
FIELDS = REQUIRED + TEXT_FIELDS + URL_FIELDS + DATE_FIELDS + ("salary_yearly", "remote")

SHORT_DESCRIPTION = 300   # characters; shorter texts are often cut off by the Source
MAX_EXAMPLES = 5          # Rejected records named in a run's log line
CHANGED_SHAPE_SHARE = 0.2  # above this share of rejections, the Source has probably changed its fields

_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def html_to_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("- ")
    text = soup.get_text("\n")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _text(value) -> Optional[str]:
    if _missing(value):
        return None
    text = str(value).strip()
    return text or None


def _url(value) -> Optional[str]:
    text = _text(value)
    return text if text and re.match(r"https?://[^\s/]+", text, re.I) else None


def iso_date(value) -> Optional[str]:
    """An ISO date or date-time string, or None when the value cannot be read as one."""
    if _missing(value) or value == "":
        return None
    if isinstance(value, (datetime, date)):  # also pandas Timestamps
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _salary_number(value) -> Optional[int]:
    if _missing(value) or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return round(number) if math.isfinite(number) and number > 0 else None


def to_posting(record: dict) -> tuple:
    """Return (posting, None), or (None, reason) when the record cannot become a Posting."""
    posting = {}
    for name in REQUIRED:
        posting[name] = _url(record.get(name)) if name == "job_url" else _text(record.get(name))
    missing = [name for name in REQUIRED if not posting[name]]
    if missing:
        return None, "missing or invalid " + ", ".join(missing)

    if _TAG.search(posting["description"]):
        posting["description"] = html_to_text(posting["description"])
        if not posting["description"]:
            return None, "missing or invalid description"

    for name in TEXT_FIELDS:
        posting[name] = _text(record.get(name))
    for name in URL_FIELDS:
        posting[name] = _url(record.get(name))
    for name in DATE_FIELDS:
        posting[name] = iso_date(record.get(name))
    posting["salary_yearly"] = _salary_number(record.get("salary_yearly"))
    remote = record.get("remote")
    posting["remote"] = remote if isinstance(remote, bool) else None
    return {k: v for k, v in posting.items() if v is not None}, None


@dataclass
class GateResult:
    source: str
    postings: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    short_descriptions: int = 0

    @property
    def total(self) -> int:
        return len(self.postings) + len(self.rejected)

    def summary(self) -> Optional[tuple]:
        """(log level, message) for the run log, or None when every record became a Posting."""
        if not self.rejected:
            return None
        reasons = Counter(r["reason"] for r in self.rejected)
        examples = "; ".join(f"'{r['title'] or r['id'] or '?'}' {r['job_url'] or ''}".strip()
                             for r in self.rejected[:MAX_EXAMPLES])
        message = (f"{self.source}: rejected {len(self.rejected)} of {self.total} record(s) ("
                   + ", ".join(f"{n}× {reason}" for reason, n in reasons.most_common())
                   + f"). Examples: {examples}.")
        if len(self.rejected) / self.total > CHANGED_SHAPE_SHARE:
            return "error", message + " So many rejections usually mean the Source changed its fields; check its Mapping."
        return "warning", message


def gate(records: Iterable[dict], source: str) -> GateResult:
    """Check every record from one Source run; see the module docstring."""
    result = GateResult(source=source)
    for record in records:
        posting, reason = to_posting(record)
        if posting is None:
            result.rejected.append({
                "source": source,
                "reason": reason,
                "id": _text(record.get("id")),
                "title": _text(record.get("title")),
                "job_url": _text(record.get("job_url")),
            })
            continue
        if len(posting["description"]) < SHORT_DESCRIPTION:
            result.short_descriptions += 1
        result.postings.append(posting)
    return result
