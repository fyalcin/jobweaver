# Architecture

Jobweaver is a Python/FastAPI backend with a React/Vite frontend and SQLite storage.
Each account owns its job list, profile configuration and document files.

## Modules

| Module | Responsibility |
|---|---|
| `server.py` | Authenticated API, background tasks, document lifecycle and optional built frontend |
| `db.py` | SQLite schema, user-scoped job queries and persistent task records |
| `auth.py` | Salted PBKDF2 passwords and HMAC-signed session cookies |
| `user_assets.py` | Profile paths, root template fallback and effective scoring CV |
| `postings.py` | Posting schema, validation gate and rejection counts |
| `scrapers.py` | Apify mappings, collection orchestration and model analysis |
| `company_feeds.py` | Greenhouse, Personio, SmartRecruiters and SuccessFactors readers |
| `safe_fetch.py`, `job_jsonld.py` | Public URL checks and schema.org JobPosting extraction |
| `job_policy.py`, `analysis_validation.py` | Analysis structure, eligibility, scores and fingerprints |
| `generators.py` | Model transport, PDF builds and preview conversion |
| `career_record.py`, `career_cv.py` | Career-record validation, scoring text and deterministic CV rendering |
| `reviewed_documents.py` | Claim selection, letter planning/writing and evidence checks |
| `document_artifacts.py` | Source/PDF hashes, build records and atomic publication |
| `jobweaver_mcp.py` | Four read-only tools over authenticated HTTP, exposed through stdio |
| `daily_scraper.py` | Optional scheduled collection and scoring, with no notifications |
| `demo_mode.py`, `demo_data.py` | Demo restrictions, read-only document responses and fictional seed data |

The frontend groups screens in `webapp/src/components/tabs/`, shared controls in `components/`, stateful API
workflows in `hooks/`, and document parsing/compilation support in `services/` and `workers/`.

## Storage and authentication

`JOBWEAVER_DATA_DIR` selects the database, `profiles/` directory and `.session_secret` location.
The default is the checkout. Export this variable before starting Python. Create the directory first.
Templates and examples always come from the checkout.

SQLite stores users, jobs, scraping logs and persistent background tasks. Jobs use `(user_id, id)` as their
primary key. Indexed columns support filtering. The JSON `data` column retains the complete job record.
All application queries scope jobs, tasks and logs to the authenticated user.
Legacy Telegram identity columns remain for database compatibility. No notification integration ships.

Passwords use PBKDF2-HMAC-SHA256 with random salts and 200,000 iterations.
An HttpOnly, SameSite=Lax cookie holds a signed user/expiry token. Sessions last 30 days.
The signing secret is generated in the data directory and stays outside Git.
Changing a password does not revoke existing cookies. The current server config uses non-Secure cookies for local HTTP.

Personal data lives under `profiles/<username>/`: career records, CV text, templates, configuration,
standing notes, preferences, drafts, outputs and the document library. Missing templates fall back to root samples.
Profile writes target the user's directory. They do not replace root templates.

## Collection and analysis

Connectors fetch source records. Mappings convert them to the Posting schema.
The gate requires the source's own ID, source, URL, title, company and description.
It removes unknown fields and reports rejected records. Optional malformed dates or salaries become empty.
Existing stored jobs are not revalidated. See ADR-0006 for the contract.

URL import checks public HTTP(S) destinations and redirects. It reads JSON-LD first, then page heuristics.
The request identifies itself as Jobweaver. It does not pretend to be a browser.

New jobs are saved before analysis. Failed analysis remains retryable.
Analysis includes language requirements, salary, skills, summary and structured match reasoning.
A fingerprint identifies the CV text and model. When those inputs change, old analysis can be shown as stale.
Scores are uncalibrated model judgments, not probabilities.

Model calls use OpenRouter or an OpenAI-compatible endpoint. `custom/` selects the custom route.
Custom endpoints use standard request parameters with fallbacks for structured-output support.
Scoring and documents resolve separate model settings. The public copy contains no `agy/` model route.

## Documents

A career record stores approved facts, claim ownership, role families, constraints and optional German wording.
The record format and validation rules are in `docs/career-record/FORMAT.md`.
CV rendering preserves approved claims. Letter generation plans evidence, writes cited paragraphs and asks
an independently selected model to check statements against those claims. Deterministic checks also examine
unsupported terms, numbers and length. A failed verifier does not silently publish a letter.

Native Typst or LaTeX builds run in fresh workspaces with timeouts. Poppler validates PDFs and creates previews.
Build manifests bind source hashes to PDF hashes. Finalization publishes an immutable source/PDF revision only
when a matching native build exists. Failed builds preserve the last good PDF and return diagnostics.
Browser Typst compilation provides previews, not proof of native source/PDF correspondence.

`GET /api/jobs/{id}/published-documents` lists existing publications without generating files.
The normal editor's `GET /api/jobs/{id}/documents` can create previews and initial version records.
The demo uses a separate read-only response for that route.

## Demo

`make demo` builds the frontend and starts `scripts/demo.py` on `127.0.0.1:8001`.
The launcher seeds an empty temporary directory, then starts one Uvicorn process with `JOBWEAVER_DEMO=1`.
It disables dotenv loading and removes credential variables from the server environment.
The directory contains the fictional applicant, 15 postings and three application sets from `examples/demo/`.
The seed refuses nonempty directories. Shutdown stops the child before removing temporary data.
A new launch resets the demo.

Demo HTTP middleware permits GET, HEAD and OPTIONS plus POST login/logout.
Every other write request returns 403. Model calls, scraping and the daily task also refuse demo execution.
The model-list endpoint returns a prepared label without contacting providers.
Document reads use bundled sources, PDFs and previews without a compiler.
Theme changes stay in the visitor's browser. Demo preferences never change the shared profile.

Scores and documents are hand-prepared examples. The interface states that no live model or verifier ran.
Regenerate document fixtures with `scripts/build_demo_documents.py` using installed LaTeX and Poppler.
Normal demo use requires neither tool.

## Runtime and verification

`make dev` runs FastAPI on localhost:8000 and Vite on localhost:5173.
Vite proxies `/api` to the backend. A built `webapp/dist/` is also served directly by FastAPI.
The default host binds only to loopback. Public hosting requires a separate deployment review.

Run Python tests through `scripts/test_isolated.py`. It copies source and fictional fixtures into a temporary
directory, disables dotenv and blocks external Python network connections before importing the server.
Never run direct discovery in a checkout containing real data. The demo integration test checks authentication,
all 15 postings, prepared downloads, refusal of writes, no compiler/network calls during reads, and unchanged files.
Frontend regressions run through `scripts/test_document_frontend.mjs`.

## Known limitations

- Letter verification has no measured catch rate on labelled examples. Read letters before sending.
- URL checks resolve DNS before the HTTP client resolves it again. DNS rebinding remains possible.
  The demo blocks URL import. Exposing normal URL import publicly needs connection pinning or equivalent protection.
- Compiler timeouts are not an operating-system sandbox. Native compilation assumes trusted local users.
- Document locks coordinate one Python process. Multiple backend workers need shared locking.
- Cookies have no per-client revocation. MCP uses an existing account password file until the token overhaul.
- Google Fonts can load from external servers. The UI remains usable with system font fallbacks when offline.
