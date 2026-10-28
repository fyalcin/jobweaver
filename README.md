# Jobweaver

A self-hosted workspace for collecting job postings, checking how well they fit your background, and drafting applications from facts you can actually defend.

![A fictional Jobweaver workflow: jobs, fit analysis, evidence and application PDFs](docs/media/hero.gif)

*The demo uses fictional postings and hand-prepared requirement checks and documents ([smooth 30fps MP4 clip](docs/media/hero.mp4)).*

Searching for a technical role usually means juggling browser tabs, a spreadsheet, and a folder of half-edited CV and cover-letter drafts. Worse, if you ask a language model to tailor an application from a raw CV, it tends to exaggerate. A script you adapted becomes a platform you "architected", and hard requirements you do not meet get smoothed over with generic buzzwords.

I built Jobweaver to keep the posting, fit check, application stage, and document history in one place, and to put strict guardrails around what the model is allowed to claim. You can pull in postings by pasting text, giving a URL, polling employer feeds, or running Apify connectors. Jobweaver checks each posting against your CV, tracks your applications through seven stages from `New` to `Offer` or `Rejected`, compiles PDFs with Typst or LaTeX while keeping earlier revisions, and exposes four read-only MCP tools if you want to query your pipeline from an assistant. Each account on the server has its own postings, profile, settings, and document library.

## Project status

