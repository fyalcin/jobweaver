#!/usr/bin/env python3
"""Mark one job as applied from the command line, without the HTTP API.

    uv run python mark_applied.py --user admin --job li_4474888661 [--date 2026-10-12] [--method email]

For scripts and agents that submit applications elsewhere and record them here. Sets the same fields as the web app's status change:
`status` "applied", `applied` true and `application_date` (default today), plus
`application_method` when given. A job that is already further along (interview, offer, rejected)
keeps its status and only gets `applied` set; a job already marked applied is left unchanged, so
repeated runs do nothing.

Standard output carries exactly one JSON object:

    {"job_id", "changed", "previous_status", "status", "errors": [...]}

Exit code 0 when the job is marked (or already was); 2 for an unknown user or job or a bad date.
"""
import argparse
import json
import sys
from datetime import date

# Statuses that come after applying; marking applied must not move a job back from them.
AFTER_APPLIED = {"applied", "interview", "offer", "rejected"}


def mark_applied(username: str, job_id: str, applied_on: str, method: str | None = None) -> dict:
    import db

    result = {"job_id": job_id, "changed": False, "previous_status": None, "status": None, "errors": []}
    user = db.get_user_by_username(username)
    if not user:
        result["errors"].append(f"unknown user: {username}")
        return result
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        result["errors"].append(f"unknown job for {username}: {job_id}")
        return result
    status = job.get("status") or "new"
    result["previous_status"] = result["status"] = status
    fields = {}
    if status not in AFTER_APPLIED:
        fields["status"] = result["status"] = "applied"
    if not job.get("applied"):
        fields["applied"] = True
    if fields and not job.get("application_date"):
        fields["application_date"] = applied_on
    if fields and method and not job.get("application_method"):
        fields["application_method"] = method
    if fields:
        db.update_job_fields(job_id, user_id=user["id"], **fields)
        result["changed"] = True
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--date", default=date.today().isoformat(), help="application date, YYYY-MM-DD")
    ap.add_argument("--method", default=None, help="stored as application_method if none is set")
    a = ap.parse_args(argv)
    try:
        date.fromisoformat(a.date)
    except ValueError:
        print(json.dumps({"job_id": a.job, "changed": False, "previous_status": None, "status": None,
                          "errors": [f"bad date: {a.date}"]}))
        return 2
    result = mark_applied(a.user, a.job, a.date, a.method)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
