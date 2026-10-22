import os
from job_policy import qualifies, fingerprint
import sys
import json
import logging
import argparse
import shutil
from datetime import datetime
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import db
import demo_mode
from scrapers import scrape_new_jobs, ScrapeParams, retry_failed_analyses
from generators import write_latex, compile_latex, resolve_scrape_model
from cv_profiles import select_cv_profile, normalize_profile
from german import german_level_compatible, normalize_german_level
from user_assets import resolve_user_path, user_outputs_dir, user_drafts_dir, ensure_user_dirs, load_effective_cv, user_profile_dir
from dotenv import load_dotenv

load_dotenv()


def load_config(username: str | None = None) -> dict:
    cfg_path = resolve_user_path(username, "scraper_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _document_engine(username: str | None, config: dict) -> str:
    """Engine for automatic documents: LaTeX until the reviewed baseline is acknowledged, then the user's choice."""
    from pathlib import Path
    approved = Path(user_profile_dir(username), 'approved', 'cv.tex').exists()
    auto = config.get('auto_generate', {})
    return 'latex' if approved and not auto.get('reviewed_baseline_ack') else auto.get('document_engine', 'typst')


def _job_folder(job: dict) -> tuple:
    """(safe_id, company slug, folder name) under which a job's drafts and outputs live."""
    import re
    safe_id = str(job.get('id', '')).replace(':', '_').replace(' ', '_')
    company = re.sub(r'[^\w\-.]', '', str(job.get('company', 'Unknown')).replace(' ', '').replace('/', '_')) or 'Unknown'
    return safe_id, company, f'{company}_{safe_id}'


def _generate_docs_for_job(job: dict, model_name: str, tone: str, cv_text: str, user: dict, cv_profile: str | None = None, compact: bool | None = None, atomic: bool = False, notes: list | None = None, language: str | None = None) -> dict:
    """Generate the CV and cover letter of one job through the reviewed pipeline.

    Incremental mode (atomic=False): each document is published as soon as it is built, so a failed letter
    leaves the new CV published. Command line (atomic=True): nothing is published unless both
    documents were built and verified; on any failure the revision folders made by this call are
    removed, so `publication.json` and the last good documents stay as they were.
    `notes` collects the letter attempts the checker rejected on the way. Returns success, files
    (published PDFs, in build order), errors, and `built`: details per document kind.
    """
    from pathlib import Path
    import uuid
    import json
    from document_artifacts import atomic_write, document_lock, matching_build, select_source
    from reviewed_documents import generate
    from generators import run_ai_prompt, compile_typst
    username = user.get('username')
    config = load_config(username)
    auto = config.get('auto_generate', {})
    engine = _document_engine(username, config)
    compact = auto.get('compact_cv', False) if compact is None else compact
    selection = select_cv_profile(job, normalize_profile(cv_profile or job.get('cv_profile_override'), username), user=username)
    safe_id, company, folder_name = _job_folder(job)
    draft = Path(user_drafts_dir(username), folder_name)
    output = Path(user_outputs_dir(username), folder_name)
    files, errors, built, created = [], [], {}, []

    def publish(entries):
        publication = output / 'publication.json'
        previous = json.loads(publication.read_text()) if publication.exists() else {}
        for entry in entries:
            previous[entry['url_key']] = entry['url']
            previous['revision'] = entry['revision']
        atomic_write(publication, json.dumps(previous))

    with document_lock(draft):
        for kind, prefix in (('cv', 'cv'), ('letter', 'cl')):
            try:
                source = generate(job, cv_text, username, engine, kind, selection['profile'], model_name, run_ai_prompt, tone=tone, compact=compact and kind == 'cv', notes=notes, language=language)
                filename = f'{prefix}_{safe_id}.' + ('tex' if engine == 'latex' else 'typ')
                atomic_write(draft / filename, source)
                select_source(draft, prefix, safe_id, 'tex' if engine == 'latex' else 'typ')
                atomic_write(draft / 'history' / (__import__('document_artifacts').digest(source) + '.' + engine), source)
                pdfname = f'{prefix}_draft_{safe_id}.pdf'
                published_name = f'CV-{company}.pdf' if kind == 'cv' else f'Letter-{company}.pdf'
                if engine == 'latex':
                    ok, message = compile_latex(str(draft), filename, pdfname, str(draft),
                        resource_dir=resolve_user_path(username, 'base-cv-tex' if kind == 'cv' else 'base-cl-tex'))
                else:
                    ok, message = compile_typst(str(draft), filename, pdfname, str(draft))
                manifest = matching_build(draft / pdfname, source)
                if not ok or not manifest:
                    raise ValueError(message or 'Build did not match source')
                revision = uuid.uuid4().hex
                bundle = output / 'revisions' / revision
                bundle.mkdir(parents=True)
                created.append(bundle)
                shutil.copy2(draft / filename, bundle / filename)
                shutil.copy2(draft / pdfname, bundle / published_name)
                atomic_write(bundle / 'manifest.json', json.dumps({kind: manifest}))
                entry = {
                    'kind': kind, 'revision': revision, 'bundle': str(bundle), 'pdf': str(bundle / published_name),
                    'published_name': published_name, 'source_file': filename, 'manifest': manifest, 'engine': engine,
                    'url_key': 'cv_url' if kind == 'cv' else 'letter_url',
                    'url': f'/api/download/{folder_name}/revisions/{revision}/{published_name}',
                }
                built[kind] = entry
                if not atomic:
                    publish([entry])
                files.append(str(bundle / published_name))
            except Exception as exc:
                errors.append(f'{kind}: {exc}')
                logger.error('Document generation failed: %s', exc)
        if atomic:
            if errors:
                for bundle in created:
                    shutil.rmtree(bundle, ignore_errors=True)
                files, built = [], {}
            else:
                publish(list(built.values()))
    return {'success': not errors, 'files': files, 'errors': errors, 'built': built, 'engine': engine,
            'folder': folder_name, 'output_dir': str(output)}


def run_daily_scraping(linkedin_limit: int = None, karriere_limit: int = None,
                       keywords: str = None, source_tag: str = None, user_filter: str = None) -> None:
    """Run the scrape → analyse pipeline; documents are generated on request.

    ``keywords``/``source_tag`` turn this into a PROBE run: LinkedIn is queried with different
    keywords and its rows are stored under a distinct source label, while the other Sources are
    skipped, so the probe sample stays comparable to the main lane and does not pollute it.
    """
    if demo_mode.enabled():
        logger.error(demo_mode.MESSAGE)
        return
    logger.info("Starting daily job scraping routine.")
    users = db.list_users()
    if user_filter:
        # Probe runs target one user: scraping every household profile for a market sample
        # doubles the Apify spend and mixes rows that should stay comparable.
        users = [u for u in users if str(u.get("username")) == user_filter]
        if not users:
            logger.error(f"No user named {user_filter!r} — aborting.")
            return
    if not users:
        logger.error("No users found — run manage_users.py to create one.")
        return
    for user in users:
        try:
            _run_daily_for_user(user, linkedin_limit, karriere_limit,
                                keywords=keywords, source_tag=source_tag)
        except Exception as e:
            logger.exception(f"Daily scraping failed for user '{user.get('username')}': {e}")


def _run_daily_for_user(user: dict, linkedin_limit: int = None, karriere_limit: int = None,
                        keywords: str = None, source_tag: str = None) -> None:
    username = user.get("username")
    user_id = user["id"]
    logger.info(f"=== Daily routine for user '{username}' ===")
    config = load_config(username)
    today = datetime.now().strftime("%Y-%m-%d")

    # Scoring/analysis only — this model is passed to every scrape_new_jobs call below.
    # Document generation uses the user's `document_model` (see generators.resolve_document_model).
    model_name = resolve_scrape_model(config)

    auto_cfg = config.get("auto_generate", {})
    min_score = auto_cfg.get("min_match_score", 65)
    max_german_level = auto_cfg.get("max_german_level", "B1")
    tone = auto_cfg.get("tone", "professional")

    daily_cfg = config.get("daily_scraper", {})
    # Apify Sources cost money and need APIFY_API_TOKEN, so each is off until the user's config turns it on.
    enable_linkedin = daily_cfg.get("enable_linkedin", False)
    enable_karriere = daily_cfg.get("enable_karriere", False)
    li_cfg = daily_cfg.get("linkedin", {})
    ka_cfg = daily_cfg.get("karriere", {})

    if linkedin_limit is None:
        # Budget default: ~$0.05/day/user at $2/1,000 Apify listings
        # (~$1.55/user/month, keeping the household cron inside ~$4/month
        # together with the incremental Karriere actor).
        linkedin_limit = li_cfg.get("results_limit", 25)
    if karriere_limit is None:
        karriere_limit = ka_cfg.get("results_limit", 10)

    cv_text = load_effective_cv(username)
    if not cv_text:
        logger.error("CV-plaintext.txt not found or empty — match scores won't be calculated and doc generation will be skipped.")

    scrape_user = {"id": user_id, "username": username}

    # 1. LinkedIn (via Apify)
    probe = bool(keywords)
    if probe:
        # Probe mode: one source, one keyword set, distinguishable rows.
        enable_linkedin, enable_karriere = True, False
        logger.info(f"PROBE mode: LinkedIn only, keywords={keywords!r}, source_tag={source_tag!r}")
    if enable_linkedin:
        li_keywords = keywords or li_cfg.get("keywords", "python OR backend developer")
        logger.info(f"Scraping LinkedIn via Apify (limit: {linkedin_limit})…")
        scrape_new_jobs(ScrapeParams(
            results_limit=linkedin_limit,
            hours_old=li_cfg.get("hours_old", 24),
            distance=li_cfg.get("distance", 10),
            keywords=li_keywords,
            source="linkedin-apify",
            label=f"{source_tag} [{username}]" if source_tag else None,
        ), cv_text=cv_text, model_name=model_name or "z-ai/glm-5.3-flash", user=scrape_user)
    else:
        logger.info("LinkedIn scraping is disabled in config.")

    # 2. karriere.at through the blackfalcondata Apify actor (incremental, age-filtered, structured salary)
    if enable_karriere:
        karriere_source = "karriere-apify"
        karriere_keywords = ka_cfg.get("keywords", ["python", "backend developer"])
        for kw in karriere_keywords:
            logger.info(f"Scraping Karriere.at [{karriere_source}] for '{kw}' (limit: {karriere_limit})…")
            scrape_new_jobs(ScrapeParams(
                results_limit=karriere_limit,
                hours_old=ka_cfg.get("hours_old", 24),
                distance=ka_cfg.get("distance", 10),
                keywords=kw,
                source=karriere_source,
            ), cv_text=cv_text, model_name=model_name or "z-ai/glm-5.3-flash", user=scrape_user)
    else:
        logger.info("Karriere.at scraping is disabled in config.")

    # 3b. Extra lanes: other keywords with a small total limit, rows tagged with the lane name, e.g.
    #     daily_scraper.lanes = [{"name": "bridge", "source": "karriere-apify",
    #                             "keywords": ["Kundenservice Türkisch", ...], "results_limit": 10}]
    #     results_limit is the lane's total per day, split across its keywords.
    for lane in ([] if probe else daily_cfg.get("lanes", [])):
        lane_keywords = lane.get("keywords") or []
        if isinstance(lane_keywords, str):
            lane_keywords = [lane_keywords]
        if not lane.get("name") or not lane_keywords:
            logger.warning(f"Skipping lane without name or keywords: {lane!r}")
            continue
        per_keyword = max(1, int(lane.get("results_limit", 10)) // len(lane_keywords))
        for kw in lane_keywords:
            logger.info(f"Lane '{lane['name']}' [{lane.get('source', 'karriere-apify')}]: '{kw}' (limit: {per_keyword})…")
            scrape_new_jobs(ScrapeParams(
                results_limit=per_keyword,
                hours_old=lane.get("hours_old", 24),
                distance=lane.get("distance", 10),
                keywords=kw,
                source=lane.get("source", "karriere-apify"),
                lane=lane["name"],
            ), cv_text=cv_text, model_name=model_name or "z-ai/glm-5.3-flash", user=scrape_user)

    # 3c. Company job feeds (profiles/<user>/companies.json): the employers' own published feeds, no Apify cost.
    #     Off unless daily_scraper.company_feeds.enabled is true; the first run imports every open posting that
    #     passes the filters, later runs only add new ones.
    if not probe and daily_cfg.get("company_feeds", {}).get("enabled", False):
        logger.info("Scraping company job feeds…")
        scrape_new_jobs(ScrapeParams(source="company-feeds", keywords="company feeds"),
                        cv_text=cv_text, model_name=model_name or "z-ai/glm-5.3-flash", user=scrape_user)

    # 4. Retry analyses that failed recently. Without this, failures from
    #    earlier days stayed in the "pending AI analysis" queue indefinitely.
    if cv_text and not probe:
        retried_ok, retried_failed = retry_failed_analyses(scrape_user, cv_text, model_name or "z-ai/glm-5.3-flash")
        if retried_ok or retried_failed:
            logger.info(f"Retried failed analyses: {retried_ok} succeeded, {retried_failed} still failing.")

    # 5. Auto-generate documents for high-scoring jobs
    jobs_today_df = db.load_jobs_by_date(user_id, today)
    if jobs_today_df.empty:
        logger.info("No new jobs scraped today.")
        return

    jobs_today_df = jobs_today_df.astype(object).where(pd.notna(jobs_today_df), None)
    jobs = jobs_today_df.to_dict(orient="records")
    logger.info(f"Found {len(jobs)} jobs scraped today. Collecting jobs above score {min_score} "
                f"for the daily results (document generation is on request, not here).")

    if not cv_text:
        logger.error("CV-plaintext.txt missing — skipping document generation.")
        return


    qualifying_jobs = []
    for job in jobs:
        score = job.get("match_score")
        try:
            score_val = int(score) if score is not None else 0
        except (ValueError, TypeError):
            continue

        if not qualifies(job, config, fingerprint(cv_text, model_name or "z-ai/glm-5.3-flash")):
            continue

        logger.info(f"Qualifying job found: {job.get('title')} @ {job.get('company')} (score {score_val})")
        qualifying_jobs.append(job)

    logger.info("Daily scrape complete: %s qualifying jobs.", len(qualifying_jobs))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Job Scraper")
    parser.add_argument("--linkedin-limit", type=int, default=None)
    parser.add_argument("--karriere-limit", type=int, default=None)
    parser.add_argument("--keywords", default=None,
                        help="PROBE run: override the LinkedIn keyword query (skips the other Sources)")
    parser.add_argument("--user", default=None, help="PROBE run: restrict to one username")
    parser.add_argument("--source-tag", default=None,
                        help="PROBE run: value stored in the rows' source column (e.g. 'AI probe (LinkedIn)') so "
                             "probe rows are distinguishable from the main lane")
    args = parser.parse_args()
    run_daily_scraping(args.linkedin_limit, args.karriere_limit,
                       keywords=args.keywords, source_tag=args.source_tag, user_filter=args.user)
