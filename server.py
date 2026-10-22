import os
import re
import unicodedata
import math
import collections
import mimetypes
import shutil
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from fastapi import FastAPI, HTTPException, BackgroundTasks, Body, Query, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationError
from typing import Optional, List, Any, Union, Literal
from dotenv import load_dotenv
from datetime import datetime
import json
import uuid
import base64
from pathlib import Path
from document_artifacts import (atomic_write, decode_pdf, digest, document_lock, active_source, select_source,
                                matching_build, record_build)
from job_policy import eligibility, qualifies, fingerprint
import reviewed_documents

# Local imports
import db
import auth
import demo_mode
import user_assets
from user_assets import (
    resolve_user_path,
    user_outputs_dir,
    user_drafts_dir,
    user_documents_dir,
    user_profile_dir,
    ensure_user_dirs,
    load_effective_cv,
    load_standing_notes,
)
from german import german_level_compatible, normalize_german_level
import scrapers as _scrapers
from generators import (
    write_latex,
    compile_latex, compile_latex_diff, refine_document_with_feedback,
    convert_pdf_to_images, apply_route_cheapest, research_company_sonar,
    resolve_document_model, resolve_scrape_model, list_custom_models,
    compile_studio_document, parse_pdflatex_error, ai_surgical_edit_latex,
    compile_typst, parse_typst_error, ai_surgical_edit_typst,
)
from cv_profiles import available_profiles, normalize_profile, profile_label, select_cv_profile

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration & Setup ---
load_dotenv()


# Initialise SQLite DB (creates tables + migrates JSON on first run)
db.init_db()
db.async_task_recover_interrupted()


# --- Authentication ---

def get_current_user(request: Request) -> dict:
    """FastAPI dependency: resolve the logged-in user from the session cookie."""
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    user_id = auth.verify_session_token(token)
    user = db.get_user_by_id(user_id) if user_id else None
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


class LoginRequest(BaseModel):
    username: str
    password: str


def load_user_config_dict(user: Optional[dict] = None) -> dict:
    """Read the user's scraper_config.json as a plain dict ({} when absent or malformed).

    Single reader for the model-resolution helpers below.
    """
    cfg_path = resolve_user_path(user.get("username") if user else None, "scraper_config.json")
    if not os.path.exists(cfg_path):
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_generation_config(user: Optional[dict] = None) -> tuple[str, str]:
    """Return (openrouter_model, tone) as a tuple, from the user's config."""
    cfg = load_user_config_dict(user)
    return cfg.get("openrouter_model", ""), cfg.get("auto_generate", {}).get("tone", "")


def load_document_engine_config(user: Optional[dict] = None) -> tuple[str, str]:
    """Return (document_engine, typst_template) from the user's config. Defaults to ('typst', 'base-cv-moderner.typ')."""
    cfg_path = resolve_user_path(user.get("username") if user else None, "scraper_config.json")
    approved = os.path.join(user_profile_dir(user.get('username') if user else None), 'approved', 'cv.tex')
    default_engine = "latex" if os.path.exists(approved) else "typst"
    default_template = "base-cv-moderner.typ"
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            auto_gen = cfg.get("auto_generate", {})
            engine = (default_engine if os.path.exists(approved) and not auto_gen.get("reviewed_baseline_ack")
                      else auto_gen.get("document_engine", default_engine))
            template = auto_gen.get("typst_cv_template", default_template)
            return engine, template
        except Exception:
            pass
    return default_engine, default_template


def route_cheapest_enabled(user: Optional[dict] = None) -> bool:
    """Read the user's `route_cheapest` config flag (default off)."""
    cfg_path = resolve_user_path(user.get("username") if user else None, "scraper_config.json")
    if not os.path.exists(cfg_path):
        return False
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("route_cheapest", False))
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def _effective_ai_model(explicit_model: Optional[str] = None, user: Optional[dict] = None,
                        purpose: str = "document") -> str:
    """Resolve the model for ONE call.

    purpose="document" (default) -> the user's `document_model`  (CVs, letters, refinements, edits)
    purpose="scrape"             -> the user's `openrouter_model` (scoring every scraped posting)

    An explicit model chosen for the request always wins, so the UI can still override per call.
    The two roles are separate keys because their volumes differ by ~25x, and mixing them is how
    a letter-quality tweak ends up repricing the daily scrape.
    """
    if explicit_model:
        return apply_route_cheapest(explicit_model, route_cheapest_enabled(user))
    cfg = load_user_config_dict(user)
    if purpose == "scrape":
        return resolve_scrape_model(cfg)
    return resolve_document_model(cfg)


def _rename_doc_folders_if_company_changed(job_id: str, old_company: str, new_company: str, username: str) -> None:
    """Rename the user's drafts/ and outputs/ subfolders when the job company name changes."""
    if (old_company or "") == (new_company or ""):
        return
    job_id_safe = str(job_id).replace(":", "_").replace(" ", "_")
    old_safe = _make_company_safe(old_company or "Unknown")
    new_safe = _make_company_safe(new_company or "Unknown")
    old_key = f"{old_safe}_{job_id_safe}"
    new_key = f"{new_safe}_{job_id_safe}"
    if old_key == new_key:
        return
    for sub_fn in (user_drafts_dir, user_outputs_dir):
        old_path = os.path.join(sub_fn(username), old_key)
        new_path = os.path.join(sub_fn(username), new_key)
        if not os.path.isdir(old_path):
            continue
        if os.path.isdir(new_path):
            for name in os.listdir(old_path):
                src = os.path.join(old_path, name)
                dst = os.path.join(new_path, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
            shutil.rmtree(old_path)
            logger.info("Merged %s/%s into existing %s", sub_fn(username), old_key, new_key)
        else:
            os.rename(old_path, new_path)
            logger.info("Renamed %s/%s → %s", sub_fn(username), old_key, new_key)


# Parallel analyses for "Process Now". Five ran an 8 GB machine out of memory in a long queue (10.2026).
REPROCESS_WORKERS = 2


def _run_reprocess_bg(task_id: str, user: dict) -> None:
    user_id = user["id"]
    jobs = db.load_unprocessed_jobs(user_id)
    total = len(jobs)
    db.async_task_update(task_id, total=total, processed=0, failed=0)

    if total == 0:
        db.async_task_update(task_id, status="completed")
        return

    cv_text = load_cv_text(user.get("username"))
    model_name = _effective_ai_model(None, user, purpose="scrape")

    # Model calls take 15-25 s each (outliers >100 s); run several at once like
    # the scrape does. Cancellation is checked before each job starts.
    counts = {"processed": 0, "failed": 0, "cancelled": False}
    lock = threading.Lock()

    def _one(job):
        st = db.async_task_get_reprocess(task_id, user_id)
        if st and st.get("cancelled"):
            with lock:
                counts["cancelled"] = True
            return
        ok, err = _scrapers.analyse_stored_job(job, user, cv_text, model_name)
        with lock:
            if ok:
                counts["processed"] += 1
            else:
                logger.error(f"Reprocess failed for job {job.get('id', '')}: {err}")
                counts["failed"] += 1
            db.async_task_update(task_id, processed=counts["processed"], failed=counts["failed"])

    with ThreadPoolExecutor(max_workers=REPROCESS_WORKERS) as pool:
        list(pool.map(_one, jobs))

    failed_count = counts["failed"]
    final_status = "cancelled" if counts["cancelled"] else "failed" if failed_count == total else "completed"
    db.async_task_update(
        task_id,
        status=final_status,
        processed=counts["processed"],
        failed=failed_count,
    )


app = FastAPI(title="Job Scraper API")

# Enable CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Same-origin via Vite proxy / static mount
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def demo_mode_guard(request: Request, call_next):
    """In demo mode, refuse every request that would change data (demo_mode.py)."""
    if demo_mode.enabled() and not demo_mode.allows(request.method, request.url.path):
        return JSONResponse(status_code=403, content={"detail": demo_mode.MESSAGE})
    return await call_next(request)


@app.get("/api/demo")
def demo_status():
    """Public: whether this instance is the read-only demo, and its sign-in (shown on the login screen)."""
    if not demo_mode.enabled():
        return {"demo": False}
    return {"demo": True, "username": demo_mode.DEMO_USERNAME, "password": demo_mode.DEMO_PASSWORD,
            "message": demo_mode.MESSAGE}

# --- Auth Endpoints ---

@app.post("/api/auth/login")
def api_auth_login(req: LoginRequest, response: Response):
    user = db.get_user_by_username(req.username)
    if not user or not auth.verify_password(req.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = auth.create_session_token(user["id"])
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # LAN-only deployment; set True behind HTTPS
    )
    ensure_user_dirs(user["username"])
    return {"success": True, "username": user["username"], "display_name": user["display_name"]}


@app.post("/api/auth/logout")
def api_auth_logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return {"success": True}


@app.get("/api/auth/me")
def api_auth_me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "display_name": user["display_name"]}

# --- Pydantic Models ---
class ScrapeRequest(BaseModel):
    keywords: str
    results_limit: int = 100
    hours_old: int = 48
    distance: int = 10
    source: str = "linkedin-apify" # or "karriere"
    modelName: Optional[str] = None  # None -> the user's configured model for this purpose
    tone: Optional[str] = ""

class ManualJobRequest(BaseModel):
    job_url: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    save_to_db: bool = True
    modelName: Optional[str] = None  # None -> the user's configured model for this purpose
    tone: Optional[str] = ""
    cv_profile_override: Optional[str] = None
    compact: Optional[bool] = False

class JobUpdateRequest(BaseModel):
    status: Optional[str] = None
    application_date: Optional[str] = None
    application_method: Optional[str] = None
    response_status: Optional[str] = None
    company_contact: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    cv_profile_override: Optional[str] = None
    company_research: Optional[str] = None
    company_research_updated_at: Optional[str] = None
    use_research_in_docs: Optional[bool] = None

class JobResearchRequest(BaseModel):
    model_name: Optional[str] = None

class GenerateRequest(BaseModel):
    job_id: str
    modelName: Optional[str] = None  # None -> the user's configured model for this purpose
    tone: Optional[str] = ""
    cv_profile: Optional[str] = None
    compact: Optional[bool] = None
    engine: Optional[str] = None
    language: Optional[str] = None  # 'en' or 'de'; None -> the user's setting (English for career-record users)


class BatchGenerateRequest(BaseModel):
    job_ids: List[str]
    modelName: Optional[str] = None
    tone: Optional[str] = None
    force: Optional[bool] = False
    cv_profile: Optional[str] = None
    compact: Optional[bool] = None
    engine: Optional[str] = None

    @field_validator("job_ids")
    @classmethod
    def _validate_job_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("job_ids must not be empty")
        if len(v) > 300:
            raise ValueError("At most 300 jobs per batch")
        return v


class RefineIterateRequest(BaseModel):
    job_id: str
    document_type: str # 'cv' or 'letter'
    current_tex: str
    feedback: str
    modelName: Optional[str] = None  # None -> the user's configured model for this purpose
    tone: Optional[str] = ""

class RefineFinalizeRequest(BaseModel):
    job_id: str
    cv_tex: str
    letter_tex: str