Early release (October 2026). Jobweaver is meant to run on your own computer or home server for yourself and a few people you trust. It has per-account data, isolated document compilers, request limits, and daily model quotas, but it has not had an external security review and is not hardened for the open internet. Run it on localhost or a private network such as Tailscale or WireGuard, and read [Known limitations](#known-limitations) before relying on it.

<details>
<summary>Four views of the demo</summary>

![Job explorer](docs/media/jobs.png)

![Fit analysis with strengths and gaps](docs/media/fit.png)

![Prepared letter and its evidence](docs/media/evidence.png)

![Application analytics](docs/media/analytics.png)

</details>

## What makes it different

Instead of feeding a free-form CV straight into a prompt, you can maintain a structured career record that separates work you authored yourself, code you adapted from someone else, basic familiarity, and AI-built systems you specified and directed. The document pipeline uses those distinctions when it selects and phrases evidence. The CV renderer keeps your approved wording intact. When the letter writer drafts a cover letter, it has to cite specific claims from your record, and a separate verifier model checks the draft against those claims before you see it. That catches a lot of overreach, though it is still no substitute for reading the final letter yourself before sending it.

Fit ratings work the same way. Rather than asking a model to invent an opaque 0 to 100 score, Jobweaver asks it to judge each requirement in the posting as `shown`, `related`, or `missing` in your CV, backed by exact quotes from both texts. Fixed rules in Python, not the language model, then turn that checklist into a rating: `Great`, `Good`, `Decent`, `Stretch`, or `Poor`. Preference conflicts from your standing notes can lower that rating, and a firm conflict or eligibility blocker marks the job as `Blocked` (postings with no checkable requirements stay `Unrated` unless a blocker applies). Requirement checks are still model judgements rather than hiring probabilities, and whenever you update your CV or switch models, older analyses are marked as historical until you click **Re-rate** on a job.

The Jobs view groups postings by rating so the strongest matches stay at the top while `Poor` and `Blocked` roles start folded out of the way. Stage tabs, search, and a Filter panel narrow the list, and clicking any row opens its requirement quotes and document studio.

## Quick start

### Try the demo

You need Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22.12 or later, npm, and Make. You do not need API keys, a browser scraper, or a local TeX/Typst installation to run the demo.

```bash
git clone https://github.com/fyalcin/jobweaver.git
cd jobweaver
uv sync --frozen
npm --prefix webapp ci
make demo
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001) and click **Explore the demo** (or sign in with `demo` / `demo`).

The demo comes loaded with a fictional applicant (Alex Example), 15 fictional postings across all rating tiers, and three prepared CV and cover-letter pairs. All requirement checks, letters, and evidence links in the demo are hand-prepared examples; no live model or automated verifier ran to produce them. You can filter jobs, inspect the evidence tables, switch color palettes and fonts in Settings, and download the compiled PDFs, while write actions, scraping, and model calls stay disabled.

Press `Ctrl+C` when you are done. Each `make demo` run uses a fresh temporary directory and never touches your real database or profiles. If port 8001 is busy, build the frontend once and pick another port:

```bash
uv run --frozen python scripts/demo.py --port 8002
```

### Use your own data

After running the dependency setup above, copy the example environment file, set an administrator password, build the frontend, and start the server:

```bash
cp .env.example .env
uv run python manage_users.py passwd admin
npm --prefix webapp run build
uv run python server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and sign in as `admin`. Put your CV text in **Personalize** and choose your models and collection sources in **Settings**. Scoring and document generation stay off until your account has its own CV (either in Personalize or in a career record), so you will not accidentally score jobs against the fictional template. If an analysis fails, it shows up on the Jobs tab with the failure reason and a retry button. To add another person to your instance, run `uv run python manage_users.py add USERNAME`.

If you want documents built from verified claims, copy `examples/career_record.example.yaml` to `profiles/admin/career_record.yaml`, replace the fictional entries with your own history, and validate the file before generating documents:

```bash
uv run python career_record.py check profiles/admin/career_record.yaml
```

The [career record format guide](docs/career-record/FORMAT.md) explains how claims, ownership levels, and approved wording work. Note that generating a German CV or cover letter requires approved German wording on the claims that document uses.

### Document tools

Typst is the default document engine and can preview and export PDFs directly in the browser. LaTeX remains an option if you prefer it, and Typst users do not need a LaTeX installation. While the demo ships with pre-compiled PDFs, server-side generation, validation, and finalization on a real instance require native command-line tools on Linux:

| Purpose | Installed tools |
|---|---|
| Native tool isolation | Linux with Bubblewrap (`bwrap`), `prlimit`, and enabled user namespaces |
| PDF validation and previews | Poppler (`pdfinfo`, `pdftoppm`, `pdftotext`) |
| Typst documents | Typst CLI 0.14 or later |
| LaTeX documents | `pdflatex` and packages used by the template, including Source Sans Pro |
| Legacy LaTeX comparison | `latexdiff` |

When you finalize an edited document, the server checks the saved source with a native build inside a Bubblewrap sandbox. If a build fails, Jobweaver keeps the last good PDF. Native builds refuse to run without sandbox isolation; there is no un-isolated fallback, and native workers on non-Linux server OSes are not supported yet. Keep your checkout and personal data outside system or compiler installation directories. Each sandboxed build sees only its own document inputs and public template assets, never server credentials or other accounts' profiles, and any build that writes more than 4 MiB of output or 256 KiB of diagnostics is terminated.

## Configuration

Credentials live in `.env` and personal files live in `profiles/`. Both stay outside Git.

| Setting | Use |
|---|---|
| `OPENROUTER_API_KEY` | Hosted models through OpenRouter |
| `CUSTOM_MODEL_BASE_URL` | OpenAI-compatible endpoint, including its `/v1` path |
| `CUSTOM_MODEL_API_KEY` | Endpoint credential, if required |
| `APIFY_API_TOKEN` | Optional Apify job connectors |
| `JOBWEAVER_DATA_DIR` | Separate directory for the SQLite database and `profiles/` |
| `JOBWEAVER_ALLOWED_HOSTS` | Additional exact server hostnames or IPs (loopback is allowed by default) |
| `JOBWEAVER_HTTPS_ONLY` | Set to `1` behind HTTPS to enable `Secure` cookies and refuse plain HTTP |

Configure at least one model route for scoring and letters. Models from a custom endpoint show up as `custom/<model>` in Settings. Because scoring many job postings has a very different cost profile from drafting a cover letter, scoring and document generation use separate model selections. Settings also shows which model verifies cover letters; by default it uses your custom writer's endpoint or a hosted default, unless you pick a verifier explicitly. Company Notes & Research uses a separate hosted Perplexity Sonar call when you click **Fetch notes** on a job.

The interface defaults to the Loden Light palette with a Light/Dark toggle in the sidebar, alongside seven community palettes (Kanagawa, Catppuccin, Rosé Pine, and Nord) and configurable typography in Settings (Fira Sans and Fira Mono by default, loaded from Google Fonts with local system fallbacks when offline). Appearance choices save per account, or in `localStorage` during the demo.

User sessions are stored as hashes in SQLite and revoked on sign-out or password change. Sign-in attempts are rate-limited (returning HTTP 429 with a retry delay), and deleting an account retires its username so a new user can never inherit retained profile files. If you want to store your database and `profiles/` outside the repository, create that directory first and export `JOBWEAVER_DATA_DIR` before running any command; back up both your data directory and `.env`.

### Job sources and daily collection

Built-in employer feeds support Greenhouse, Personio, SmartRecruiters, and SuccessFactors. Copy `examples/companies.example.json` to `profiles/<user>/companies.json` and keep the employers you want to poll (the example file lists real public employer feeds, while the demo uses fictional postings). If you have an Apify account, the LinkedIn and Karriere.at connectors map their results into the same internal posting schema. Every imported posting passes through the [Posting gate](docs/adr/0006-one-posting-schema-with-a-gate.md), and URL imports read `schema.org/JobPosting` data over pinned public IPs with strict byte, redirect, and timeout caps (see [ARCHITECTURE.md](ARCHITECTURE.md#collection-and-analysis)).

Daily collection is off by default. Once you enable your sources in `scraper_config.json` and check your model selection, you can run a collection manually or from cron:

```bash
uv run python daily_scraper.py --user admin
```

```cron
0 8 * * * cd /path/to/jobweaver && /path/to/uv run --frozen python daily_scraper.py --user admin >> /path/to/jobweaver/daily.log 2>&1
```

The daily script collects and scores postings, and can automatically draft documents for eligible roles whose current match rating is at least `auto_generate.min_rating` (default `good`). Historical numeric scores are never auto-converted or used for automatic document generation. The script never submits applications or sends external notifications on its own.

### Quotas, queues, and safety limits

Because Jobweaver can run unattended cron jobs and multi-step document pipelines, it enforces local resource caps so a stuck process or an oversized batch cannot overwhelm your machine or run up unbounded API calls.

Run a single backend worker per data directory (a second worker will refuse to start while the first holds the directory lock). Scraping, reprocessing, and batch document generation pass through a bounded background queue that runs at most two jobs at once and holds up to eight waiting jobs, with at most one active and two admitted jobs per account. If the server stops or crashes mid-run, unfinished jobs are marked as interrupted on the next startup rather than replaying silently. Across all processes sharing a data directory, file locks in `.jobweaver-capacity/` cap concurrent activity at four simultaneous model calls and two native compiler builds.

Every operation also has a strict call and time budget: interactive or CLI document builds may make up to 16 model POSTs within 10 minutes, while collection, reprocessing, batch generation, and scheduled runs may make up to 120 POSTs within 30 minutes. On top of per-operation caps, each account has a daily quota of 300 model requests and 2,400,000 requested output tokens per calendar day in `JOBWEAVER_QUOTA_TZ` (configurable globally via `JOBWEAVER_QUOTA_REQUESTS` and `JOBWEAVER_QUOTA_OUTPUT_TOKENS` in `.env`, or per user via `manage_users.py`):

```bash
uv run python manage_users.py quota USERNAME --attempts 100 --output-tokens 800000   # or --default
uv run python manage_users.py usage [USERNAME] [--day YYYY-MM-DD]
```

Every attempted request counts against the quota, including failed or cancelled calls. The `model_calls` table logs token counts, byte sizes, endpoint hostnames, and reported costs (storing unknown cost as unknown, never zero, and pruning rows older than 400 days), without ever storing prompts, responses, CV text, or API keys. Keep in mind that request and token quotas are not a hard dollar limit: actual cost depends on which model you pick and how large your prompts are, and providers can still bill for failed or cancelled requests. Set a spending cap directly on your model provider key as well. Full input size limits, feed pagination caps, and HTTP deadlines are documented in [ARCHITECTURE.md](ARCHITECTURE.md#operation-budgets).

### Read-only MCP

If you use an MCP-compatible assistant, `jobweaver_mcp.py` exposes four read-only tools (`list_jobs`, `get_job`, `get_pipeline`, and `list_documents`) over local `stdio` while the web backend is running. Store your password in a `chmod 600` file outside the repository and point your MCP client at:

```bash
uv run python jobweaver_mcp.py --url http://127.0.0.1:8000 --username admin --password-file /absolute/path/to/password-file
```

The MCP tools respect your account permissions and mark scraped job descriptions as untrusted text so prompt-injection attempts inside job postings are easier for the assistant to spot.

## How it works

```text
Postings -> mappings -> Posting gate -> SQLite -> analysis and application pipeline
Career record -> CV renderer / letter writer -> evidence checks -> PDF build -> saved revision
Assistant -> read-only stdio MCP -> authenticated web API
```

The backend is written in Python with FastAPI and SQLite, and the frontend uses React and Vite. See [ARCHITECTURE.md](ARCHITECTURE.md) for the module map, data boundaries, and security model, and [GLOSSARY.md](GLOSSARY.md) for how terms like *career record*, *claim*, and *Posting gate* are used across the codebase.

## How this was built

I ([Fırat Yalçın](https://github.com/fyalcin)) designed the workflows, specified the architecture and verification rules, directed the implementation, and use Jobweaver for my own job search. AI coding agents wrote most of the application code under my direction. I am sharing the repository as a working, self-hosted system and a record of its design decisions, not as a claim that I hand-wrote its React frontend or every backend module myself.

## Development

```bash
make dev
uv run --offline --no-sync python scripts/test_isolated.py
node scripts/test_document_frontend.mjs
npm --prefix webapp run build
```

`make dev` starts the FastAPI server on port 8000 and Vite on port 5173. Always run backend tests through `scripts/test_isolated.py`, which copies the source tree into a temporary directory and uses synthetic data; running `pytest` or `unittest` directly in a live checkout can initialize or migrate your real database.

## Known limitations

- Quote verification confirms that an excerpt appears verbatim in the posting or your CV, but the model can still miss requirements, misjudge transferable experience, or count differently worded duplicates twice.
- Model calls go to OpenRouter or your configured OpenAI-compatible endpoint, which means postings, CV text, and draft documents are sent to that provider. A strict local-only mode and an in-app data-destinations view are planned.
- The web UI loads fonts from Google Fonts when online (with local system fallbacks offline); self-hosted fonts and a Content-Security-Policy header are planned.
- There is no in-app session list or "sign out other devices" button yet, and MCP uses a password file rather than scoped per-client tokens.
- Daily model quotas count requests and tokens rather than dollars; use your provider's billing settings for a hard monetary ceiling.
- There is no one-click export/restore command yet, so back up your data directory and `.env` directly.
- Server-side PDF builds require Linux with Bubblewrap and user namespaces, though browser-based Typst preview and PDF download work anywhere.
- The cover-letter verifier does not have a measured catch rate against a labelled benchmark yet. Read every letter before you send it.

## Roadmap

- Local-only model mode, an in-app data-destinations panel, and cached model lists.
- Self-hosted web fonts and a Content-Security-Policy header.
- Active session management and scoped read-only tokens for MCP clients.
- Built-in backup export/restore, packaging, and CI workflows.
- Declarative source mappings and additional employer feed connectors.
- Hosted read-only demo instance.
- Benchmark evaluation of the cover-letter verifier against labelled examples.

## Licence

[MIT](LICENSE). Bundled fonts, Typst packages, and other vendored assets keep their own licences; see [THIRD_PARTY.md](THIRD_PARTY.md).
