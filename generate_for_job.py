#!/usr/bin/env python3
"""Generate one job's CV and cover letter from the command line, without the HTTP API.

    uv run python generate_for_job.py --user admin --job li_4474888661 [--force]

Runs the same reviewed pipeline as the other document requests (approved fact IDs, fresh build,
parsed-PDF validation, immutable output bundles) through `daily_scraper._generate_docs_for_job`,
with the engine and the documents model from the user's settings. It makes the model calls that
generation makes and no other network calls: none for the CV (every approved bullet is kept; one in
compact mode), and for the letter a fact plan, then one to three rounds of writing and verification
(the verifier is `letter_verifier_model`, by default another model family than the writer).
`plan` lists each planned fact with the posting need it answers and its allowed framing; `warnings`
lists rejected plan and letter attempts.

Standard output carries exactly one JSON object and nothing else (logs go to standard error):

    {"job_id", "ok", "cached", "cv_pdf", "letter_pdf",          absolute paths in the output bundle
     "cv_download_name", "letter_download_name",                  e.g. Alex_Muster_CV.pdf
     "revision", "engine", "model", "letter_date",
     "validation": [...], "warnings": [...], "plan": [...], "errors": [...],
     "regenerated_because": null | "..."}

Exit code 0 only if both documents are built and verified (or a verified current bundle was
returned); 1 if generation failed; 2 if the request cannot be run (unknown user or job, missing CV,
bad arguments). A failed run publishes nothing and leaves the last good documents active.

A job's bundle is reused (`cached: true`, no model call) while its recorded inputs still match: the
CV text, the approved CV, the career record, claim policy, document instructions, model, verifier, pipeline version,
engine, tone, CV profile and the job's text, and while the letter's date is still today. `--force` rebuilds regardless.
"""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

GENERATION_FILE = "generation.json"
SCHEMA = 1


def _today() -> str:
    return date.today().isoformat()


def fingerprint(job: dict, username: str, config: dict, cv_text: str, model: str, tone: str,
                compact: bool, engine: str, profile: str) -> dict:
    """What the generated documents depend on. Changing any part makes an older bundle stale."""
    import reviewed_documents
    from document_artifacts import digest
    from user_assets import user_profile_dir

    approved = Path(user_profile_dir(username), "approved", "cv.tex")
    policy = Path(user_profile_dir(username), "claim_policy.json")
    instructions = config.get("document_instructions", {})
    posting = {
        "title": str(job.get("title") or ""), "company": str(job.get("company") or ""),
        "company_contact": str(job.get("company_contact") or ""),
        "description": str(job.get("description") or "")[:6000],
        "language": reviewed_documents.letter_language(job),
        "research": str(job.get("company_research") or "")[:2000]
                    if job.get("use_research_in_docs", True) is not False else "",
    }
    parts = {
        "pipeline": reviewed_documents.PIPELINE_VERSION, "verifier": reviewed_documents.verifier_model(username),
        "model": model, "engine": engine, "tone": tone, "compact": bool(compact), "profile": profile,
        "cv_text": digest(cv_text)[:16],
        "approved_cv": digest(approved.read_bytes())[:16] if approved.exists() else None,
        "claim_policy": digest(policy.read_bytes())[:16] if policy.exists() else None,
        "career_record": digest(reviewed_documents.career_record_for(username)[1] or "")[:16],
        "instructions": digest(json.dumps(instructions, sort_keys=True, ensure_ascii=False))[:16],
        "job": digest(json.dumps(posting, sort_keys=True, ensure_ascii=False))[:16],
    }
    return {"digest": digest(json.dumps(parts, sort_keys=True)), "parts": parts}


def pdf_pages(path) -> int | None:
    result = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=10)
    found = re.search(r"^Pages:\s+(\d+)", result.stdout.decode("utf-8", "replace"), re.M)
    return int(found.group(1)) if found else None


def verify_current(output: Path, record: dict, inputs_digest: str, today: str) -> str | None:
    """None if the stored bundle is still the current, intact result; otherwise the reason it is not."""
    from document_artifacts import digest, validate_pdf

    if record.get("schema") != SCHEMA:
        return "stored record has an unknown format"
    if record.get("inputs_digest") != inputs_digest:
        return "inputs changed (CV, model, engine, instructions or job text)"
    if record.get("letter_date") != today:
        return f"the letter is dated {record.get('letter_date')}, not today"
    try:
        publication = json.loads((output / "publication.json").read_text())
        for kind, key in (("cv", "cv_url"), ("letter", "letter_url")):
            entry = record[kind]
            if f"/revisions/{entry['revision']}/" not in publication.get(key, ""):
                return f"the {kind} was republished since (another run or the web app)"
            bundle = output / "revisions" / entry["revision"]
            manifest = json.loads((bundle / "manifest.json").read_text())[kind]
            if digest((bundle / entry["source_file"]).read_text()) != manifest["source_hash"]:
                return f"the {kind} source no longer matches its build"
            if validate_pdf(bundle / entry["published_name"]) != manifest["pdf_hash"]:
                return f"the {kind} PDF no longer matches its build"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return f"stored bundle failed verification ({type(exc).__name__}: {exc})"
    return None