def _deep_merge_dict(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out

class LinkedinScraperConfig(BaseModel):
    keywords: str = ""
    results_limit: int = Field(default=80, ge=1, le=500)
    hours_old: int = Field(default=24, ge=1, le=720)
    distance: int = Field(default=10, ge=1, le=200)


class KarriereScraperConfig(BaseModel):
    keywords: Union[List[str], str] = Field(default_factory=list)
    results_limit: int = Field(default=10, ge=1, le=200)
    hours_old: Optional[int] = Field(default=24, ge=1, le=720)
    distance: Optional[int] = Field(default=10, ge=1, le=200)

    @field_validator("keywords", mode="before")
    @classmethod
    def coerce_keywords(cls, v: Any):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return []


class AutoGenerateConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    min_match_score: int = Field(default=65, ge=0, le=100)
    max_german_level: str = Field(default="B1", max_length=20)
    tone: str = Field(default="", max_length=20000)
    document_engine: Literal["latex", "typst"] = "typst"
    typst_cv_template: str = Field(default="base-cv-moderner.typ", pattern=r"^[\w-]+\.typ$")
    compact_cv: bool = False


class DocumentInstructions(BaseModel):
    """Per-user extra instructions injected into document generation prompts."""
    model_config = ConfigDict(extra="allow")
    cv: str = Field(default="", max_length=4000)
    cover_letter: str = Field(default="", max_length=4000)


class ScraperConfigPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    openrouter_model: str = Field(default="", max_length=200)
    document_model: str = Field(default="", max_length=200)
    linkedin: LinkedinScraperConfig = Field(default_factory=LinkedinScraperConfig)
    karriere: KarriereScraperConfig = Field(default_factory=KarriereScraperConfig)
    auto_generate: AutoGenerateConfig = Field(default_factory=AutoGenerateConfig)
    document_instructions: DocumentInstructions = Field(default_factory=DocumentInstructions)
    linkedin_location: str = Field(default="", max_length=200)
    karriere_region: str = Field(default="", max_length=200)
    denoise_sources: List[str] = Field(default_factory=lambda: list(_scrapers.DEFAULT_DENOISE_SOURCES))
    route_cheapest: bool = False

    @field_validator("denoise_sources")
    @classmethod
    def _validate_denoise_sources(cls, v: List[str]) -> List[str]:
        allowed = {"linkedin", "karriere", "manual"}
        seen: List[str] = []
        for item in v or []:
            key = str(item).strip().lower()
            if key in allowed and key not in seen:
                seen.append(key)
        return seen


def _resolved_safe_path(relative_path: str, root_dir: str) -> str:
    """Resolve relative path and ensure it stays under root_dir (no path traversal)."""
    root_abs = os.path.abspath(root_dir)
    candidate = os.path.abspath(os.path.join(root_abs, relative_path))
    if not candidate.startswith(root_abs + os.sep) and candidate != root_abs:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


# --- Storage helpers (thin delegates to db module) ---
def get_logs(user_id: int) -> list:
    return db.get_logs(user_id)

def add_log(msg: str, level: str = "info", user_id: Optional[int] = None):
    db.add_log(msg, level, user_id)

def load_db(user_id: int) -> pd.DataFrame:
    return db.load_processed_jobs(user_id, is_one_off=False)

def load_all_jobs(user_id: int) -> pd.DataFrame:
    return db.load_all_jobs(user_id)

def load_cv_text(username: Optional[str] = None) -> str:
    return load_effective_cv(username)

def _make_company_safe(company: str) -> str:
    """Normalise a company name into a filesystem-safe slug.

    Strips spaces, replaces '/' with '_', then removes every character that
    isn't alphanumeric, a hyphen, an underscore, or a dot.  This prevents
    characters like '"' from ending up in file/directory names where they would
    be treated differently by pdflatex (which silently strips them from
    -jobname), causing a mismatch between the expected and actual PDF path.
    """
    s = str(company).replace(" ", "").replace("/", "_")
    s = re.sub(r'[^\w\-.]', '', s)
    return s or "Unknown"


def _outputs_has_cv_pdf(job: dict, user: dict) -> bool:
    username = user.get("username")
    job_id_safe = str(job.get("id", "")).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    path = os.path.join(user_outputs_dir(username), folder_name, f"CV-{company_safe}.pdf")
    publication = os.path.join(os.path.dirname(path), 'publication.json')
    if os.path.isfile(publication):
        with open(publication) as stream:
            return bool(json.load(stream).get('cv_url'))
    return os.path.isfile(path)


def _outputs_has_letter_pdf(job: dict, user: dict) -> bool:
    username = user.get("username")
    job_id_safe = str(job.get("id", "")).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    path = os.path.join(user_outputs_dir(username), folder_name, f"Letter-{company_safe}.pdf")
    publication = os.path.join(os.path.dirname(path), 'publication.json')
    if os.path.isfile(publication):
        with open(publication) as stream:
            return bool(json.load(stream).get('letter_url'))
    return os.path.isfile(path)


def _get_ai_versions(draft_dir: str) -> dict:
    version_file = os.path.join(draft_dir, "ai_versions.json")
    if os.path.exists(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "cv": data.get("cv", []),
                        "letter": data.get("letter", [])
                    }
        except Exception as e:
            logger.warning(f"Failed to read ai_versions.json in {draft_dir}: {e}")
    return {"cv": [], "letter": []}


def _save_ai_versions(draft_dir: str, versions: dict):
    version_file = os.path.join(draft_dir, "ai_versions.json")
    try:
        atomic_write(version_file, json.dumps(versions, indent=2))
    except Exception as e:
        logger.warning(f"Failed to write ai_versions.json in {draft_dir}: {e}")


def _record_initial_document_version(draft_dir: str, doc_type: str, tex: str, engine: str):
    """Snapshot the pristine generated document as Original Draft if no versions exist yet."""
    with document_lock(draft_dir):
        if not tex or not tex.strip():
            return
        versions = _get_ai_versions(draft_dir)
        doc_versions = versions.get(doc_type, [])
        if not any(version.get("tex") == tex for version in doc_versions):
            now_ts = int(time.time() * 1000)
            now_dt = datetime.fromtimestamp(now_ts / 1000.0)
            base_snapshot = {
                "id": uuid.uuid4().hex,
                "timestamp": now_ts,
                "date_str": now_dt.strftime("%d.%m %H:%M"),
                "instruction": "Original generated document",
                "label": "Original Draft",
                "tex": tex,
                "engine": engine,
            }
            versions[doc_type] = [*doc_versions, base_snapshot]
            _save_ai_versions(draft_dir, versions)


def _try_generate_cv_pdf(job_id: str, model_name: str, tone: str, user: dict, cv_profile: Optional[str] = None, compact: Optional[bool] = None, engine: Optional[str] = None, language: Optional[str] = None) -> Optional[str]:
    username = user.get('username')
    job = db.get_job_by_id(job_id, user['id'])
    if not job:
        return 'Job not found'
    cv = load_cv_text(username)
    selected_engine = engine or load_document_engine_config(user)[0]
    compact = load_user_config_dict(user).get('auto_generate', {}).get('compact_cv', False) if compact is None else compact
    profile = select_cv_profile(job, normalize_profile(cv_profile or job.get("cv_profile_override"), username), user=username)['profile']
    try:
        from generators import run_ai_prompt
        source = reviewed_documents.generate(job, cv, username, selected_engine, 'cv', profile, model_name, run_ai_prompt, tone=tone, compact=compact, language=language)
        result = compile_job_document(job_id, JobDocCompileRequest(document_type='cv', tex=source), user=user)
        if not result['success']:
            return result.get('error', 'Compilation failed')
        safe_id = str(job_id).replace(':', '_').replace(' ', '_')
        folder = os.path.join(user_drafts_dir(username), f"{_make_company_safe(job.get('company', 'Unknown'))}_{safe_id}")
        _record_initial_document_version(folder, 'cv', source, selected_engine)
        finalize_job_documents(job_id, JobDocFinalizeRequest(document_type='cv', cv_source=source), user=user)
        return None
    except (ValueError, OSError, HTTPException) as exc:
        return str(getattr(exc, 'detail', exc))


def _try_generate_letter_pdf(job_id: str, model_name: str, tone: str, user: dict, engine: Optional[str] = None, language: Optional[str] = None) -> Optional[str]:
    username = user.get('username')
    job = db.get_job_by_id(job_id, user['id'])
    if not job:
        return 'Job not found'
    cv = load_cv_text(username)
    selected_engine = engine or load_document_engine_config(user)[0]
    profile = select_cv_profile(job, normalize_profile(job.get("cv_profile_override"), username), user=username)['profile']
    try:
        from generators import run_ai_prompt
        source = reviewed_documents.generate(job, cv, username, selected_engine, 'letter', profile, model_name, run_ai_prompt, tone=tone, language=language)
        result = compile_job_document(job_id, JobDocCompileRequest(document_type='letter', tex=source), user=user)
        if not result['success']:
            return result.get('error', 'Compilation failed')
        safe_id = str(job_id).replace(':', '_').replace(' ', '_')
        folder = os.path.join(user_drafts_dir(username), f"{_make_company_safe(job.get('company', 'Unknown'))}_{safe_id}")
        _record_initial_document_version(folder, 'letter', source, selected_engine)
        finalize_job_documents(job_id, JobDocFinalizeRequest(document_type='letter', letter_source=source), user=user)
        return None
    except (ValueError, OSError, HTTPException) as exc:
        return str(getattr(exc, 'detail', exc))


def _run_batch_generate_bg(task_id: str, job_ids: List[str], model_name: str, tone: str, user: dict, force: bool = False, cv_profile: Optional[str] = None, compact: Optional[bool] = None, engine: Optional[str] = None) -> None:
    total = len(job_ids)
    db.async_task_update(task_id, total=total, processed=0, failed=0)
    cv_text = load_cv_text(user.get("username"))
    if not cv_text:
        db.async_task_update(
            task_id,
            status="failed",
            result={"success": False, "message": "No CV text (career record or CV-plaintext.txt) found"},
        )
        return

    processed_ok = 0
    failed_count = 0
    cancelled_mid = False
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    update_lock = threading.Lock()

    def _process_single(jid: str):
        st = db.async_task_get_batch_generate(task_id, user["id"])
        if st and st.get("cancelled"):
            return "cancelled"
        job = db.get_job_by_id(jid, user["id"])
        if not job:
            return "failed"
        job_failed = False
        if force or not _outputs_has_cv_pdf(job, user):
            try:
                err = _try_generate_cv_pdf(jid, model_name, tone, user, cv_profile, compact=compact, engine=engine)
            except Exception as exc:
                err = f"Unexpected error: {exc}"
            if err:
                logger.error("Batch CV gen failed for %s: %s", jid, err)
                job_failed = True
        if not job_failed and (force or not _outputs_has_letter_pdf(job, user)):
            try:
                err = _try_generate_letter_pdf(jid, model_name, tone, user, engine=engine)
            except Exception as exc:
                err = f"Unexpected error: {exc}"
            if err:
                logger.error("Batch letter gen failed for %s: %s", jid, err)
                job_failed = True
        return "failed" if job_failed else "ok"

    try:
        max_workers = 5
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_jid = {executor.submit(_process_single, jid): jid for jid in job_ids}
            for future in as_completed(future_to_jid):
                res = future.result()
                with update_lock:
                    if res == "cancelled":
                        cancelled_mid = True
                        break
                    elif res == "failed":
                        failed_count += 1
                    else:
                        processed_ok += 1
                    db.async_task_update(task_id, processed=processed_ok, failed=failed_count)
    except Exception as exc:
        logger.exception("Batch generate task %s crashed: %s", task_id, exc)
        db.async_task_update(
            task_id,
            status="failed",
            processed=processed_ok,
            failed=failed_count,
            result={"success": False, "message": f"Task crashed: {exc}"},
        )
        return

    final_status = "cancelled" if cancelled_mid else "failed" if failed_count == total else "completed"
    db.async_task_update(
        task_id,
        status=final_status,
        processed=processed_ok,
        failed=failed_count,
        result={
            "success": failed_count == 0 and not cancelled_mid,
            "state": 'cancelled' if cancelled_mid else 'partial' if failed_count else 'complete',
            "message": f"Batch done: {processed_ok} ok, {failed_count} failed.",
            "processed": processed_ok,
            "failed": failed_count,
        },
    )


def process_job_with_ai(description: str, cv_text: Optional[str] = None, model_name: Optional[str] = None, user: Optional[dict] = None, denoise: bool = True) -> dict:
    """Analyze a job description via the configured AI model."""
    m = _effective_ai_model(model_name, user, purpose="scrape")
    try:
        return _scrapers.process_job_with_ai(description, cv_text, model_name=m, denoise=denoise)
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        return {
            "analysis_state": "failed",
            "analysis_error": str(e),
            "german_level": "unknown",
            "requires_german": True,
            "salary": "Error",
            "salary_yearly": None,
            "skills": "Error",
            "summary": "Error",
            "match_score": None
        }

# --- API Endpoints ---

@app.get("/api/jobs")
def get_jobs(user: dict = Depends(get_current_user)):
    username = user.get("username")
    df = load_db(user["id"])
    if df.empty:
        return []
    df = df.astype(object).where(pd.notna(df), None)

    outputs_root = user_outputs_dir(username)

    # Scan the user's outputs/ once and build a lookup: folder_name → {cv_url, letter_url}
    outputs_map: dict[str, dict] = {}
    if os.path.isdir(outputs_root):
        for folder_name in os.listdir(outputs_root):
            out_dir = os.path.join(outputs_root, folder_name)
            if not os.path.isdir(out_dir):
                continue
            for fname in os.listdir(out_dir):
                fpath = os.path.join(out_dir, fname)
                mtime = int(os.path.getmtime(fpath))
                if fname.startswith("CV-") and fname.endswith(".pdf"):
                    outputs_map.setdefault(folder_name, {})["cv_url"] = f"/api/download/{folder_name}/{fname}?v={mtime}"
                elif fname.startswith("Letter-") and fname.endswith(".pdf"):
                    outputs_map.setdefault(folder_name, {})["letter_url"] = f"/api/download/{folder_name}/{fname}?v={mtime}"

    jobs = df.to_dict(orient="records")
    policy_config = load_user_config_dict(user)
    default_engine = load_document_engine_config(user)[0]
    expected_analysis = fingerprint(load_cv_text(username), _effective_ai_model(None, user, purpose='scrape'))
    for job in jobs:
        job['default_document_engine'] = default_engine
        job['eligibility'] = eligibility(job, policy_config)
        job['analysis_current'] = (job['analysis_fingerprint'] == expected_analysis) if job.get('analysis_fingerprint') else None
        job['qualifies'] = qualifies(job, policy_config, expected_analysis)
        job_id_safe = str(job.get("id", "")).replace(":", "_").replace(" ", "_")
        company_safe = _make_company_safe(job.get("company", "Unknown"))
        folder_key = f"{company_safe}_{job_id_safe}"
        urls = outputs_map.get(folder_key, {})
        publication = os.path.join(outputs_root, folder_key, 'publication.json')
        if os.path.exists(publication):
            with open(publication) as stream:
                saved = json.load(stream)
            urls.update({key: value for key, value in saved.items() if key in ('cv_url', 'letter_url') and value})
        job["cv_url"] = urls.get("cv_url")
        job["letter_url"] = urls.get("letter_url")

    return jobs


SUMMARY_FIELDS = ("id", "title", "company", "location", "status", "match_score", "analysis_current",
                  "date_scraped", "cv_url", "letter_url")


@app.get("/api/jobs/summaries")
def get_job_summaries(user: dict = Depends(get_current_user)):
    """The Jobs list without texts and analyses (about 1/40 of its size): what the MCP server's list and
    pipeline tools need. Read-only."""
    summaries = []
    for job in get_jobs(user=user):
        item = {key: job.get(key) for key in SUMMARY_FIELDS}
        state = job.get("eligibility")
        item["eligibility"] = {"state": state.get("state")} if isinstance(state, dict) else None
        summaries.append(item)
    return summaries

def scrape_new_jobs_sync(req: ScrapeRequest, user: dict, log_fn=None, async_task_id: Optional[str] = None):
    """
    Thin wrapper around scrapers.scrape_new_jobs.
    Kept for backward compatibility with daily_scraper.py.
    """
    params = _scrapers.ScrapeParams(
        results_limit=req.results_limit,
        hours_old=req.hours_old,
        distance=req.distance,
        keywords=req.keywords,
        source=req.source,
    )
    cv_text = load_cv_text(user.get("username"))
    model_name = _effective_ai_model(None, user, purpose="scrape")
    return _scrapers.scrape_new_jobs(
        params,
        log_fn=log_fn,
        cv_text=cv_text,

        model_name=model_name,
        async_task_id=async_task_id,
        user=user,
    )


def _run_scrape_bg(task_id: str, req: ScrapeRequest, user: dict):
    user_id = user["id"]
    def task_logger(msg: str, level: str = "info"):
        db.add_log(msg, level, user_id=user_id)
        db.async_task_append_log(
            task_id,
            {
                "timestamp": datetime.now().isoformat(),
                "message": msg,
                "level": level,
            },
        )

    try:
        res = scrape_new_jobs_sync(req, user, log_fn=task_logger, async_task_id=task_id)
        db.async_task_update(task_id, status="completed" if res.get("success") else "failed", result=res)
    except Exception as e:
        task_logger(f"Fatal scrape error: {e}", "error")
        db.async_task_update(
            task_id,
            status="failed",
            result={"success": False, "message": str(e)},
        )

@app.post("/api/scrape")
def api_scrape_start(req: ScrapeRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    db.async_task_prune_completed(3600)
    task_id = str(uuid.uuid4())
    db.async_task_create(task_id, "scrape", payload=req.model_dump(), user_id=user["id"])
    background_tasks.add_task(_run_scrape_bg, task_id, req, user)
    return {"success": True, "task_id": task_id}

@app.get("/api/scrape/status/{task_id}")
def api_scrape_status(task_id: str, user: dict = Depends(get_current_user)):
    row = db.async_task_get_scrape(task_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@app.get("/api/scrape/active")
def api_scrape_active(user: dict = Depends(get_current_user)):
    """Return the most recently started running scrape task, if any."""
    got = db.async_task_get_latest_running_scrape(user["id"])
    if not got:
        return {"active": False, "task_id": None}
    tid, task = got
    return {"active": True, "task_id": tid, **task}


# --- Reprocess endpoints ---

def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so payloads parse in browsers.

    Python's json emits bare NaN/Inf, but JSON.parse rejects them — job blobs
    can legitimately contain NaN floats (e.g. date_posted), so dict-returning
    endpoints sanitize before responding.
    """
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


@app.get("/api/jobs/unprocessed")
def get_unprocessed_jobs(user: dict = Depends(get_current_user)):
    jobs = db.load_unprocessed_jobs(user["id"])
    return {"count": len(jobs), "jobs": _sanitize_for_json(jobs)}


@app.post("/api/reprocess")
def api_reprocess_start(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user), all_scored: bool = False):
    if all_scored:
        for job in db.load_all_jobs(user['id']).to_dict(orient='records'):
            db.update_job_fields(job['id'], user_id=user['id'], processed=0, analysis_state='pending')
    count = db.get_unprocessed_count(user["id"])
    if count == 0:
        return {"success": True, "message": "No unprocessed jobs found.", "task_id": None}

    db.async_task_cancel_running_reprocess(user["id"])

    task_id = str(uuid.uuid4())
    db.async_task_create(task_id, "reprocess", total=count, user_id=user["id"])
    background_tasks.add_task(_run_reprocess_bg, task_id, user)
    return {"success": True, "task_id": task_id, "total": count}


@app.get("/api/reprocess/status/{task_id}")
def api_reprocess_status(task_id: str, user: dict = Depends(get_current_user)):
    row = db.async_task_get_reprocess(task_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@app.get("/api/reprocess/active")
def api_reprocess_active(user: dict = Depends(get_current_user)):
    """Return the most recently started running reprocess task, if any."""
    got = db.async_task_get_latest_running_reprocess(user["id"])
    if not got:
        return {"active": False, "task_id": None}
    tid, task = got
    return {"active": True, "task_id": tid, **task}


@app.get("/api/logs")
def fetch_logs(user: dict = Depends(get_current_user)):
    return db.get_logs(user["id"])


@app.get("/api/config")
def get_config(user: dict = Depends(get_current_user)):
    cfg_path = resolve_user_path(user.get("username"), "scraper_config.json")
    if not os.path.exists(cfg_path):
        raise HTTPException(status_code=404, detail="scraper_config.json not found")
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    approved = Path(user_profile_dir(user.get('username')), 'approved', 'cv.tex').exists()
    if approved:
        config.setdefault('auto_generate', {})['document_engine'] = load_document_engine_config(user)[0]
        config['auto_generate']['reviewed_baseline'] = True
    return config

@app.get("/api/openrouter/models")
def get_openrouter_models():
    """Models for the Settings dropdowns: OpenRouter's list, then `custom/…` models. One source
    being unreachable (for example no internet with a local model server) never hides the others."""
    if demo_mode.enabled():
        return {"success": True, "models": [{"id": "demo/prepared-example", "name": "Prepared demo examples"}]}
    import urllib.request
    models, error = [], None
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            models = [{"id": m["id"], "name": m["name"], "context_length": m.get("context_length")} for m in data.get("data", [])]
    except Exception as e:
        logger.error(f"Failed to fetch OpenRouter models: {e}")
        error = str(e)
    models += list_custom_models()
    return {"success": bool(models), "models": models, **({"error": error} if error and not models else {})}

@app.put("/api/config")
def save_config(body: dict = Body(...), user: dict = Depends(get_current_user)):
    # Writes always go to the user's own profile config (created on first
    # save); the root scraper_config.json is a user-agnostic base template
    # and is never modified by saves (see _user_asset_save_path).
    cfg_path = _user_asset_save_path(user.get("username"), "scraper_config.json")
    if os.path.dirname(cfg_path):
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    existing: dict = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Existing scraper_config.json is not valid JSON")
    merged = _deep_merge_dict(existing, body)
    try:
        validated = ScraperConfigPayload.model_validate(merged)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    out = validated.model_dump(mode="json", exclude_none=True)
    out['auto_generate'].pop('reviewed_baseline', None)
    if Path(user_profile_dir(user.get('username')), 'approved', 'cv.tex').exists() and 'document_engine' in body.get('auto_generate', {}):
        out['auto_generate']['reviewed_baseline_ack'] = True
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return {"success": True}


class CvTextPayload(BaseModel):
    content: str = Field(..., max_length=1_000_000)

class ProfileNotesPayload(BaseModel):
    notes: str = Field(..., max_length=1_000_000)


def _display_path(path: str) -> str:
    """Repo-root-relative path for showing in the UI."""
    return os.path.relpath(path, user_assets.BASE_DIR)


def _user_asset_save_path(username: Optional[str], relative: str) -> str:
    """File a user's edits to a root-fallback asset are written to.

    All repo-root asset files (CV-plaintext.txt, base-cv-tex/, base-cl-tex/,
    scraper_config.json, cv_profiles.py) are user-agnostic placeholder/base
    templates safe to commit. Reads fall back to them via
    `resolve_user_path`, but EVERY user's edits — default user included —
    go to `profiles/<user>/<relative>` (created on first save), so personal
    data never lands in the shared root files.
    """
    return os.path.join(user_profile_dir(username), relative)


@app.get("/api/cv")
def get_cv(user: dict = Depends(get_current_user)):
    username = user.get("username")
    import career_record
    record_path = career_record.path_for_user(username)
    if record_path:  # ADR-0004: the text comes from the career record and is edited there
        record, _ = career_record.for_user(username)
        return {"content": career_record.scoring_text(record), "exists": True, "read_only": True,
                "loaded_from": f"career record ({record_path.name})", "save_path": None}
    cv_path = resolve_user_path(username, "CV-plaintext.txt")
    content = ""
    exists = os.path.exists(cv_path)
    if exists:
        with open(cv_path, "r", encoding="utf-8") as f:
            content = f.read()
    return {
        "content": content,
        "exists": exists,
        "loaded_from": _display_path(cv_path),
        "save_path": _display_path(_user_asset_save_path(username, "CV-plaintext.txt")),
    }


@app.put("/api/cv")
def save_cv(body: CvTextPayload, user: dict = Depends(get_current_user)):
    username = user.get("username")
    import career_record
    if career_record.path_for_user(username):
        raise HTTPException(status_code=409, detail="Your CV text comes from your career record; edit the record instead.")
    cv_path = _user_asset_save_path(username, "CV-plaintext.txt")
    os.makedirs(os.path.dirname(cv_path), exist_ok=True)
    with open(cv_path, "w", encoding="utf-8") as f:
        f.write(body.content)
    logger.info("CV-plaintext.txt updated by user '%s' -> %s", username, _display_path(cv_path))
    return {"success": True, "save_path": _display_path(cv_path)}


@app.get("/api/profile/notes")
def get_profile_notes(user: dict = Depends(get_current_user)):
    username = user.get("username")
    notes_path = resolve_user_path(username, "standing_notes.txt")
    content = ""
    exists = os.path.exists(notes_path)
    if exists:
        with open(notes_path, "r", encoding="utf-8") as f:
            content = f.read()
    return {
        "notes": content,
        "exists": exists,
        "loaded_from": _display_path(notes_path),
        "save_path": _display_path(_user_asset_save_path(username, "standing_notes.txt")),
    }


@app.put("/api/profile/notes")
def save_profile_notes(body: ProfileNotesPayload, user: dict = Depends(get_current_user)):
    username = user.get("username")
    notes_path = _user_asset_save_path(username, "standing_notes.txt")
    os.makedirs(os.path.dirname(notes_path), exist_ok=True)
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(body.notes)
    logger.info("standing_notes.txt updated by user '%s' -> %s", username, _display_path(notes_path))
    return {"success": True, "save_path": _display_path(notes_path)}


VALID_THEMES = {
    "default",
    "kanagawa-wave",
    "kanagawa-dragon",
    "kanagawa-lotus",
    "catppuccin-mocha",
    "catppuccin-latte",
    "rose-pine",
    "nord",
}

VALID_FONTS = {
    "inter",
    "geist",
    "plus-jakarta-sans",
    "dm-sans",
    "ibm-plex-sans",
    "manrope",
}


class UiPreferencesPayload(BaseModel):
    theme: str = Field(default="default", max_length=50)
    font: str = Field(default="inter", max_length=50)

    @field_validator("theme")
    @classmethod
    def _validate_theme(cls, v: str) -> str:
        t = (v or "").strip().lower()
        if t in VALID_THEMES:
            return t
        return "default"

    @field_validator("font")
    @classmethod
    def _validate_font(cls, v: str) -> str:
        f = (v or "").strip().lower()
        if f in VALID_FONTS:
            return f
        return "inter"


@app.get("/api/preferences")
def get_ui_preferences(user: dict = Depends(get_current_user)):
    username = user.get("username")
    return user_assets.load_ui_preferences(username)


@app.put("/api/preferences")
def update_ui_preferences(body: UiPreferencesPayload, user: dict = Depends(get_current_user)):
    username = user.get("username")
    saved = user_assets.save_ui_preferences(username, body.model_dump())
    return {"success": True, "preferences": saved}


@app.post("/api/jobs/manual")
def add_job_manual(req: ManualJobRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    if req.job_url:
        existing_urls = db.load_job_urls(user["id"])
        if req.job_url in existing_urls:
            raise HTTPException(status_code=400, detail="Job URL already exists.")

    cv_text = load_cv_text(username)
    if req.save_to_db:
        model_name = _effective_ai_model(req.modelName, user, purpose="scrape")
        ai_data = process_job_with_ai(
            req.description, cv_text, model_name=model_name, user=user,
            denoise=_scrapers.denoise_enabled(username, "manual"),
        )
    else:
        ai_data = {
            "german_level": "none",
            "requires_german": False,
            "salary": "Not Specified",
            "salary_yearly": None,
            "skills": "Not Specified",
            "summary": "One-off Draft (No AI Preprocessing)",
            "match_score": None
        }

    new_job = {
        **ai_data,
        'raw_description': req.description,
        'normalized_description': ai_data.get('description') or req.description,
        # Manual entries can be created several times within one second.  A
        # timestamp-only ID caused INSERT OR REPLACE to overwrite the prior
        # manual job when two submissions landed in the same second.
        'id': f"manual_{uuid.uuid4().hex}",
        'job_url': req.job_url,
        'title': req.title,
        'company': req.company,
        'location': req.location,
        'description': ai_data.get("description") or req.description,
        'german_level': ai_data.get("german_level", "unknown"),
        'requires_german': ai_data.get("requires_german", False),
        'salary': ai_data["salary"],
        'salary_yearly': ai_data.get("salary_yearly"),
        'skills': ai_data["skills"],
        'summary': ai_data["summary"],
        'status': 'new',
        'application_date': None,
        'application_method': None,
        'response_status': None,
        'company_contact': ai_data.get("company_contact") or None,
        'match_score': ai_data["match_score"],
        'work_model': ai_data.get("work_model"),
        'experience_years': ai_data.get("experience_years"),
        'education_level': ai_data.get("education_level"),
        'tools_technologies': ai_data.get("tools_technologies", []),
        'requirements': ai_data.get("requirements", []),
        'tasks': ai_data.get("tasks", []),
        'company_summary': ai_data.get("company_summary"),
        'match_analysis': ai_data.get("match_analysis", {}),
        'date_scraped': datetime.now().strftime("%Y-%m-%d"),
        'source': 'manual',
        'processed': 0 if ai_data.get('analysis_state') == 'failed' else 1,
        'cv_profile_override': normalize_profile(req.cv_profile_override, username),
    }

    # Both save_to_db=True and one-off jobs go into the same DB now
    db.upsert_job(new_job, user_id=user["id"], is_one_off=not req.save_to_db)
    return {"success": ai_data.get('analysis_state') != 'failed',
            "saved": True, "message": "Posting saved; analysis failed and can be retried." if ai_data.get('analysis_state') == 'failed' else "Manual job added.",
            "job_id": new_job['id'], "job": new_job}

@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str, user: dict = Depends(get_current_user)):
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job['analysis_current'] = (job['analysis_fingerprint'] == fingerprint(load_cv_text(user.get('username')),
        _effective_ai_model(None, user, purpose='scrape'))) if job.get('analysis_fingerprint') else None
    job['default_document_engine'] = load_document_engine_config(user)[0]
    job['eligibility'] = eligibility(job, load_user_config_dict(user))
    return {"success": True, "job": _sanitize_for_json(job)}


@app.get("/api/jobs/{job_id}/published-documents")
def get_published_documents(job_id: str, user: dict = Depends(get_current_user)):
    """The job's newest CV and letter PDFs, read-only (no folders created, nothing rendered); the same links
    the Jobs list shows. Used by the MCP server, which must not call the documents editor route."""
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    job_id_safe = str(job_id).replace(":", "_").replace(" ", "_")
    folder = f"{_make_company_safe(job.get('company', 'Unknown'))}_{job_id_safe}"
    out_dir = os.path.join(user_outputs_dir(user.get("username")), folder)
    urls, revision = {}, None
    if os.path.isdir(out_dir):
        for fname in sorted(os.listdir(out_dir)):
            mtime = int(os.path.getmtime(os.path.join(out_dir, fname)))
            if fname.startswith("CV-") and fname.endswith(".pdf"):
                urls["cv_url"] = f"/api/download/{folder}/{fname}?v={mtime}"
            elif fname.startswith("Letter-") and fname.endswith(".pdf"):
                urls["letter_url"] = f"/api/download/{folder}/{fname}?v={mtime}"
        publication = os.path.join(out_dir, "publication.json")
        if os.path.exists(publication):
            with open(publication) as stream:
                saved = json.load(stream)
            urls.update({k: v for k, v in saved.items() if k in ("cv_url", "letter_url") and v})
            revision = saved.get("revision")
    return {"success": True, "cv_url": urls.get("cv_url"), "letter_url": urls.get("letter_url"),
            "revision": revision, "finalized": revision is not None}

@app.post("/api/jobs/{job_id}/research")
def research_job_company(
    job_id: str,
    req: Optional[JobResearchRequest] = None,
    user: dict = Depends(get_current_user),
):
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    company = (job.get("company") or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="Job does not have a company name.")

    title = job.get("title", "")
    description = job.get("description", "")

    cfg_path = resolve_user_path(user.get("username") if user else None, "scraper_config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    model = (req.model_name if req and req.model_name else None) or cfg.get("sonar_model") or "perplexity/sonar"

    try:
        research_text = research_company_sonar(
            company=company,
            role_title=title,
            description=description,
            model_name=model,
            label=f"sonar-{company[:20]}",
        )
    except Exception as e:
        logger.error(f"Failed to research company '{company}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to research company: {str(e)}")

    now_iso = datetime.now().isoformat()
    use_docs = job.get("use_research_in_docs")
    if use_docs is None:
        use_docs = True

    db.update_job_fields(
        job_id,
        user_id=user["id"],
        company_research=research_text,
        company_research_updated_at=now_iso,
        use_research_in_docs=use_docs,
    )

    return {
        "success": True,
        "company_research": research_text,
        "company_research_updated_at": now_iso,
        "use_research_in_docs": use_docs,
    }

@app.put("/api/jobs/{job_id}")
def update_job(job_id: str, req: JobUpdateRequest, user: dict = Depends(get_current_user)):
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    # Auto-set application_date when marking as applied
    if updates.get("status") == "applied" and "application_date" not in updates:
        updates["application_date"] = datetime.now().strftime("%Y-%m-%d")
    if "company" in updates:
        _rename_doc_folders_if_company_changed(
            job_id, job.get("company", "Unknown"), updates["company"], user.get("username")
        )
    if not db.update_job_fields(job_id, user_id=user["id"], **updates):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"success": True}

@app.delete("/api/jobs")
def delete_unreviewed_jobs(user: dict = Depends(get_current_user)):
    """Delete only 'new'/'interested' jobs — preserves applied/interview/offer/rejected pipeline."""
    deleted = db.delete_unreviewed_jobs(user["id"])
    return {"success": True, "deleted": deleted}

@app.delete("/api/jobs/all")
def delete_all_jobs(user: dict = Depends(get_current_user)):
    """Wipe every job including tracked pipeline entries. Use with caution."""
    db.delete_all_jobs(user["id"])
    return {"success": True}

@app.delete("/api/jobs/{job_id}")
def delete_single_job(job_id: str, user: dict = Depends(get_current_user)):
    """Delete one job of the logged-in user (any status)."""
    if not db.delete_job(job_id, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}

@app.post("/api/generate/cv")
def generate_cv(req: GenerateRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    cfg_model, cfg_tone = load_generation_config(user)
    model_name = _effective_ai_model(req.modelName, user)
    tone = req.tone if (req.tone is not None and str(req.tone).strip()) else cfg_tone
    job = db.get_job_by_id(req.job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    selection = select_cv_profile(job, normalize_profile(req.cv_profile or job.get("cv_profile_override"), username), user=username)
    err = _try_generate_cv_pdf(req.job_id, model_name, tone or "", user, selection["profile"], compact=req.compact, engine=req.engine, language=req.language)
    if err == "Job not found":
        raise HTTPException(status_code=404, detail=err)
    if err == "CV-plaintext.txt not found":
        raise HTTPException(status_code=400, detail=err)
    if err:
        raise HTTPException(status_code=500, detail=err)
    job = db.get_job_by_id(req.job_id, user["id"])
    job_id_safe = str(req.job_id).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    pdf_filename = f"CV-{company_safe}.pdf"
    download_url = get_job_documents(req.job_id, user=user)['cv_download_url']
    if not download_url:
        raise HTTPException(status_code=500, detail='Published CV URL is missing')
    return {"success": True, "filename": pdf_filename, "download_url": download_url, "cv_profile": selection["profile"], "cv_profile_label": profile_label(selection["profile"], username), "cv_profile_confidence": selection["confidence"], "cv_profile_reason": selection["reason"]}

@app.post("/api/generate/letter")
def generate_letter(req: GenerateRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    cfg_model, cfg_tone = load_generation_config(user)
    model_name = _effective_ai_model(req.modelName, user)
    tone = req.tone if (req.tone is not None and str(req.tone).strip()) else cfg_tone
    err = _try_generate_letter_pdf(req.job_id, model_name, tone or "", user, engine=req.engine, language=req.language)
    if err == "Job not found":
        raise HTTPException(status_code=404, detail=err)
    if err == "CV-plaintext.txt not found":
        raise HTTPException(status_code=400, detail=err)
    if err:
        raise HTTPException(status_code=500, detail=err)
    job = db.get_job_by_id(req.job_id, user["id"])
    job_id_safe = str(req.job_id).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    pdf_filename = f"Letter-{company_safe}.pdf"
    download_url = get_job_documents(req.job_id, user=user)['cl_download_url']
    if not download_url:
        raise HTTPException(status_code=500, detail='Published letter URL is missing')
    return {"success": True, "filename": pdf_filename, "download_url": download_url}


@app.post("/api/generate/batch")
def api_batch_generate_start(req: BatchGenerateRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    db.async_task_prune_completed(3600)
    db.async_task_cancel_running_batch_generate(user["id"])
    task_id = str(uuid.uuid4())
    cfg_model, cfg_tone = load_generation_config(user)
    model_name = _effective_ai_model(req.modelName, user)
    tone = req.tone if (req.tone is not None and str(req.tone).strip()) else cfg_tone
    n = len(req.job_ids)
    db.async_task_create(
        task_id,
        "batch_generate",
        total=n,
        payload=req.model_dump(),
        user_id=user["id"],
    )
    background_tasks.add_task(_run_batch_generate_bg, task_id, req.job_ids, model_name, tone, user, bool(req.force), normalize_profile(req.cv_profile, user.get("username")), req.compact, req.engine)
    return {"success": True, "task_id": task_id, "total": n}


@app.get("/api/generate/batch/status/{task_id}")
def api_batch_generate_status(task_id: str, user: dict = Depends(get_current_user)):
    row = db.async_task_get_batch_generate(task_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@app.get("/api/generate/batch/active")
def api_batch_generate_active(user: dict = Depends(get_current_user)):
    got = db.async_task_get_latest_running_batch_generate(user["id"])
    if not got:
        return {"active": False, "task_id": None}
    tid, task = got
    return {"active": True, "task_id": tid, **task}


@app.post("/api/generate/batch/cancel")
def api_batch_generate_cancel(user: dict = Depends(get_current_user)):
    db.async_task_cancel_running_batch_generate(user["id"])
    return {"success": True}

@app.get("/api/cv-profiles")
def get_cv_profiles(user: dict = Depends(get_current_user)):
    return {"profiles": available_profiles(user.get("username"))}

@app.post("/api/cv-profiles/select")
def select_cv_profile_api(job: dict = Body(...), cv_profile: Optional[str] = Query(default=None), user: dict = Depends(get_current_user)):
    return select_cv_profile(job, normalize_profile(cv_profile, user.get("username")), user=user.get("username"))

@app.get("/api/download/draft/{filepath:path}")
def download_tmp_pdf(filepath: str, user: dict = Depends(get_current_user)):
    full_path = _resolved_safe_path(filepath, user_drafts_dir(user.get("username")))
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(full_path)[1].lower()
    ext_media = {
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tex": "text/plain",
    }
    guessed, _ = mimetypes.guess_type(full_path)
    media = ext_media.get(ext) or guessed or "application/octet-stream"
    return FileResponse(
        full_path, media_type=media, filename=os.path.basename(filepath),
        headers={"Cache-Control": "no-store"},
    )

@app.get("/api/download/documents/{filepath:path}")
def download_studio_document_file(filepath: str, user: dict = Depends(get_current_user)):
    full_path = _resolved_safe_path(filepath, user_documents_dir(user.get("username")))
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(full_path)[1].lower()
    ext_media = {
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tex": "text/plain",
        ".log": "text/plain",
        ".json": "application/json",
    }
    guessed, _ = mimetypes.guess_type(full_path)
    media = ext_media.get(ext) or guessed or "application/octet-stream"
    return FileResponse(
        full_path, media_type=media, filename=os.path.basename(filepath),
        headers={"Cache-Control": "no-store"},
    )

def _download_name(username: Optional[str], basename: str) -> str:
    """Name the browser saves an application PDF under (see reviewed_documents.download_name)."""
    if not basename.startswith(("CV-", "Letter-")):
        return basename
    try:
        cv_text = load_cv_text(username)
    except Exception:
        cv_text = None
    return reviewed_documents.download_name(username, basename, cv_text)


@app.get("/api/download/{filepath:path}")
def download_pdf(filepath: str, user: dict = Depends(get_current_user)):
    full_path = _resolved_safe_path(filepath, user_outputs_dir(user.get("username")))
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        full_path, media_type='application/pdf',
        filename=_download_name(user.get("username"), os.path.basename(filepath)),
        headers={"Cache-Control": "no-store"},
    )

class RefineStartRequest(BaseModel):
    job_id: str
    doc_type: str = "all" # 'cv', 'letter', or 'all'
    modelName: Optional[str] = None  # None -> the user's configured model for this purpose
    tone: Optional[str] = ""
    cv_profile: Optional[str] = None
    compact: Optional[bool] = False
    force: Optional[bool] = False

# --- Refine Endpoint Helpers ---
def get_available_versions(job_id_safe: str, doc_type: str, draft_dir: str) -> List[int]:
    """Returns a sorted list of available version integers for a given job and document type."""
    versions = []
    prefix = f"{doc_type}_draft_{job_id_safe}_v"
    try:
        for f in os.listdir(draft_dir):
            if f.startswith(prefix) and f.endswith(".pdf"):
                v_str = f[len(prefix):-4]
                if v_str.isdigit():
                    versions.append(int(v_str))
        return sorted(versions)
    except Exception:
        return []

@app.post("/api/refine/start")
def refine_start(req: RefineStartRequest, user: dict = Depends(get_current_user)):
    """Compatibility adapter to the reviewed generation/publication pipeline."""
    errors = []
    model = _effective_ai_model(req.modelName, user)
    if req.doc_type in ('cv', 'all'):
        error = _try_generate_cv_pdf(req.job_id, model, req.tone or '', user,
                                     cv_profile=req.cv_profile, compact=bool(req.compact))
        if error: errors.append(error)
    if req.doc_type in ('letter', 'all'):
        error = _try_generate_letter_pdf(req.job_id, model, req.tone or '', user)
        if error: errors.append(error)
    if errors:
        raise HTTPException(status_code=422, detail='; '.join(errors))
    result = get_job_documents(req.job_id, user=user)
    return {**result, 'cv_image_urls': result.get('cv_images', []),
            'cl_image_urls': result.get('cl_images', []), 'cv_versions': [], 'cl_versions': [],
            'cv_url': result.get('cv_download_url'), 'letter_url': result.get('cl_download_url')}

@app.post("/api/refine/iterate")
def refine_iterate(req: RefineIterateRequest, user: dict = Depends(get_current_user)):
    result = ai_edit_job_document(req.job_id, JobDocAiEditRequest(
        document_type=req.document_type, tex=req.current_tex,
        instruction=req.feedback, model_name=req.modelName), user=user)
    return {**result, 'new_tex': result['modified_tex'], 'versions': [],
            'success': result.get('compile_success', False)}


class RefineDiffRequest(BaseModel):
    job_id: str
    document_type: str # 'cv' or 'letter'
    target_version: int

@app.post("/api/refine/diff")
def refine_diff(req: RefineDiffRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    job = db.get_job_by_id(req.job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_id_safe = str(req.job_id).replace(':', '_').replace(' ', '_')
    company_safe = _make_company_safe(job.get('company', 'Unknown'))
    folder_name = f"{company_safe}_{job_id_safe}"
    draft_dir = os.path.join(user_drafts_dir(username), folder_name)
    
    doc_type = req.document_type
    file_prefix = "cv" if doc_type == "cv" else "cl"
    
    v0_tex_file = f"{file_prefix}_{job_id_safe}_v0.tex"
    target_tex_file = f"{file_prefix}_{job_id_safe}_v{req.target_version}.tex"
    diff_pdf_file = f"{file_prefix}_diff_{job_id_safe}_v0_v{req.target_version}.pdf"
    
    v0_exists = os.path.exists(os.path.join(draft_dir, v0_tex_file))
    target_exists = os.path.exists(os.path.join(draft_dir, target_tex_file))
    
    if not v0_exists or not target_exists:
        raise HTTPException(status_code=400, detail="Requested versions not found.")
        
    folder = resolve_user_path(username, "base-cv-tex") if doc_type == "cv" else resolve_user_path(username, "base-cl-tex")
    
    diff_success, diff_msg = compile_latex_diff(draft_dir, v0_tex_file, target_tex_file,
                                               diff_pdf_file, draft_dir, resource_dir=folder)
    
    if not diff_success:
        raise HTTPException(status_code=500, detail=f"Diff compilation failed: {diff_msg}")
        
    # Generate images for the diff pdf
    diff_pdf_path = os.path.join(draft_dir, diff_pdf_file)
    diff_img_prefix = f"{file_prefix}_diff_img_{job_id_safe}"
    diff_images = convert_pdf_to_images(diff_pdf_path, draft_dir, diff_img_prefix)
        
    return {
        "success": True,
        "diff_image_urls": [f"/api/download/draft/{folder_name}/{img}" for img in diff_images],
        "diff_pdf_url": f"/api/download/draft/{folder_name}/{diff_pdf_file}" # keep pdf url just in case
    }

@app.post("/api/refine/finalize")
def refine_finalize(req: RefineFinalizeRequest, user: dict = Depends(get_current_user)):
    for kind, source in (('cv', req.cv_tex), ('letter', req.letter_tex)):
        if source and source.strip():
            result = compile_job_document(req.job_id, JobDocCompileRequest(document_type=kind, tex=source), user=user)
            if not result.get('success'):
                raise HTTPException(status_code=422, detail=result.get('error', 'Compilation failed'))
    return finalize_job_documents(req.job_id, JobDocFinalizeRequest(
        cv_source=req.cv_tex or None, letter_source=req.letter_tex or None), user=user)

# ---------------------------------------------------------------------------
# In-Job Tailor Studio endpoints
# ---------------------------------------------------------------------------

class JobDocCompileRequest(BaseModel):
    document_type: str = "cv"  # "cv" or "letter"
    tex: str
    pdf_base64: Optional[str] = None

class JobDocAiEditRequest(BaseModel):
    document_type: str = "cv"  # "cv" or "letter"
    tex: str
    instruction: str
    selection: Optional[str] = None
    model_name: Optional[str] = None

class JobDocRestoreVersionRequest(BaseModel):
    document_type: str = "cv"  # "cv" or "letter"
    version_id: str

class JobDocFinalizeRequest(BaseModel):
    document_type: str = "all"  # "cv", "letter", or "all"
    cv_pdf_base64: Optional[str] = None
    letter_pdf_base64: Optional[str] = None
    cv_source: Optional[str] = None
    letter_source: Optional[str] = None
@app.get("/api/jobs/{job_id}/documents")
def get_job_documents(job_id: str, user: dict = Depends(get_current_user)):
    username = user.get("username")
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_id_safe = str(job_id).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    draft_dir = os.path.join(user_drafts_dir(username), folder_name)
    out_dir = os.path.join(user_outputs_dir(username), folder_name)
    if demo_mode.enabled():
        return demo_mode.documents(Path(draft_dir), folder_name)
    os.makedirs(draft_dir, exist_ok=True)

    # 1. CV files
    cv_typ_path = os.path.join(draft_dir, f"cv_{job_id_safe}.typ")
    cv_tex_path = os.path.join(draft_dir, f"cv_{job_id_safe}.tex")
    cv_draft_pdf = os.path.join(draft_dir, f"cv_draft_{job_id_safe}.pdf")
    cv_out_pdf = os.path.join(out_dir, f"CV-{company_safe}.pdf")
    
    active = active_source(draft_dir, 'cv', job_id_safe)
    if active and active.endswith('.tex'): cv_typ_path = ''
    if active and active.endswith('.typ'): cv_tex_path = ''
    cv_tex = ""
    cv_engine = "latex"
    if os.path.exists(cv_typ_path):
        try:
            with open(cv_typ_path, "r", encoding="utf-8") as f:
                cv_tex = f.read()
            cv_engine = "typst"
        except Exception:
            pass
    elif os.path.exists(cv_tex_path):
        try:
            with open(cv_tex_path, "r", encoding="utf-8") as f:
                cv_tex = f.read()
            cv_engine = "latex"
        except Exception:
            pass

    if not os.path.exists(cv_draft_pdf) and os.path.exists(cv_out_pdf):
        try:
            shutil.copy2(cv_out_pdf, cv_draft_pdf)
        except Exception:
            pass

    cv_images = []
    if os.path.exists(cv_draft_pdf):
        img_prefix = f"cv_img_{job_id_safe}"
        existing_imgs = sorted([
            f for f in os.listdir(draft_dir)
            if f.startswith(img_prefix) and f.endswith(".png")
        ])
        if not existing_imgs:
            existing_imgs = convert_pdf_to_images(cv_draft_pdf, draft_dir, img_prefix)
        mtime = int(os.path.getmtime(cv_draft_pdf))
        cv_images = [f"/api/download/draft/{folder_name}/{img}?v={mtime}" for img in existing_imgs]

    # 2. Cover Letter files
    cl_typ_path = os.path.join(draft_dir, f"cl_{job_id_safe}.typ")
    cl_tex_path = os.path.join(draft_dir, f"cl_{job_id_safe}.tex")
    cl_draft_pdf = os.path.join(draft_dir, f"cl_draft_{job_id_safe}.pdf")
    cl_out_pdf = os.path.join(out_dir, f"Letter-{company_safe}.pdf")

    active = active_source(draft_dir, 'cl', job_id_safe)
    if active and active.endswith('.tex'): cl_typ_path = ''
    if active and active.endswith('.typ'): cl_tex_path = ''
    cl_tex = ""
    cl_engine = "latex"
    if os.path.exists(cl_typ_path):
        try:
            with open(cl_typ_path, "r", encoding="utf-8") as f:
                cl_tex = f.read()
            cl_engine = "typst"
        except Exception:
            pass
    elif os.path.exists(cl_tex_path):
        try:
            with open(cl_tex_path, "r", encoding="utf-8") as f:
                cl_tex = f.read()
            cl_engine = "latex"
        except Exception:
            pass

    if not os.path.exists(cl_draft_pdf) and os.path.exists(cl_out_pdf):
        try:
            shutil.copy2(cl_out_pdf, cl_draft_pdf)
        except Exception:
            pass

    cl_images = []
    if os.path.exists(cl_draft_pdf):
        img_prefix = f"cl_img_{job_id_safe}"
        existing_imgs = sorted([
            f for f in os.listdir(draft_dir)
            if f.startswith(img_prefix) and f.endswith(".png")
        ])
        if not existing_imgs:
            existing_imgs = convert_pdf_to_images(cl_draft_pdf, draft_dir, img_prefix)
        mtime = int(os.path.getmtime(cl_draft_pdf))
        cl_images = [f"/api/download/draft/{folder_name}/{img}?v={mtime}" for img in existing_imgs]

    cv_download_url = None
    if os.path.exists(cv_out_pdf):
        mtime = int(os.path.getmtime(cv_out_pdf))
        cv_download_url = f"/api/download/{folder_name}/CV-{company_safe}.pdf?v={mtime}"
    elif os.path.exists(cv_draft_pdf):
        mtime = int(os.path.getmtime(cv_draft_pdf))
        cv_download_url = f"/api/download/draft/{folder_name}/cv_draft_{job_id_safe}.pdf?v={mtime}"

    cl_download_url = None
    if os.path.exists(cl_out_pdf):
        mtime = int(os.path.getmtime(cl_out_pdf))
        cl_download_url = f"/api/download/{folder_name}/Letter-{company_safe}.pdf?v={mtime}"
    elif os.path.exists(cl_draft_pdf):
        mtime = int(os.path.getmtime(cl_draft_pdf))
        cl_download_url = f"/api/download/draft/{folder_name}/cl_draft_{job_id_safe}.pdf?v={mtime}"

    publication = os.path.join(out_dir, 'publication.json')
    if os.path.exists(publication):
        with open(publication) as stream:
            published = json.load(stream)
        cv_download_url = published.get('cv_url') or cv_download_url
        cl_download_url = published.get('letter_url') or cl_download_url

    ai_versions = _get_ai_versions(draft_dir)
    # Seed Original Draft if document exists on disk but has no versions recorded yet
    if not ai_versions.get("cv") and cv_tex:
        cv_v0_typ = os.path.join(draft_dir, f"cv_{job_id_safe}_v0.typ")
        cv_v0_tex = os.path.join(draft_dir, f"cv_{job_id_safe}_v0.tex")
        initial_cv_tex = ""
        initial_cv_engine = cv_engine
        if os.path.exists(cv_v0_typ):
            try:
                with open(cv_v0_typ, "r", encoding="utf-8") as f:
                    initial_cv_tex = f.read()
                initial_cv_engine = "typst"
            except Exception:
                pass
        elif os.path.exists(cv_v0_tex):
            try:
                with open(cv_v0_tex, "r", encoding="utf-8") as f:
                    initial_cv_tex = f.read()
                initial_cv_engine = "latex"
            except Exception:
                pass
        _record_initial_document_version(draft_dir, "cv", initial_cv_tex or cv_tex, initial_cv_engine)

    if not ai_versions.get("letter") and cl_tex:
        cl_v0_typ = os.path.join(draft_dir, f"cl_{job_id_safe}_v0.typ")
        cl_v0_tex = os.path.join(draft_dir, f"cl_{job_id_safe}_v0.tex")
        initial_cl_tex = ""
        initial_cl_engine = cl_engine
        if os.path.exists(cl_v0_typ):
            try:
                with open(cl_v0_typ, "r", encoding="utf-8") as f:
                    initial_cl_tex = f.read()
                initial_cl_engine = "typst"
            except Exception:
                pass
        elif os.path.exists(cl_v0_tex):
            try:
                with open(cl_v0_tex, "r", encoding="utf-8") as f:
                    initial_cl_tex = f.read()
                initial_cl_engine = "latex"
            except Exception:
                pass
        _record_initial_document_version(draft_dir, "letter", initial_cl_tex or cl_tex, initial_cl_engine)

    return {
        "success": True,
        "has_cv": bool(cv_tex or os.path.exists(cv_draft_pdf) or os.path.exists(cv_out_pdf)),
        "has_letter": bool(cl_tex or os.path.exists(cl_draft_pdf) or os.path.exists(cl_out_pdf)),
        "cv_tex": cv_tex,
        "cl_tex": cl_tex,
        "cv_pdf_current": bool(matching_build(cv_draft_pdf, cv_tex)),
        "cl_pdf_current": bool(matching_build(cl_draft_pdf, cl_tex)),
        "cv_engine": cv_engine,
        "cl_engine": cl_engine,
        "cv_images": cv_images,
        "cl_images": cl_images,
        "cv_download_url": cv_download_url,
        "cl_download_url": cl_download_url,
        "ai_versions": _get_ai_versions(draft_dir),
    }

def _job_document_operation(function):
    """Serialize edits/restores and their history in the current backend process."""
    from functools import wraps
    @wraps(function)
    def guarded(job_id, req, user=None):
        job = db.get_job_by_id(job_id, user['id'])
        if not job:
            raise HTTPException(status_code=404, detail='Job not found')
        safe_id = str(job_id).replace(':', '_').replace(' ', '_')
        folder = Path(user_drafts_dir(user.get('username')), f"{_make_company_safe(job.get('company', 'Unknown'))}_{safe_id}")
        with document_lock(folder):
            return function(job_id, req, user=user)
    return guarded


@app.post("/api/jobs/{job_id}/documents/compile")
def compile_job_document(job_id: str, req: JobDocCompileRequest, user: dict = Depends(get_current_user)):
    job = db.get_job_by_id(job_id, user['id'])
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    if req.document_type not in ('cv', 'letter'):
        raise HTTPException(status_code=400, detail='document_type must be cv or letter')
    safe_id = str(job_id).replace(':', '_').replace(' ', '_')
    folder_name = f"{_make_company_safe(job.get('company', 'Unknown'))}_{safe_id}"
    folder = os.path.join(user_drafts_dir(user.get('username')), folder_name)
    prefix = 'cv' if req.document_type == 'cv' else 'cl'
    engine = 'latex' if '\\documentclass' in req.tex else 'typst'
    source_path = os.path.join(folder, f'{prefix}_{safe_id}.' + ('tex' if engine == 'latex' else 'typ'))
    pdf_name = f'{prefix}_draft_{safe_id}.pdf'
    pdf_path = os.path.join(folder, pdf_name)
    with document_lock(folder):
        # Validate before replacing either the current source or last-good PDF.
        try:
            client_pdf = decode_pdf(req.pdf_base64) if req.pdf_base64 else None
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        previous_source = active_source(folder, prefix, safe_id)
        if previous_source:
            old = Path(previous_source).read_text(encoding='utf-8')
            atomic_write(Path(folder, 'history', digest(old) + Path(previous_source).suffix), old)
        atomic_write(source_path, req.tex)
        atomic_write(Path(folder, 'history', digest(req.tex) + Path(source_path).suffix), req.tex)
        select_source(folder, prefix, safe_id, 'tex' if engine == 'latex' else 'typ')
        if client_pdf:
            atomic_write(pdf_path, client_pdf)
            record_build(pdf_path, req.tex, engine, verified=False)
            ok, log = True, 'Client preview saved; finalization verifies the saved source.'
        elif engine == 'typst':
            ok, log = compile_typst(folder, os.path.basename(source_path), pdf_name, folder)
        else:
            resources = resolve_user_path(user.get('username'), 'base-cv-tex' if prefix == 'cv' else 'base-cl-tex')
            ok, log = compile_latex(folder, os.path.basename(source_path), pdf_name, folder, resource_dir=resources)
        if not ok:
            return {'success': False, 'error': f'{engine.title()} compilation failed.',
                    'parsed_error': parse_typst_error(log) if engine == 'typst' else parse_pdflatex_error(log),
                    'raw_log': log, 'source_hash': digest(req.tex), 'stale_pdf': os.path.exists(pdf_path)}
        manifest = matching_build(pdf_path, req.tex)
        if not manifest:
            return {'success': False, 'error': 'Compiler did not produce a valid PDF for this source.'}
        image_prefix = f'{prefix}_img_{safe_id}'
        images = convert_pdf_to_images(pdf_path, folder, image_prefix)
        return {'success': True, 'source_hash': digest(req.tex), 'revision': manifest['revision'],
                'image_urls': [f'/api/download/draft/{folder_name}/{name}?v={manifest["revision"]}' for name in images],
                'pdf_url': f'/api/download/draft/{folder_name}/{pdf_name}?v={manifest["revision"]}',
                'preview_warning': None if images else 'PDF saved; image preview unavailable.'}

@app.post("/api/jobs/{job_id}/documents/ai-edit")
@_job_document_operation
def ai_edit_job_document(job_id: str, req: JobDocAiEditRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    doc_type = req.document_type.lower()
    if doc_type not in ("cv", "letter"):
        raise HTTPException(status_code=400, detail="document_type must be 'cv' or 'letter'")

    model_name = _effective_ai_model(req.model_name, user)
    is_typst = "#set " in req.tex or "#let " in req.tex or req.tex.strip().startswith("//")

    try:
        if is_typst:
            modified_text = ai_surgical_edit_typst(
                typst_code=req.tex,
                instruction=req.instruction,
                selection=req.selection,
                model_name=model_name,
                user=username,
            )
        else:
            modified_text = ai_surgical_edit_latex(
                tex_code=req.tex,
                instruction=req.instruction,
                selection=req.selection,
                model_name=model_name,
                user=username,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error(f"AI surgical edit error for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"AI edit failed: {e}")

    if not modified_text:
        raise HTTPException(status_code=500, detail="AI edit returned empty document")

    job_id_safe = str(job_id).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    draft_dir = os.path.join(user_drafts_dir(username), folder_name)
    os.makedirs(draft_dir, exist_ok=True)

    # Versioning: snapshot pre-edit baseline/manual state (if needed) and AI result
    versions = _get_ai_versions(draft_dir)
    doc_versions = versions.get(doc_type, [])
    now_ts = int(time.time() * 1000)
    now_dt = datetime.fromtimestamp(now_ts / 1000.0)
    date_str = now_dt.strftime("%d.%m %H:%M")
    instr_trimmed = req.instruction.strip()
    instr_preview = instr_trimmed[:32] + "…" if len(instr_trimmed) > 32 else instr_trimmed

    # If this is the first AI edit on this document, snapshot the initial pre-edit state
    if not doc_versions:
        base_snapshot = {
            "id": uuid.uuid4().hex,
            "timestamp": now_ts,
            "date_str": date_str,
            "instruction": "Original document",
            "label": "Original Draft",
            "tex": req.tex,
            "engine": "typst" if is_typst else "latex",
        }
        doc_versions = [base_snapshot]
    elif req.tex.strip() and not any(v.get("tex", "").strip() == req.tex.strip() for v in doc_versions):
        # User made manual edits since previous snapshots; capture them before applying AI
        pre_ts = now_ts
        pre_snapshot = {
            "id": uuid.uuid4().hex,
            "timestamp": pre_ts,
            "date_str": date_str,
            "instruction": f"State before: {instr_trimmed}",
            "label": f'Before: "{instr_preview}"',
            "tex": req.tex,
            "engine": "typst" if is_typst else "latex",
        }
        doc_versions = [pre_snapshot] + doc_versions

    # Record the newly generated AI state as a first-class selectable version
    ai_ts = now_ts + 10
    ai_dt = datetime.fromtimestamp(ai_ts / 1000.0)
    ai_snapshot = {
        "id": uuid.uuid4().hex,
        "timestamp": ai_ts,
        "date_str": ai_dt.strftime("%d.%m %H:%M"),
        "instruction": instr_trimmed,
        "label": f'AI: "{instr_preview}"',
        "tex": modified_text,
        "engine": "typst" if is_typst else "latex",
    }
    doc_versions = [ai_snapshot] + doc_versions
    versions[doc_type] = doc_versions
    _save_ai_versions(draft_dir, versions)

    result = compile_job_document(job_id, JobDocCompileRequest(document_type=doc_type, tex=modified_text), user=user)
    return {**result, 'success': True, 'compile_success': result.get('success', False),
            'modified_tex': modified_text, 'ai_versions': versions,
            'active_version_id': ai_snapshot['id']}

@app.post("/api/jobs/{job_id}/documents/restore-version")
@_job_document_operation
def restore_job_document_version(job_id: str, req: JobDocRestoreVersionRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    job = db.get_job_by_id(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    doc_type = req.document_type.lower()
    if doc_type not in ("cv", "letter"):
        raise HTTPException(status_code=400, detail="document_type must be 'cv' or 'letter'")

    job_id_safe = str(job_id).replace(":", "_").replace(" ", "_")
    company_safe = _make_company_safe(job.get("company", "Unknown"))
    folder_name = f"{company_safe}_{job_id_safe}"
    draft_dir = os.path.join(user_drafts_dir(username), folder_name)

    versions = _get_ai_versions(draft_dir)
    doc_versions = versions.get(doc_type, [])
    target_version = None
    target_idx = -1
    for i, v in enumerate(doc_versions):
        if str(v.get("id")) == str(req.version_id):
            target_version = v
            target_idx = i
            break

    if not target_version:
        raise HTTPException(status_code=404, detail="Version snapshot not found")

    restored_tex = target_version.get("tex", "")
    is_typst = target_version.get("engine") == "typst" or (
        "#set " in restored_tex or "#let " in restored_tex or restored_tex.strip().startswith("//")
    )

    result = compile_job_document(job_id, JobDocCompileRequest(document_type=doc_type, tex=restored_tex), user=user)
    return {**result, 'success': True, 'compile_success': result.get('success', False),
            'restored_tex': restored_tex, 'ai_versions': versions,
            'active_version_id': str(target_version['id'])}

@app.post("/api/jobs/{job_id}/documents/finalize")
def finalize_job_documents(job_id: str, req: JobDocFinalizeRequest, user: dict = Depends(get_current_user)):
    job = db.get_job_by_id(job_id, user['id'])
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    if req.document_type not in ('cv', 'letter', 'all'):
        raise HTTPException(status_code=400, detail='Invalid document_type')
    safe_id = str(job_id).replace(':', '_').replace(' ', '_')
    company = _make_company_safe(job.get('company', 'Unknown'))
    folder_name = f'{company}_{safe_id}'
    draft = os.path.join(user_drafts_dir(user.get('username')), folder_name)
    output = os.path.join(user_outputs_dir(user.get('username')), folder_name)
    types = ('cv', 'letter') if req.document_type == 'all' else (req.document_type,)
    with document_lock(draft):
        prepared = []
        for kind in types:
            prefix = 'cv' if kind == 'cv' else 'cl'
            source_path = active_source(draft, prefix, safe_id)
            visible = req.cv_source if kind == 'cv' else req.letter_source
            if source_path is None:
                if req.document_type == 'all' and not visible:
                    continue
                raise HTTPException(status_code=409, detail=f'{kind}: no saved source. Compile first.')
            with open(source_path, encoding='utf-8') as stream:
                source = stream.read()
            if visible is not None and visible != source:
                raise HTTPException(status_code=409, detail=f'{kind}: unsaved changes. Compile this version first.')
            pdf = os.path.join(draft, f'{prefix}_draft_{safe_id}.pdf')
            manifest = matching_build(pdf, source)
            if not manifest:
                raise HTTPException(status_code=409, detail=f'{kind}: PDF is stale or unverified. Compile first.')
            if not manifest['verified']:
                # Browser bytes are previews, not proof of source/PDF correspondence.
                result = compile_job_document(job_id, JobDocCompileRequest(document_type=kind, tex=source), user=user)
                manifest = matching_build(pdf, source)
                if not result['success'] or not manifest or not manifest['verified']:
                    raise HTTPException(status_code=409, detail=f'{kind}: saved source could not be compiled for finalization.')
            prepared.append((kind, prefix, source_path, pdf, manifest))
        if not prepared:
            raise HTTPException(status_code=409, detail='No documents to finalize.')
        revision = uuid.uuid4().hex
        bundle = os.path.join(output, 'revisions', revision)
        os.makedirs(bundle, exist_ok=False)
        urls = {'cv_url': None, 'letter_url': None}
        records = {}
        for kind, prefix, source_path, pdf, manifest in prepared:
            name = f'CV-{company}.pdf' if kind == 'cv' else f'Letter-{company}.pdf'
            shutil.copy2(source_path, os.path.join(bundle, os.path.basename(source_path)))
            shutil.copy2(pdf, os.path.join(bundle, name))
            records[kind] = manifest
            urls['cv_url' if kind == 'cv' else 'letter_url'] = f'/api/download/{folder_name}/revisions/{revision}/{name}'
        atomic_write(os.path.join(bundle, 'manifest.json'), json.dumps(records))
        # Publication becomes visible only after the whole immutable bundle exists.
        previous = {}
        publication = os.path.join(output, 'publication.json')
        if os.path.exists(publication):
            with open(publication) as stream:
                previous = json.load(stream)
        previous.update({key: value for key, value in urls.items() if value})
        previous['revision'] = revision
        atomic_write(publication, json.dumps(previous))
        return {'success': True, 'revision': revision, **urls}

class FetchJobUrlRequest(BaseModel):
    url: str

@app.post("/api/fetch-job-url")
def fetch_job_url(req: FetchJobUrlRequest, user: dict = Depends(get_current_user)):
    """Fetch a job page URL and extract title, company, and description text.

    The page's schema.org JobPosting block is read first (job_jsonld.py); site heuristics are the fallback.
    Only public http(s) addresses are fetched (safe_fetch.py)."""
    from bs4 import BeautifulSoup
    import job_jsonld
    import safe_fetch

    try:
        resp = safe_fetch.fetch_page(req.url)
    except safe_fetch.UnsafeURL as e:
        raise HTTPException(status_code=400, detail=f"This link cannot be fetched: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

    for node in job_jsonld.find_job_postings(resp.text):
        found = job_jsonld.to_job(node)
        if found.get("title") and found.get("description"):
            return {
                **found,
                "company": found.get("company", ""),
                "description": _scrapers.clean_job_description_noise(found["description"]),
                "warning": None,
            }

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title — prefer <h1>, fall back to <title>
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title and soup.title:
        raw = soup.title.get_text(strip=True)
        # karriere.at pattern: "Job Title bei Company | karriere.at"
        import re
        m = re.match(r"^(.+?)\s+bei\s+.+\|", raw)
        title = m.group(1).strip() if m else raw

    # Company — karriere.at page pattern
    company = ""
    if "karriere.at" in req.url:
        import re
        if soup.title:
            m = re.search(r"\s+bei\s+(.+?)\s*\|", soup.title.get_text())
            if m:
                company = m.group(1).strip()
        if not company:
            company_link = soup.find("a", href=lambda h: h and "/f/" in h)
            if company_link:
                company = company_link.get_text(strip=True)

    # Description — remove nav/footer/scripts then get body text
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body_text = soup.get_text(separator="\n", strip=True)
    # Preserve the whole extracted posting for analysis and source evidence.
    description = _scrapers.clean_job_description_noise(
        "\n".join(line for line in body_text.splitlines() if line.strip())
    )

    is_linkedin = "linkedin.com" in req.url
    return {
        "title": title,
        "company": company,
        "description": description,
        "warning": "LinkedIn pages are JavaScript-rendered; description may be incomplete." if is_linkedin else None,
    }


@app.get("/api/daily-results")
def list_daily_dates(user: dict = Depends(get_current_user)):
    """Return the user's distinct date_scraped values from the DB, sorted descending."""
    return {"dates": db.load_distinct_scrape_dates(user["id"])}


@app.get("/api/daily-results/{date}")
def get_daily_results(date: str, user: dict = Depends(get_current_user)):
    """
    Return current analysed jobs matching the user's score and eligibility policy on {date}.
    Annotates each job with cv_url / letter_url if auto-generated PDFs exist in outputs/.
    """
    df = db.load_jobs_by_date(user["id"], date)
    if df.empty:
        # Return empty list (not 404) so frontend shows the empty state gracefully
        return {"date": date, "jobs": []}

    username = user.get('username')
    outputs_root = user_outputs_dir(username)
    policy_config = load_user_config_dict(user)
    expected_analysis = fingerprint(load_cv_text(username), _effective_ai_model(None, user, purpose='scrape'))
    qualifying = []

    for _, row in df.iterrows():
        if not qualifies(row.to_dict(), policy_config, expected_analysis):
            continue

        job_id = str(row.get("id", ""))
        company = str(row.get("company", "Unknown"))
        company_safe = _make_company_safe(company)
        job_id_safe = job_id.replace(":", "_").replace(" ", "_")
        folder_name = f"{company_safe}_{job_id_safe}"
        out_dir = os.path.join(outputs_root, folder_name)

        cv_url = None
        letter_url = None
        if os.path.isdir(out_dir):
            for fname in os.listdir(out_dir):
                fpath = os.path.join(out_dir, fname)
                mtime = int(os.path.getmtime(fpath))
                if fname.startswith("CV-") and fname.endswith(".pdf"):
                    cv_url = f"/api/download/{folder_name}/{fname}?v={mtime}"
                elif fname.startswith("Letter-") and fname.endswith(".pdf"):
                    letter_url = f"/api/download/{folder_name}/{fname}?v={mtime}"

        publication = Path(out_dir, 'publication.json')
        if publication.exists():
            published = json.loads(publication.read_text())
            cv_url = published.get('cv_url') or cv_url
            letter_url = published.get('letter_url') or letter_url

        job_out = row.to_dict()
        job_out = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in job_out.items()}
        job_out["cv_url"] = cv_url
        job_out["letter_url"] = letter_url
        qualifying.append(job_out)

    qualifying.sort(key=lambda j: int(j.get("match_score") or 0), reverse=True)
    return {"date": date, "jobs": qualifying}


@app.get("/api/stats")
def get_stats(user: dict = Depends(get_current_user)):
    df = load_all_jobs(user["id"])
    if df.empty:
        return {
            "total_jobs": 0, "avg_match_score": None,
            "match_score_distribution": [], "source_breakdown": [],
            "jobs_per_day": [], "status_funnel": []
        }

    df = df.astype(object).where(pd.notna(df), None)

    # Match score distribution
    bins = [0, 20, 40, 60, 80, 100]
    labels = ["0-20", "21-40", "41-60", "61-80", "81-100"]
    scores = pd.to_numeric(df["match_score"], errors="coerce").dropna()
    hist_counts = pd.cut(scores, bins=bins, labels=labels, right=True).value_counts().sort_index()
    match_dist = [{"range": lbl, "count": int(hist_counts.get(lbl, 0))} for lbl in labels]

    # Source breakdown
    source_counts = df["source"].fillna("unknown").value_counts()
    source_breakdown = [{"source": src, "count": int(cnt)} for src, cnt in source_counts.items()]

    # Jobs per day (last 60 days)
    date_counts = df["date_scraped"].dropna().value_counts().sort_index()
    jobs_per_day = [{"date": str(d), "count": int(c)} for d, c in date_counts.items()]

    # Application funnel by status
    status_order = ["new", "interested", "not_interested", "applied", "interview", "offer", "rejected"]
    status_col = df["status"].fillna("new") if "status" in df.columns else pd.Series(["new"] * len(df))
    status_counts = status_col.value_counts()
    status_funnel = [{"status": s, "count": int(status_counts.get(s, 0))} for s in status_order]
    # Include any unknown statuses
    for s, c in status_counts.items():
        if s not in status_order:
            status_funnel.append({"status": s, "count": int(c)})

    avg_score = round(float(scores.mean()), 1) if not scores.empty else None

    return {
        "total_jobs": len(df),
        "avg_match_score": avg_score,
        "match_score_distribution": match_dist,
        "source_breakdown": source_breakdown,
        "jobs_per_day": jobs_per_day,
        "status_funnel": status_funnel
    }


# ---------------------------------------------------------------------------
# Skills demand analytics endpoint
# ---------------------------------------------------------------------------

def _parse_skills_field(raw_skills) -> list[str]:
    """Extract individual skill strings from a skills field (str or list)."""
    if not raw_skills:
        return []
    if isinstance(raw_skills, list):
        tokens = raw_skills
    else:
        raw = str(raw_skills)
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                tokens = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                tokens = re.split(r"[,;|/\n]+", raw)
        else:
            tokens = re.split(r"[,;|/\n]+", raw)
    result = []
    for t in tokens:
        s = str(t).strip().strip('"\'\t').strip()
        if s and s.lower() not in ("error", "not specified", "none", "n/a", ""):
            result.append(s)
    return result


@app.get("/api/stats/skills")
def get_skills_stats(limit: int = Query(default=50, ge=1, le=200), user: dict = Depends(get_current_user)):
    """Return skill frequency data from the user's processed jobs, sorted by count."""
    df = db.load_processed_jobs(user["id"], is_one_off=False)
    if df.empty:
        return {"skills": [], "total_unique": 0, "total_jobs_analyzed": 0}

    df = df.astype(object).where(pd.notna(df), None)

    # Count raw occurrences, then merge case-insensitive duplicates
    raw_counts: collections.Counter = collections.Counter()
    for _, row in df.iterrows():
        for token in _parse_skills_field(row.get("skills")):
            raw_counts[token] += 1

    ci_merged: dict[str, int] = {}
    ci_key_map: dict[str, str] = {}
    for skill, count in raw_counts.items():
        key = skill.lower().strip()
        if key not in ci_key_map:
            ci_key_map[key] = skill
            ci_merged[skill] = count
        else:
            ci_merged[ci_key_map[key]] += count

    skills_list = sorted(
        [{"skill": s, "count": c} for s, c in ci_merged.items()],
        key=lambda x: -x["count"],
    )

def _studio_operation(function):
    from functools import wraps
    @wraps(function)
    def guarded(doc_id, req=None, user=None):
        folder = _resolved_safe_path(doc_id, user_documents_dir(user.get('username')))
        with document_lock(folder):
            source_path = next((os.path.join(folder, name) for name in ('document.typ', 'document.tex')
                                if os.path.exists(os.path.join(folder, name))), None)
            before = Path(source_path).read_text(encoding='utf-8') if source_path else ''
            expected = getattr(req, 'expected_source_hash', None)
            if expected and expected != digest(before):
                raise HTTPException(status_code=409, detail='Document changed. Reload before saving.')
            encoded = getattr(req, 'pdf_base64', None)
            if encoded:
                try:
                    decode_pdf(encoded)
                except (ValueError, OSError) as exc:
                    raise HTTPException(status_code=422, detail=str(exc))
            if source_path:
                snapshot = os.path.join(folder, 'history', digest(before) + os.path.splitext(source_path)[1])
                if not os.path.exists(snapshot):
                    atomic_write(snapshot, before)
            try:
                result = function(doc_id, req=req, user=user)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            after = Path(source_path).read_text(encoding='utf-8') if source_path else ''
            if source_path:
                snapshot = os.path.join(folder, 'history', digest(after) + os.path.splitext(source_path)[1])
                if not os.path.exists(snapshot):
                    atomic_write(snapshot, after)
            pdf = os.path.join(folder, 'document.pdf')
            if result.get('success') and (encoded or function.__name__ in ('compile_studio_document_api', 'ai_edit_studio_document')):
                if encoded or result.get('has_pdf'):
                    record_build(pdf, after, 'typst' if source_path and source_path.endswith('.typ') else 'latex', verified=not bool(encoded))
            result['source_hash'] = digest(after)
            result['pdf_current'] = bool(matching_build(pdf, after))
            return result
    return guarded


# --- CV Studio (Documents Workspace) Models & Endpoints ---

class CreateDocumentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    doc_type: str = Field(default="cv")  # "cv" or "letter"
    engine: Optional[str] = None  # "typst" or "latex"
    template_source: Optional[str] = None
    content: Optional[str] = None

class UpdateDocumentRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    pdf_base64: Optional[str] = None
    expected_source_hash: Optional[str] = None

class CompileDocumentRequest(BaseModel):
    content: Optional[str] = None
    pdf_base64: Optional[str] = None
    expected_source_hash: Optional[str] = None

class AiEditDocumentRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    selection: Optional[str] = None
    modelName: Optional[str] = None
    content: Optional[str] = None
    expected_source_hash: Optional[str] = None


@app.get("/api/documents/templates")
def list_available_templates(user: dict = Depends(get_current_user)):
    username = user.get("username")
    templates = []
    candidates = [
        {"id": "approved/cv.tex", "title": "[LaTeX] Reviewed default CV", "doc_type": "cv", "engine": "latex", "default": True},
        {"id": "base-typst/base-cv-moderner.typ", "title": "[Typst] ModernCV (moderner-cv)", "doc_type": "cv", "engine": "typst"},
        {"id": "base-typst/base-cv.typ", "title": "[Typst] Modern CV (Standard)", "doc_type": "cv", "engine": "typst"},
        {"id": "base-typst/base-cl.typ", "title": "[Typst] Modern Cover Letter", "doc_type": "letter", "engine": "typst"},
        {"id": "base-cv-tex/base-cv-industry.tex", "title": "[LaTeX] Industry CV (Standard)", "doc_type": "cv", "engine": "latex"},
        {"id": "base-cv-tex/base-cv-industry-compact.tex", "title": "[LaTeX] Industry CV (Compact, 9pt)", "doc_type": "cv", "engine": "latex"},
        {"id": "base-cv-tex/base-cv-research.tex", "title": "[LaTeX] Research CV (Standard)", "doc_type": "cv", "engine": "latex"},
        {"id": "base-cv-tex/base-cv-research-compact.tex", "title": "[LaTeX] Research CV (Compact, 9pt)", "doc_type": "cv", "engine": "latex"},
        {"id": "base-cl-tex/cl_template.tex", "title": "[LaTeX] Standard Cover Letter Template", "doc_type": "letter", "engine": "latex"},
        {"id": "base-cl-tex/main.tex", "title": "[LaTeX] Modern Cover Letter Template", "doc_type": "letter", "engine": "latex"},
    ]
    for cand in candidates:
        resolved = resolve_user_path(username, cand["id"])
        if os.path.exists(resolved):
            templates.append({
                "id": cand["id"],
                "title": cand["title"],
                "doc_type": cand["doc_type"],
                "engine": cand.get("engine", "latex"),
                "default": cand.get("default", False),
                "resolved_path": os.path.relpath(resolved, user_assets.BASE_DIR),
            })
    return {"templates": templates}


@app.get("/api/documents")
def list_studio_documents(user: dict = Depends(get_current_user)):
    username = user.get("username")
    docs_dir = user_documents_dir(username)
    os.makedirs(docs_dir, exist_ok=True)

    documents = []
    for entry in os.listdir(docs_dir):
        doc_dir = os.path.join(docs_dir, entry)
        if not os.path.isdir(doc_dir):
            continue
        meta_file = os.path.join(doc_dir, "meta.json")
        meta = {}
        if os.path.exists(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}

        doc_id = entry
        title = meta.get("title") or entry.replace("_", " ").title()
        doc_type = meta.get("doc_type") or "cv"
        updated_at = meta.get("updated_at")

        pdf_path = os.path.join(doc_dir, "document.pdf")
        has_pdf = os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        pdf_mtime = int(os.path.getmtime(pdf_path)) if has_pdf else 0

        previews = []
        for f in os.listdir(doc_dir):
            if f.startswith("preview") and f.endswith(".png"):
                previews.append(f)

        def _extract_page_num(fn):
            m = re.search(r'-(\d+)\.png$', fn)
            return int(m.group(1)) if m else 0
        previews.sort(key=_extract_page_num)

        engine = meta.get("engine") or ("typst" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "latex")

        documents.append({
            "id": doc_id,
            "title": title,
            "doc_type": doc_type,
            "engine": engine,
            "created_at": meta.get("created_at", datetime.now().isoformat()),
            "updated_at": updated_at or datetime.fromtimestamp(os.path.getmtime(doc_dir)).isoformat(),
            "has_pdf": has_pdf,
            "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={pdf_mtime}" if has_pdf else None,
            "preview_urls": [f"/api/download/documents/{doc_id}/{p}?v={pdf_mtime}" for p in previews],
            "preview_count": len(previews),
        })

    documents.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
    return {"documents": documents}


@app.post("/api/documents")
def create_studio_document(req: CreateDocumentRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    docs_dir = user_documents_dir(username)
    ensure_user_dirs(username)

    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', req.title.lower()).strip('_')
    if not slug:
        slug = "document"
    doc_id = f"{slug[:35]}_{uuid.uuid4().hex}"
    doc_dir = os.path.join(docs_dir, doc_id)
    os.makedirs(doc_dir, exist_ok=True)

    # Determine engine
    engine = req.engine
    if not engine:
        if (req.template_source and req.template_source.endswith(".typ")) or (
            req.content and ("#set " in req.content or "#let " in req.content)
        ):
            engine = "typst"
        else:
            engine = "latex"

    content = ""
    if req.content is not None and req.content.strip():
        content = req.content
    elif req.template_source:
        tmpl_path = resolve_user_path(username, req.template_source)
        if os.path.exists(tmpl_path):
            with open(tmpl_path, "r", encoding="utf-8") as f:
                content = f.read()
        if req.template_source == 'approved/cv.tex':
            store = reviewed_documents.evidence(username, load_cv_text(username))
            content = reviewed_documents.render_cv(store, list(store['facts']), engine)

    if not content:
        if engine == "typst":
            content = r"""// ==============================================================================
// Curriculum Vitae (Typst)
// ==============================================================================
#set page(paper: "a4", margin: (x: 2cm, y: 2cm))
#set text(font: ("Arial", "Helvetica Neue"), size: 10pt)

#align(center)[
  #text(size: 20pt, weight: "bold")[Your Name] \
  #v(0.1cm)
  #text(size: 9pt)[your.email\@example.com • Vienna, Austria]
]

#v(0.3cm)
== Experience
*Software Developer* \
Built scalable web applications and automated data workflows.
"""
        else:
            content = r"""\documentclass[10pt, a4paper]{article}
\usepackage[margin=2cm]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{hyperref}

\begin{document}
\section*{Curriculum Vitae}
\textbf{Name:} Your Name \\
\textbf{Email:} your.email@example.com

\subsection*{Experience}
\begin{itemize}
    \item Developed scalable software and automated workflows.
\end{itemize}

\end{document}
"""

    source_filename = "document.typ" if engine == "typst" else "document.tex"
    source_path = os.path.join(doc_dir, source_filename)
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(content)

    now_iso = datetime.now().isoformat()
    meta = {
        "id": doc_id,
        "title": req.title,
        "doc_type": req.doc_type,
        "engine": engine,
        "created_at": now_iso,
        "updated_at": now_iso,
        "template_source": req.template_source,
    }
    with open(os.path.join(doc_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    compile_ok, compile_log = compile_studio_document(doc_dir)
    pdf_path = os.path.join(doc_dir, "document.pdf")
    has_pdf = compile_ok and os.path.exists(pdf_path)
    now_ts = int(time.time())
    previews = []
    if has_pdf:
        gen_imgs = sorted([f for f in os.listdir(doc_dir) if f.startswith("preview") and f.endswith(".png")])
        if not gen_imgs:
            gen_imgs = convert_pdf_to_images(pdf_path, doc_dir, "preview")
        previews = [f"/api/download/documents/{doc_id}/{p}?v={now_ts}" for p in gen_imgs]

    err_diag = None
    if not compile_ok:
        err_diag = parse_typst_error(compile_log) if engine == "typst" else parse_pdflatex_error(compile_log)
        with open(os.path.join(doc_dir, "compile_error.json"), "w", encoding="utf-8") as f:
            json.dump(err_diag, f, indent=2)

    return {
        "id": doc_id,
        "title": req.title,
        "doc_type": req.doc_type,
        "engine": engine,
        "created_at": now_iso,
        "updated_at": now_iso,
        "content": content,
        "source_hash": digest(content),
        "pdf_current": bool(matching_build(pdf_path, content)),
        "has_pdf": has_pdf,
        "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={now_ts}" if has_pdf else None,
        "preview_urls": previews,
        "error": err_diag,
    }


@app.get("/api/documents/{doc_id}")
def get_studio_document(doc_id: str, user: dict = Depends(get_current_user)):
    username = user.get("username")
    doc_dir = _resolved_safe_path(doc_id, user_documents_dir(username))
    if not os.path.exists(doc_dir) or not os.path.isdir(doc_dir):
        raise HTTPException(status_code=404, detail="Document not found")

    meta = {}
    meta_file = os.path.join(doc_dir, "meta.json")
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    engine = meta.get("engine") or ("typst" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "latex")
    source_filename = "document.typ" if engine == "typst" else "document.tex"
    source_path = os.path.join(doc_dir, source_filename)
    if not os.path.exists(source_path):
        alt_filename = "document.tex" if engine == "typst" else "document.typ"
        alt_path = os.path.join(doc_dir, alt_filename)
        if os.path.exists(alt_path):
            source_path = alt_path
            engine = "latex" if alt_filename == "document.tex" else "typst"

    content = ""
    if os.path.exists(source_path):
        with open(source_path, "r", encoding="utf-8") as f:
            content = f.read()

    pdf_path = os.path.join(doc_dir, "document.pdf")
    has_pdf = os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
    pdf_mtime = int(os.path.getmtime(pdf_path)) if has_pdf else 0

    previews = []
    for f in os.listdir(doc_dir):
        if f.startswith("preview") and f.endswith(".png"):
            previews.append(f)
    def _extract_num(fn):
        m = re.search(r'-(\d+)\.png$', fn)
        return int(m.group(1)) if m else 0
    previews.sort(key=_extract_num)

    error_diag = None
    err_file = os.path.join(doc_dir, "compile_error.json")
    if os.path.exists(err_file):
        try:
            with open(err_file, "r", encoding="utf-8") as f:
                error_diag = json.load(f)
        except Exception:
            pass

    return {
        "id": doc_id,
        "title": meta.get("title", doc_id),
        "doc_type": meta.get("doc_type", "cv"),
        "engine": engine,
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "content": content,
        "source_hash": digest(content),
        "pdf_current": bool(matching_build(pdf_path, content)),
        "has_pdf": has_pdf,
        "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={pdf_mtime}" if has_pdf else None,
        "preview_urls": [f"/api/download/documents/{doc_id}/{p}?v={pdf_mtime}" for p in previews],
        "error": error_diag,
    }


@app.put("/api/documents/{doc_id}")
@_studio_operation
def update_studio_document(doc_id: str, req: UpdateDocumentRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    doc_dir = _resolved_safe_path(doc_id, user_documents_dir(username))
    if not os.path.exists(doc_dir) or not os.path.isdir(doc_dir):
        raise HTTPException(status_code=404, detail="Document not found")

    meta_file = os.path.join(doc_dir, "meta.json")
    meta = {}
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    if req.title:
        meta["title"] = req.title
    meta["updated_at"] = datetime.now().isoformat()

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if req.content is not None:
        engine = meta.get("engine") or ("typst" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "latex")
        source_filename = "document.typ" if engine == "typst" else "document.tex"
        atomic_write(os.path.join(doc_dir, source_filename), req.content)

    if req.pdf_base64:
        try:
            pdf_bytes = decode_pdf(req.pdf_base64)
            atomic_write(os.path.join(doc_dir, "document.pdf"), pdf_bytes)
            err_file = os.path.join(doc_dir, "compile_error.json")
            if os.path.exists(err_file):
                try:
                    os.remove(err_file)
                except OSError:
                    pass
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not save PDF: {e}") from e

    return {"success": True, "updated_at": meta["updated_at"]}


@app.post("/api/documents/{doc_id}/compile")
@_studio_operation
def compile_studio_document_api(doc_id: str, req: CompileDocumentRequest = None, user: dict = Depends(get_current_user)):
    username = user.get("username")
    doc_dir = _resolved_safe_path(doc_id, user_documents_dir(username))
    if not os.path.exists(doc_dir) or not os.path.isdir(doc_dir):
        raise HTTPException(status_code=404, detail="Document not found")

    meta_file = os.path.join(doc_dir, "meta.json")
    meta = {}
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    engine = meta.get("engine") or ("typst" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "latex")
    source_filename = "document.typ" if engine == "typst" else "document.tex"
    source_path = os.path.join(doc_dir, source_filename)
    if req and req.content is not None:
        atomic_write(source_path, req.content)

    for f in os.listdir(doc_dir):
        if f.startswith("preview") and f.endswith(".png"):
            try:
                os.remove(os.path.join(doc_dir, f))
            except OSError:
                pass

    err_file = os.path.join(doc_dir, "compile_error.json")
    now_ts = int(time.time())
    pdf_path = os.path.join(doc_dir, "document.pdf")

    # If client supplied pre-compiled PDF bytes (pure WASM in browser)
    if req and req.pdf_base64:
        try:
            pdf_bytes = decode_pdf(req.pdf_base64)
            atomic_write(pdf_path, pdf_bytes)
            if os.path.exists(err_file):
                try:
                    os.remove(err_file)
                except OSError:
                    pass
            gen_imgs = convert_pdf_to_images(pdf_path, doc_dir, "preview")
            preview_urls = [f"/api/download/documents/{doc_id}/{p}?v={now_ts}" for p in gen_imgs]
            return {
                "success": True,
                "has_pdf": True,
                "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={now_ts}",
                "preview_urls": preview_urls,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "has_pdf": False,
                "pdf_url": None,
                "preview_urls": [],
                "error": {"message": f"Failed to save client PDF: {e}"},
            }

    # Fallback to server-side CLI compilation
    compile_ok, compile_log = compile_studio_document(doc_dir)
    has_pdf = compile_ok and os.path.exists(pdf_path)

    if compile_ok and has_pdf:
        if os.path.exists(err_file):
            try:
                os.remove(err_file)
            except OSError:
                pass
        gen_imgs = sorted([f for f in os.listdir(doc_dir) if f.startswith("preview") and f.endswith(".png")])
        if not gen_imgs:
            gen_imgs = convert_pdf_to_images(pdf_path, doc_dir, "preview")
        preview_urls = [f"/api/download/documents/{doc_id}/{p}?v={now_ts}" for p in gen_imgs]
        return {
            "success": True,
            "has_pdf": True,
            "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={now_ts}",
            "preview_urls": preview_urls,
            "error": None,
        }
    else:
        err_diag = parse_typst_error(compile_log) if engine == "typst" else parse_pdflatex_error(compile_log)
        with open(err_file, "w", encoding="utf-8") as f:
            json.dump(err_diag, f, indent=2)
        return {
            "success": False,
            "has_pdf": False,
            "pdf_url": None,
            "preview_urls": [],
            "error": err_diag,
        }


@app.post("/api/documents/{doc_id}/ai-edit")
@_studio_operation
def ai_edit_studio_document(doc_id: str, req: AiEditDocumentRequest, user: dict = Depends(get_current_user)):
    username = user.get("username")
    doc_dir = _resolved_safe_path(doc_id, user_documents_dir(username))
    if not os.path.exists(doc_dir) or not os.path.isdir(doc_dir):
        raise HTTPException(status_code=404, detail="Document not found")

    meta_file = os.path.join(doc_dir, "meta.json")
    meta = {}
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    engine = meta.get("engine") or ("typst" if os.path.exists(os.path.join(doc_dir, "document.typ")) else "latex")
    source_filename = "document.typ" if engine == "typst" else "document.tex"
    source_path = os.path.join(doc_dir, source_filename)
    if not os.path.exists(source_path):
        raise HTTPException(status_code=400, detail=f"{source_filename} not found")
    with open(source_path, "r", encoding="utf-8") as f:
        current_code = f.read()
    if req.content is not None:
        current_code = req.content

    model_name = _effective_ai_model(req.modelName, user)
    if engine == "typst":
        new_code = ai_surgical_edit_typst(
            typst_code=current_code,
            instruction=req.instruction,
            selection=req.selection,
            model_name=model_name,
            user=username,
        )
    else:
        new_code = ai_surgical_edit_latex(
            tex_code=current_code,
            instruction=req.instruction,
            selection=req.selection,
            model_name=model_name,
            user=username,
        )
    if not new_code:
        raise HTTPException(status_code=500, detail=f"AI edit failed to produce valid {engine.title()}")

    atomic_write(source_path, new_code)

    compile_ok, compile_log = compile_studio_document(doc_dir)
    pdf_path = os.path.join(doc_dir, "document.pdf")
    has_pdf = compile_ok and os.path.exists(pdf_path)
    now_ts = int(time.time())

    previews = []
    err_diag = None
    err_file = os.path.join(doc_dir, "compile_error.json")
    if has_pdf:
        if os.path.exists(err_file):
            try: os.remove(err_file)
            except OSError: pass
        for f in os.listdir(doc_dir):
            if f.startswith("preview") and f.endswith(".png"):
                try: os.remove(os.path.join(doc_dir, f))
                except OSError: pass
        gen_imgs = sorted([f for f in os.listdir(doc_dir) if f.startswith("preview") and f.endswith(".png")])
        if not gen_imgs:
            gen_imgs = convert_pdf_to_images(pdf_path, doc_dir, "preview")
        previews = [f"/api/download/documents/{doc_id}/{p}?v={now_ts}" for p in gen_imgs]
    else:
        err_diag = parse_typst_error(compile_log) if engine == "typst" else parse_pdflatex_error(compile_log)
        with open(err_file, "w", encoding="utf-8") as f:
            json.dump(err_diag, f, indent=2)

    return {
        "success": True,
        "content": new_code,
        "engine": engine,
        "has_pdf": has_pdf,
        "pdf_url": f"/api/download/documents/{doc_id}/document.pdf?v={now_ts}" if has_pdf else None,
        "preview_urls": previews,
        "error": err_diag,
    }


@app.delete("/api/documents/{doc_id}")
def delete_studio_document(doc_id: str, user: dict = Depends(get_current_user)):
    username = user.get("username")
    doc_dir = _resolved_safe_path(doc_id, user_documents_dir(username))
    if not os.path.exists(doc_dir) or not os.path.isdir(doc_dir):
        raise HTTPException(status_code=404, detail="Document not found")
    shutil.rmtree(doc_dir, ignore_errors=True)
    return {"success": True}


# Serve the built frontend from the same origin as the API. Vite remains available for development.
_frontend = Path(__file__).resolve().parent / "webapp" / "dist"
if _frontend.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="webapp")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
