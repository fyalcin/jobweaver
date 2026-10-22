"""Mapping for any job page that embeds schema.org JobPosting JSON-LD (most career sites and job boards do).

`find_job_postings` returns the JobPosting objects in a page; `to_job` maps one to the Posting fields
(postings.py). Pages without a block, or with a broken one, give an empty list; callers then fall back to
reading the page text. https://developers.google.com/search/docs/appearance/structured-data/job-posting
"""
import json
from typing import Optional

from bs4 import BeautifulSoup

from postings import html_to_text, iso_date
from salary import salary_yearly_eur


def _is_job_posting(node) -> bool:
    kind = node.get("@type") if isinstance(node, dict) else None
    return kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        if _is_job_posting(node):
            yield node
        elif "@graph" in node:
            yield from _walk(node["@graph"])


def find_job_postings(html: str) -> list:
    found = []
    for script in BeautifulSoup(html or "", "html.parser").find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text(), strict=False)
        except ValueError:
            continue
        found.extend(_walk(data))
    return found


def _str(value) -> Optional[str]:
    return value.strip() or None if isinstance(value, str) else None


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _company(org) -> Optional[str]:
    org = _first(org)
    return _str(org.get("name")) if isinstance(org, dict) else _str(org)


def _location(places) -> Optional[str]:
    """Places joined with "; ". A place that names only a country is dropped when another names a town."""
    names, country_only = [], []
    for place in places if isinstance(places, list) else [places]:
        address = place.get("address") if isinstance(place, dict) else None
        address = _first(address)
        if isinstance(address, dict):
            parts = [_str(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
            country = address.get("addressCountry")
            if isinstance(country, dict):
                parts[2] = _str(country.get("name"))
            text = ", ".join(dict.fromkeys(p for p in parts if p))
            if text and not (parts[0] or parts[1]):
                country_only.append(text)
        else:
            text = _str(address) or (_str(place) if isinstance(place, str) else None)
        if text and text not in names:
            names.append(text)
    if len(country_only) < len(names):
        names = [n for n in names if n not in country_only]
    return "; ".join(names) or None


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number > 0 else None


def _salary(base) -> tuple:
    """(salary text, yearly EUR or None) from a MonetaryAmount."""
    base = _first(base)
    if not isinstance(base, dict):
        return None, None
    value = base.get("value")
    currency = _str(base.get("currency")) or ""
    unit = None
    if isinstance(value, dict):
        unit = _str(value.get("unitText"))
        low = _number(value.get("minValue")) or _number(value.get("value"))
        high = _number(value.get("maxValue"))
    else:
        low, high = _number(value), None
    if low is None:
        return None, None
    amounts = " – ".join(f"{v:,.0f}" for v in [low] + ([high] if high and high != low else []))
    text = f"{amounts} {currency}".strip() + (f" per {unit.lower()}" if unit else "")
    yearly = salary_yearly_eur(low, unit.lower() if unit else None) if currency.upper() == "EUR" else None
    return text, yearly


def to_job(node: dict) -> dict:
    """Map one JobPosting object to Posting fields; fields the page does not give are left out."""
    types = node.get("employmentType")
    types = [t for t in (types if isinstance(types, list) else [types]) if isinstance(t, str) and t.strip()]
    salary, yearly = _salary(node.get("baseSalary"))
    location_type = node.get("jobLocationType")
    remote = "TELECOMMUTE" in (location_type if isinstance(location_type, list) else [location_type])
    description = node.get("description")
    job = {
        "title": _str(node.get("title")),
        "company": _company(node.get("hiringOrganization")),
        "description": html_to_text(description) if isinstance(description, str) else None,
        "location": _location(node.get("jobLocation")) if node.get("jobLocation") else None,
        "posted_date": iso_date(node.get("datePosted")),
        "type": ", ".join(types) or None,
        "salary": salary,
        "salary_yearly": yearly,
        "remote": True if remote else None,
        "apply_url": _str(node.get("url")),
    }
    return {k: v for k, v in job.items() if v is not None}