@contextmanager
def job_lock(path: Path):
    """One run per job at a time across processes; a second caller waits, then finds the bundle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _result(job_id: str, ok: bool, **fields) -> dict:
    base = {"job_id": job_id, "ok": ok, "cached": False, "cv_pdf": None, "letter_pdf": None,
            "cv_download_name": None, "letter_download_name": None, "revision": None, "engine": None,
            "model": None, "letter_date": None, "validation": [], "warnings": [], "plan": [], "errors": [],
            "regenerated_because": None}
    base.update(fields)
    return base


def _success(job_id, output, record, cached, cv_text, username, reason=None) -> dict:
    import reviewed_documents

    validation = []
    for kind, label in (("cv", "CV"), ("letter", "Cover letter")):
        entry = record[kind]
        pdf = output / "revisions" / entry["revision"] / entry["published_name"]
        pages = pdf_pages(pdf)
        validation.append(f"{label}: PDF parsed ({pages} page{'s' if pages != 1 else ''}), "
                          f"build verified against its {record['engine']} source")
    return _result(
        job_id, True, cached=cached,
        cv_pdf=str(output / "revisions" / record["cv"]["revision"] / record["cv"]["published_name"]),
        letter_pdf=str(output / "revisions" / record["letter"]["revision"] / record["letter"]["published_name"]),
        cv_download_name=reviewed_documents.download_name(username, record["cv"]["published_name"], cv_text),
        letter_download_name=reviewed_documents.download_name(username, record["letter"]["published_name"], cv_text),
        revision=record["letter"]["revision"], engine=record["engine"], model=record["inputs"]["model"],
        letter_date=record["letter_date"], validation=validation, warnings=list(record.get("warnings", [])),
        plan=list(record.get("plan", [])),
        regenerated_because=reason)


def run(username: str, job_id: str, force: bool = False, language: str | None = None) -> tuple[dict, int]:
    """Return (result dict, exit code)."""
    import db
    from daily_scraper import _document_engine, _generate_docs_for_job, _job_folder, load_config
    from cv_profiles import normalize_profile, select_cv_profile
    import reviewed_documents
    from document_artifacts import atomic_write, digest
    from generators import resolve_document_model
    from user_assets import resolve_user_path, user_drafts_dir, user_outputs_dir

    user = db.get_user_by_username(username)
    if not user:
        return _result(job_id, False, errors=[f"unknown user: {username}"]), 2
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        return _result(job_id, False, errors=[f"job not found for {username}: {job_id}"]), 2
    config = load_config(username)
    auto = config.get("auto_generate", {})
    model, tone, compact = resolve_document_model(config), auto.get("tone", "professional"), bool(auto.get("compact_cv", False))
    from user_assets import load_effective_cv
    cv_text = load_effective_cv(username)  # from the career record when the user has one
    if not cv_text.strip():
        return _result(job_id, False, errors=["CV-plaintext.txt not found or empty; cannot generate documents"]), 2

    engine = _document_engine(username, config)
    profile = select_cv_profile(job, normalize_profile(job.get("cv_profile_override"), username), user=username)["profile"]
    _, _, folder = _job_folder(job)
    output = Path(user_outputs_dir(username), folder)
    inputs = fingerprint(job, username, config, cv_text, model, tone, compact, engine, profile)
    inputs["parts"]["language"] = reviewed_documents.document_language(
        username, job, language, bool(reviewed_documents.career_record_for(username)[0]))
    inputs["digest"] = digest(json.dumps(inputs["parts"], sort_keys=True))
    today, reason = _today(), None

    with job_lock(Path(user_drafts_dir(username), folder, ".generate.lock")):
        stored = output / GENERATION_FILE
        if stored.exists() and not force:
            try:
                record = json.loads(stored.read_text())
            except (OSError, ValueError):
                record, reason = None, "stored record is unreadable"
            else:
                reason = verify_current(output, record, inputs["digest"], today)
                if reason is None:
                    return _success(job_id, output, record, True, cv_text, username), 0
        elif force:
            reason = "--force"

        notes = []
        outcome = _generate_docs_for_job(job, model_name=model, tone=tone, cv_text=cv_text, user=user,
                                         compact=compact, atomic=True, notes=notes, language=inputs["parts"]["language"])
        plan = [note.removeprefix("plan: ") for note in notes if note.startswith("plan: ")]
        notes = [note for note in notes if not note.startswith("plan: ")]
        if not outcome["success"]:
            return _result(job_id, False, engine=outcome["engine"], model=model, warnings=notes, plan=plan,
                           errors=outcome["errors"], regenerated_because=reason), 1
        record = {"schema": SCHEMA, "inputs_digest": inputs["digest"], "inputs": inputs["parts"],
                  "letter_date": today, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "engine": outcome["engine"], "warnings": notes, "plan": plan}
        for kind in ("cv", "letter"):
            built = outcome["built"][kind]
            record[kind] = {"revision": built["revision"], "published_name": built["published_name"],
                            "source_file": built["source_file"]}
        atomic_write(stored, json.dumps(record, ensure_ascii=False, indent=1))
        return _success(job_id, output, record, False, cv_text, username, reason), 0


class _JsonParser(argparse.ArgumentParser):
    """Bad arguments still produce the one JSON object on stdout (exit code 2)."""

    def error(self, message):
        print(json.dumps(_result(None, False, errors=[f"usage: {message}"])))
        sys.exit(2)


def main(argv=None) -> int:
    parser = _JsonParser(description="Generate one job's CV and cover letter (see the module docstring).")
    parser.add_argument("--user", required=True, help="Jobweaver username, e.g. admin")
    parser.add_argument("--job", required=True, help="job id, e.g. li_4474888661")
    parser.add_argument("--force", action="store_true", help="rebuild even if a current bundle exists")
    parser.add_argument("--language", choices=("en", "de"), help="document language (default: the user's setting, "
                        "English for career-record users)")
    args = parser.parse_args(argv)

    # Anything a library prints must not corrupt the JSON: send stdout to stderr until the end.
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        result, code = run(args.user, args.job, args.force, args.language)
    except Exception as exc:  # last resort: still one JSON object, non-zero exit
        result, code = _result(args.job, False, errors=[f"{type(exc).__name__}: {exc}"]), 1
    finally:
        sys.stdout = real_stdout
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
