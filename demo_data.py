"""Seed a new demo directory from fictional fixtures. No model calls or network access."""
import json
from datetime import date, timedelta
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "examples" / "demo"


def seed(destination: Path) -> None:
    """Create demo data in an empty directory. Refuse to replace existing data."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError(f"Demo destination must be empty: {destination}")
    # Set these before importing storage modules. The launcher runs this in a separate process.
    import os
    os.environ["JOBWEAVER_DATA_DIR"] = str(destination)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    import auth
    import db
    import user_assets
    if Path(user_assets.DATA_DIR) != destination or Path(db.DB_PATH).parent != destination:
        raise ValueError("Storage modules already use a different data directory. Start a new process.")
    db.init_db()
    user_id = db.create_user("demo", auth.hash_password("demo"), display_name="Alex Example")["id"]
    profile = destination / "profiles" / "demo"
    user_assets.ensure_user_dirs("demo")
    shutil.copy2(ROOT / "examples" / "career_record.example.yaml", profile / "career_record.yaml")
    config = json.loads((ROOT / "scraper_config.json").read_text())
    config["openrouter_model"] = "demo/prepared-example"
    config["auto_generate"].update({"document_engine": "latex", "enabled": False})
    (profile / "scraper_config.json").write_text(json.dumps(config, indent=2))
    (profile / "ui_preferences.json").write_text(json.dumps({"theme": "loden-light", "font": "fira-sans"}))
    from job_policy import fingerprint, apply_rating
    from user_assets import load_effective_cv
    shutil.copy2(FIXTURES / "standing-notes.md", profile / "standing_notes.txt")
    cv_fingerprint = fingerprint(load_effective_cv("demo"), config["openrouter_model"])
    jobs = json.loads((FIXTURES / "jobs.json").read_text())
    for job in jobs:
        job["date_scraped"] = (date.today() - timedelta(days=job.pop("days_ago"))).isoformat()
        if job["status"] in ("applied", "interview", "offer", "rejected"):
            job["application_date"] = job["date_scraped"]
            job["applied"] = True
        job.update(processed=True, analysis_state="complete", analysis_model="demo/prepared-example",
                   analysis_fingerprint=cv_fingerprint, analysis_demo=True)
        apply_rating(job, config, cv_fingerprint)
        documents = FIXTURES / "documents" / job["id"]
        if documents.is_dir():
            folder = f"{job['company'].replace(' ', '')}_{job['id']}"
            shutil.copytree(documents, profile / "drafts" / folder)
            output = profile / "outputs" / folder
            output.mkdir()
            shutil.copy2(documents / "cv.pdf", output / f"CV-{job['company'].replace(' ', '')}.pdf")
            shutil.copy2(documents / "cl.pdf", output / f"Letter-{job['company'].replace(' ', '')}.pdf")
        db.upsert_job(job, user_id=user_id)
    db.add_log("Loaded 15 fictional postings. Ratings and letters are prepared examples, not live model results.",
               user_id=user_id)
