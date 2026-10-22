"""Read-only demo mode (JOBWEAVER_DEMO=1): visitors look around a fictional applicant's job search.

The server refuses every request that would change data, except signing in and out and the visitor's own UI
preferences. As a second layer, model calls and scrapes refuse to run, so a demo can never cost money or contact
job sites. `make demo` seeds a fresh copy of the demo data and starts the app this way.
"""
import os
import json
from pathlib import Path

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"
MESSAGE = "This is a read-only demo. Install Jobweaver to add jobs, score them and write documents."
WRITABLE_REQUESTS = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout")}


def enabled() -> bool:
    return os.environ.get("JOBWEAVER_DEMO", "").strip() == "1"


def allows(method: str, path: str) -> bool:
    """True when demo mode permits this request."""
    return method.upper() in ("GET", "HEAD", "OPTIONS") or (method.upper(), path.rstrip("/")) in WRITABLE_REQUESTS


def documents(folder: Path, folder_name: str) -> dict:
    """Read prepared demo documents without compiling PDFs or creating files."""
    result = {"success": True, "ai_versions": {"cv": [], "letter": []}}
    for prefix, kind, key in (("cv", "cv", "cv"), ("cl", "letter", "cl")):
        source = folder / f"{prefix}.tex"
        pdf = folder / f"{prefix}.pdf"
        result.update({f"has_{kind}": pdf.is_file(), f"{key}_tex": source.read_text() if source.is_file() else "",
                       f"{key}_engine": "latex", f"{key}_pdf_current": pdf.is_file(),
                       f"{key}_images": [f"/api/download/draft/{folder_name}/{p.name}"
                                          for p in sorted(folder.glob(f"{prefix}-*.png"))],
                       f"{key}_download_url": f"/api/download/draft/{folder_name}/{prefix}.pdf" if pdf.is_file() else None})
    evidence = folder / "evidence.json"
    result["demo_evidence"] = json.loads(evidence.read_text()) if evidence.is_file() else None
    return result


class DemoModeError(RuntimeError):
    """Raised by code paths that cost money or contact other sites."""

    def __init__(self):
        super().__init__(MESSAGE)


def refuse_if_enabled() -> None:
    if enabled():
        raise DemoModeError()
