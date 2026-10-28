# Architecture

Jobweaver is a Python/FastAPI backend with a React/Vite frontend and SQLite storage.
Each account owns its job list, profile configuration and document files.

## Modules

| Module | Responsibility |
|---|---|
| `server.py` | Authenticated API, background tasks, document lifecycle and optional built frontend |
| `db.py` | SQLite schema, user-scoped job queries and persistent task records |
| `background_queue.py` | Finite persistent-operation admission, fair dispatch, cancellation and backend ownership |
| `auth.py` | Salted PBKDF2 passwords, hashed revocable sessions and sign-in throttling |
| `web_security.py` | Explicit hosts, same-origin browser requests and HTTPS deployment policy |
| `input_limits.py`, `request_limits.py` | Shared HTTP/cron input contracts and byte-counted ASGI request admission |
| `user_assets.py` | Profile paths, root template fallback and effective scoring CV |
| `postings.py` | Posting schema, validation gate and rejection counts |
| `scrapers.py` | Apify mappings, collection orchestration and model analysis |
| `company_feeds.py` | Greenhouse, Personio, SmartRecruiters and SuccessFactors readers |
| `safe_fetch.py`, `job_jsonld.py` | Public URL checks and schema.org JobPosting extraction |
| `job_policy.py`, `analysis_validation.py` | Requirement checks, grounded evidence, ratings, eligibility and fingerprints |
| `generators.py` | Model transport, PDF builds and preview conversion |
| `career_record.py`, `career_cv.py` | Career-record validation, scoring text and deterministic CV rendering |
| `reviewed_documents.py` | Claim selection, letter planning/writing and evidence checks |
| `document_artifacts.py` | Source/PDF hashes, build records and atomic publication |
| `compiler_sandbox.py` | Isolated native document tools with explicit inputs, process limits and supervision |
| `capacity.py` | Fixed cross-process slots for model POSTs and native tools |
| `model_usage.py` | Durable model usage ledger and per-User daily request quotas |
| `jobweaver_mcp.py` | Four read-only tools over authenticated HTTP, exposed through stdio |
| `daily_scraper.py` | Optional scheduled collection and scoring, with no notifications |
| `demo_mode.py`, `demo_data.py` | Demo restrictions, read-only document responses and fictional seed data |

The frontend groups screens in `webapp/src/components/tabs/`, shared controls in `components/`, stateful API
workflows in `hooks/`, and document parsing/compilation support in `services/` and `workers/`.

Appearance uses Loden Light by default, a direct Loden Dark control and seven community
palettes. `ui_preferences.py` normalizes saved theme/font IDs on read without rewriting
profile files; `webapp/src/preferences.js` provides the matching browser contract.
Legacy `default` and unknown themes become Loden Light; retired decorative palettes become
Loden Dark. Explicit supported fonts are retained, while new accounts use Fira Sans and
numeric UI values use Fira Mono. The page bootstrap applies cached appearance before React
starts. Preference updates preserve omitted fields, and a delayed initial response cannot
replace a newer choice or prevent the untouched preference from loading. The demo keeps
appearance in browser storage without reading or writing shared account preferences.

## Storage and authentication

`JOBWEAVER_DATA_DIR` selects the database and `profiles/` directory.
The default is the checkout. Export this variable before starting Python. Create the directory first.
Templates and examples always come from the checkout.

SQLite stores users, jobs, scraping logs and persistent background tasks. Jobs use `(user_id, id)` as their
primary key. Indexed columns support filtering. The JSON `data` column retains the complete job record.
All application queries scope jobs, tasks and logs to the authenticated user.
Legacy Telegram identity columns remain for database compatibility. No notification integration ships.

Passwords use PBKDF2-HMAC-SHA256 with random salts and 600,000 iterations. Older hashes upgrade at login.
An HttpOnly, SameSite=Lax cookie holds a random 256-bit token; only its SHA-256 hash and expiry are stored
in SQLite. Sessions last at most 30 days. Logout revokes that session; password changes revoke all sessions.
Session creation checks that credentials did not change during login. Old signed cookies are rejected;
the former `.session_secret` is unused and is not automatically deleted. Sign-in work is limited to five
attempts per username/address pair and 30 per address per minute, returning 429 and Retry-After.

Default hosts are localhost and loopback IPs. Additional exact hosts require `JOBWEAVER_ALLOWED_HOSTS`.
`JOBWEAVER_HTTPS_ONLY=1` requires HTTPS and sets Secure cookies. A remote deployment needs a trusted TLS
proxy and explicit host configuration; proxy trust must match that deployment. Browser API requests must
use the same origin. CLI/MCP clients authenticate without browser Origin/Fetch Metadata headers.

Personal data lives under `profiles/<username>/`: career records, CV text, templates, configuration,
standing notes, preferences, drafts, outputs and the document library. Missing templates fall back to root samples.
The root `CV-plaintext.txt` is a fictional example, never a user's CV. A user without a career record or own
CV text gets no ratings or documents: scrape, reprocess and generation return "Add your CV in Personalize first.",
and a manual posting is saved with its analysis marked failed. Personalize offers the example as a starting text.
Profile writes target the user's directory. They do not replace root templates.
Template selection accepts only advertised IDs. Owned paths reject traversal and symlink escapes.
Usernames are validated. Removing a User deletes database records and sessions, retains files and reserves
the old username. New Users cannot adopt orphaned profile directories. This preserves the existing directory
layout without silently moving or deleting personal files; immutable storage IDs remain a future migration.

## Collection and analysis

Connectors fetch source records. Mappings convert them to the Posting schema.
The gate requires the source's own ID, source, URL, title, company and description.
It removes unknown fields and reports rejected records. Optional malformed dates or salaries become empty.
Existing stored jobs are not revalidated. See ADR-0006 for the contract.

URL import checks every DNS answer and connects directly to a validated public numeric address. Each
redirect repeats the checks. HTTP Host, TLS SNI and certificate verification keep the original hostname.
No proxy environment, netrc credentials, cookies or authorization state enters these requests. URL import
accepts HTML/XHTML; employer readers accept their JSON or XML feed types. Missing or other content types
fail closed. Only identity and gzip encoding are accepted; malformed/concatenated gzip is refused.
It reads JSON-LD first, then page heuristics. Requests identify themselves as Jobweaver.

Public fetches use an exec helper with a total deadline, including startup, DNS, headers, redirects and body:
15 seconds for URL import, 40 seconds for feeds. Timeout kills and reaps the helper. Four helpers may run
per backend process; additional requests fail without queueing. Helpers receive no credential environment
and import no server/database modules. Encoded bodies are limited to 4 MiB and decoded bodies to 8 MiB.
An additional 4 MiB + 256 KiB budget counts HTTP headers and chunk framing across all redirect hops,
before parsing. Responses and connections close on success, failure and redirects. The helper output is
bounded; POSIX also enforces its output file limit. This transport is verified on Linux.

Feed identifiers are validated before URL construction. Greenhouse and SmartRecruiters use their exact
API host, Personio the exact configured tenant at `*.jobs.personio.de`, and SuccessFactors the explicitly
configured careers hostname. Every feed redirect must retain HTTPS, port 443 and that exact host.
These policies do not constrain deliberately configured local model endpoints.

Shared validation applies before HTTP task creation, direct scraping and scheduled collection. LinkedIn
accepts 1–500 results per phrase; Karriere accepts 1–200. Both accept 1–720 hours and 1–200 km. Keywords
accept at most 20 phrases, 500 characters per phrase and 4,000 characters combined; scheduled collection
accepts at most 20 extra lanes, with each lane's total validated before it is divided across keywords.
Recognized saved and scheduled fields share these contracts. Config extensions remain preserved.
Apify dataset reads stop at the requested result count per phrase even if a provider returns more.

Employer collection accepts at most 50 companies and 2,000 retained rows. Each feed inventory is capped
at 1,000 postings. SmartRecruiters allows at most 10 list pages and 200 detail requests per company;
all companies share a 250-fetch limit per collection. A company that reaches its inventory/page/detail
cap reports a visible error and contributes no partial rows. Earlier successful companies are retained.
The aggregate row cap skips a company that would exceed it and the remaining companies.

New jobs are saved before analysis. Failed analysis remains retryable.
Analysis includes language requirements, salary, skills, summary and per-requirement checks.
The model classifies requirements as firm/optional and CV coverage as shown/related/missing.
Posting quotes must be grounded; an unsupported requirement quote fails validation instead of
silently reducing the requirements. Unsupported CV evidence counts as missing. Preference
conflicts require quotes from both the posting and the User's Standing Notes. A hard conflict
requires explicit firm language. Duplicate requirements cannot inflate the tally.
Extraction accepts at most 128 checks and 32 conflicts, with at most 4,000 characters per
quote. These bounds limit validation/deduplication work without reducing CV/posting limits.
Deduplication uses normalized names, preserving technical distinctions such as C/C++/C#;
semantic paraphrases can still repeat the same condition.

Fixed rules turn these checks into Great, Good, Decent, Stretch or Poor. Soft conflicts lower
the label; hard conflicts or eligibility blockers give Blocked. Empty checklists without blockers stay Unrated.
Judgement calls identify related firm requirements whose downgrade would change the label.
These labels depend on model judgements and are not probabilities. The Jobs view groups
them, folds Poor/Blocked by default and exposes the evidence on the existing job page.

The fingerprint includes the CV, model and analysis-schema version. Old numeric analyses
remain historical and are never converted into ratings or automatically regenerated merely
because a rating is absent. Explicit per-job Re-rate uses the existing bounded queue and
checks ownership before admission. Only the requested job resets after dispatch; stage,
application history and documents remain. Omitted targeting retains the pending/failed retry flow.

Persistent scrape, reprocess and batch-generation starts share one backend queue. It admits at most
two running operations plus eight waiting, with at most one running and two admitted per User.
Dispatch chooses the oldest eligible waiter, skipping Users already running so they cannot block
another User's idle slot. One scheduler critical section and a SQLite immediate transaction cover
active duplicate lookup, capacity checks and queued record creation. Keys scope canonical effective
inputs to User and kind. Batch keys include resolved model, tone, engine, profile, force and unique
job IDs; changing captured defaults changes the key. Equivalent active starts return the same task,
even during cancellation; they never cancel previous work. Rejected starts return 429/Retry-After.
Reprocess resets for `all_scored` happen only when admitted work is dispatched.

Task status/stage and results persist in SQLite: queued, running (collecting/resetting analysis/
analysing/generating/cancelling), then completed, failed, cancelled or interrupted. Status/active and
cancellation routes scope records to their User, including queued work after page reload. Cancelling
queued work never calls its worker. Running cancellation stops new child submission and waits for
running calls to exit; model HTTP helpers are killed and reaped, while saved results may already exist. The scheduler retains its reservation
until the callback and child pools have exited, regardless of early terminal result writes. Each
operation submits at most two child jobs at once; context-managed pools drain on cancellation,
exceptions and early consumer exit. Reprocessing retains its existing two-way execution.

The supported deployment is one backend worker per data directory on Linux. FastAPI lifespan acquires
a nonblocking POSIX owner lock in the resolved database directory before recovery; import alone cannot
recover another process's tasks. A second worker fails startup. The lock remains held through graceful
shutdown until running callbacks exit. Owned startup marks any previous queued/running rows interrupted
with explicit retry guidance; it never silently reruns them. The lock file must remain in place.
This is backend ownership. Cross-process model/native slots are described under operation budgets.

Model calls use OpenRouter or an OpenAI-compatible endpoint. `custom/` selects the custom route.
Custom endpoints use standard request parameters with fallbacks for structured-output support.
Scoring and documents resolve separate model settings. Automatic letter verification follows a `custom/`
writer through the same endpoint; hosted writers retain the hosted default. Settings exposes an explicit
verifier override (including a visible opt-out). The public copy contains no `agy/` model route.

## Operation budgets

`operation_budget.py` owns one thread-safe Budget per operation, with a monotonic absolute deadline,
terminal cancellation/exhaustion and atomic reservations for each actual POST. Nested scopes reuse it;
`bounded_results` submits each child with a fresh copied Context pointing to the same Budget. Scopes
wrap the function that actually executes, including queue callbacks, synchronous routes, daily per-user
runs and `generate_for_job.run` (cache checks, generation and final PDF checks). A FastAPI dependency
cannot establish a scope in a different worker context. The first terminal failure is latched so siblings
stop; broad job/stage handlers preserve terminal exceptions rather than trying another job or document.

| Allowance | Interactive / CLI documents | Collection / reprocess / batch / daily per User |
|---|---:|---:|
| Absolute elapsed time | 600 seconds | 1,800 seconds |
| Actual HTTP POST reservations | 16 | 120 |
| Aggregate UTF-8 prompt bytes | 64 MiB | 512 MiB |
| Aggregate serialized JSON payload bytes | 80 MiB | 640 MiB |
| Aggregate requested output tokens | 128,000 | 960,000 |
| Aggregate accepted response bytes | 16 MiB | 64 MiB |

Every call also caps prompt bytes at 8 MiB, payload at 10 MiB, requested output at 8,000 tokens and
response at 2 MiB. Schema insertion and endpoint parameter fallbacks are checked after serialization;
refusals/retries reserve again without refunds. Byte limits are not token estimates. Output-token limits
depend on endpoint compliance. Test code can inject tiny Limits; production has no unlimited setting.
These per-operation limits reset for a new operation and do not enforce daily quotas or monetary spending.

`model_transport.py` dispatches one short-lived exec helper per POST. The parent supervises startup,
stdin transfer, DNS, headers and streaming body against the same deadline and cancellation state. It
bounds both IPC pipes, kills/reaps before returning and never automatically retries ambiguous transport
errors. Retry waits poll cancellation and the remaining deadline. Credentials travel in a bounded stdin
envelope; argv, environment, persistent files and helper errors contain no request credentials. Sessions
ignore ambient proxy/netrc configuration, retain HTTPS certificate verification, request identity encoding
and refuse encoded responses and redirects. Configured local HTTP model endpoints are intentionally
supported; public fetch SSRF rules belong to a separate transport. Legacy provider unit tests explicitly
inject a private inline I/O fixture; production transport always uses the helper.

`capacity.py` provides fixed slots shared by every process using one data directory: 4 model POSTs and
2 native tools. Lock files live in `.jobweaver-capacity/` beside the resolved database path, so
`db.set_db_path`, `JOBWEAVER_DATA_DIR` and symlink aliases select the same slots. The leaf calls
`post_json` and `run_tool` acquire them, which covers the backend, synchronous routes, standalone CLI and
scheduled runs. Each acquisition opens every candidate file separately and takes a nonblocking `flock`.
Release is close-only; files are never unlinked or truncated. A full pool waits at most 20 seconds, never
past the operation deadline, while polling cancellation. Then it raises `OperationBusy` (HTTP 503 with
`Retry-After`); a wait cut short by cancellation or the deadline reports that instead. Busy is terminal
for the operation: that step's POST or tool never starts, nothing is reserved and nothing is retried. The one
exception is an optional preview after a written PDF, which is skipped. A slot file of ours with the wrong
mode is reset to 0600; other unusable lock paths fail closed. The model helper inherits its slot descriptor and arms its own `SIGALRM`
wall deadline (remaining operation time plus 5 seconds) before importing `requests`. A helper that
outlives a crashed parent keeps its slot until that deadline ends it.

Operation checks precede later compilation/publication; native tool timeouts clamp to remaining time.
Atomic CLI generation removes its new revision bundles on terminal failure. Manual postings save before
optional analysis and retain failed analysis for retry. Model cancellation stops local work but cannot
prove the provider stopped generation or billing; unknown usage stays unknown. USD enforcement is not
implemented (see the usage ledger below). The backend remains a single worker per data directory.

### Usage ledger and daily quotas

Every Budget carries an owner (User id), origin (`web`, `background`, `scheduled`, `cli`), an optional
task id and a random operation id. `attribute()` sets the owner once; a different User later is a terminal
error. `@operation` attributes a new operation from the function's `user` dict (origin `web`; the daily
per-User run passes `scheduled`), the queue worker attributes `background` with its task id, and
`generate_for_job.run` attributes `cli` after its user lookup. Nested operations never attribute.
`post_json` refuses an unattributed operation before any slot, reservation or dispatch.

`post_json` then takes, in order: the capacity slot, the operation Budget reservation, the durable quota
reservation, and dispatch. Busy before any reservation keeps the batch-4 rule that a busy step consumes
nothing; the in-memory Budget check runs before the database so the durable row is written only when
dispatch follows. The quota reservation is one `BEGIN IMMEDIATE` transaction (lock wait at most
min(5 s, remaining time)) that counts the User's `model_calls` rows for the quota day, compares requests
and requested output tokens with the limits, and inserts the `reserved` row or refuses. No database
connection is open during the provider call. A second short transaction stores the response fields
(`responded`) or marks `unknown` after transport errors, cancellation or deadlines. If that update fails,
the row stays `reserved` and the caller still receives the response.

Limits default to 300 requests and 2,400,000 requested output tokens per User per calendar day in
`JOBWEAVER_QUOTA_TZ` (server local zone by default); `JOBWEAVER_QUOTA_REQUESTS` and
`JOBWEAVER_QUOTA_OUTPUT_TOKENS` must be positive integers and are validated at backend and daily-run
startup. Per-User overrides live in `user_model_quotas` (NULL means the default) and are changed only with
`manage_users.py quota`; `PUT /api/config` writes profile JSON that the quota never reads. Attempts are
never refunded and custom endpoints count. Refusal raises `QuotaExceeded` (an `OperationExhausted`): HTTP
429 with `Retry-After` until the reset, terminal for sibling stages; the daily run logs it and continues
with the next User; the CLI prints it and exits 1. A busy or unusable ledger raises
`UsageLedgerUnavailable` (HTTP 503); nothing is sent. A missing owner (User deleted during the operation)
is an `AttributionError` (HTTP 502); nothing is sent. The backend, cron runs, `generate_for_job.py` and
`manage_users.py` each load `.env`; all of them must see the same `JOBWEAVER_QUOTA_*` values, or their
day boundaries and defaults differ.

`model_calls` rows hold user, origin, operation/task ids, purpose, label (one of a fixed set of code
labels such as `Letter plan` or `Company research`; anything else is stored as `model`), route
(`openrouter`/`custom`), endpoint host name, requested model, day, timestamps, prompt/payload bytes and
requested output tokens. Parsed from each response, else NULL: HTTP status, response bytes, provider
request id, served model, finish reason, prompt/completion/total/cached/reasoning tokens, `reported_cost`
as exact decimal text (`'0'` only when stated), `cost_unit` (`openrouter_credits`, or `endpoint_reported`
for a custom endpoint that states a cost) and `is_byok`. Responses are parsed inside `post_json`, so
schema fallbacks, 4xx and truncated replies are recorded. Prompts, responses, error bodies, headers, full
URLs, query strings and keys are never stored. The tables are created by `init_db` and, because cron and
CLI runs may skip it, inside the reservation transaction. `delete_user` removes the User's rows. Backend
startup deletes rows reserved more than 400 days ago, next to the queue pruning. Unexpected response-parse
failures leave the response fields NULL; the caller still receives the response. The model
helper loads `model_transport.py` as a script and never imports `db`, `model_usage` or dotenv.

This is a request-volume quota, not a monetary ceiling: price depends on model, provider and prompt size;
cost appears only after a response and only when reported; and cancelled or failed calls may still be
billed. `manage_users.py usage` therefore reports coverage (rows, rows with cost, rows without response)
and sums cost only over rows that reported one, per unit.

## Documents

A career record stores approved facts, claim ownership, role families, constraints and optional German wording.
The record format and validation rules are in `docs/career-record/FORMAT.md`.
CV rendering preserves approved claims. Letter generation plans evidence, writes cited paragraphs and asks
an independently selected model to check statements against those claims. Deterministic checks also examine
unsupported terms, numbers and length. A failed verifier does not silently publish a letter.

Typst is the default workflow; LaTeX remains optional and supported. Native builds, PDF validation and
previews run through Bubblewrap/prlimit on Linux. The sandbox mounts explicit scratch inputs and public
system/TeX/font resources, clears the compiler environment, separates network/PID namespaces and drops
capabilities. The checkout/data must stay outside mounted system/compiler resource trees. Typst receives
only its bundled public fonts/packages. Missing isolation fails closed. Limits include 1 GiB address space,
30 CPU seconds, 32 MiB per file, 256 file descriptors and an operation deadline. These are per-process
limits; the native slots above bound concurrency. Poppler validates PDFs and creates previews inside the sandbox.

The process chain is slot holder -> `prlimit` -> Bubblewrap monitor -> namespace init -> tool. Bubblewrap
passes inherited descriptors to the tool, so only the parent and the small holder (`python -I`) keep the
slot descriptor; the holder marks it close-on-exec before starting the monitor. Inside the sandbox no
`/proc/*/fd` entry resolves to a slot file or to the `--info-fd` pipe. `/tmp` is a 256 MiB tmpfs. The parent drains stdout and stderr concurrently and checks
cancellation and the deadline every 50 ms. The deadline is the smaller of the tool timeout and the
operation deadline. More than 4 MiB stdout or 256 KiB stderr stops the tool with `ToolOutputLimit`, never a
truncated success; realistic fictional CVs produce about 10 KiB of `latexdiff` output. On cancellation,
timeout or overflow the parent kills the namespace init through a pidfd from `--info-fd`, waiting up to
1 second for that report after an early cancel. Without a report it stops the monitor (`SIGSTOP`), kills the
monitor's child and then the monitor. The kernel kills every sandbox process, including detached sessions;
the monitor exits only after the namespace is empty, and the holder only after the monitor. The parent
reaps the holder and drains the pipes before releasing its slot. Killing the holder's process group is a
last, bounded escalation. If the parent dies, the holder kills the namespace init at its own wall deadline
(tool deadline plus 2 seconds) and holds the slot until the monitor exits.
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

Requirement checks and documents are hand-prepared examples. The interface states that no live model or verifier ran.
Regenerate document fixtures with `scripts/build_demo_documents.py` using installed LaTeX and Poppler.
Normal demo use requires neither tool.

## Runtime and verification

A pure ASGI middleware buffers incoming bodies under a byte cap before JSON parsing, authentication
dependencies or handlers execute. It rejects declared excess early and also counts actual bytes when
Content-Length is absent, incorrect or replaced by chunked transport. The limit is 16 MiB generally,
40 MiB for job document compile/finalize and Library update/compile routes, preserving two 12 MiB
decoded PDFs plus source fields. A single 30-second receive deadline covers the entire body. Responses
are 413 for excess bytes, 408 for the receive deadline, 415 for any non-identity Content-Encoding, and
400 for malformed/duplicate Content-Length. Rejections close the connection. Bodies are buffered in a
bounded bytearray so empty/tiny chunks cannot amplify a list of chunk references.

Text limits count Unicode characters, while body limits count encoded bytes. CV text, notes and sources
allow one million characters; instructions/tone 20,000; model IDs 200; job/document IDs 512; and batch
generation 300 individually bounded job IDs. Each PDF base64 field is bounded before decoding and
the decoded PDF validation still enforces 12 MiB. Persistent backend operation admission, per-user
concurrency, equivalent active reuse and owned restart recovery use the queue described above.
Operation scopes below cover synchronous model routes, background callbacks, daily per-user work and
standalone document generation. Per-User daily model quotas are described under operation budgets.

`make dev` runs FastAPI on localhost:8000 and Vite on localhost:5173.
Vite proxies `/api` to the backend. A built `webapp/dist/` is also served directly by FastAPI.
The default host binds only to loopback. Public hosting requires a separate deployment review.

Run Python tests through `scripts/test_isolated.py`. It copies source and fictional fixtures into a temporary
directory, disables dotenv and blocks external Python network connections before importing the server.
Never run direct discovery in a checkout containing real data. The demo integration test checks authentication,
all 15 postings, prepared downloads, refusal of writes, no compiler/network calls during reads, and unchanged files.
Frontend regressions run through `scripts/test_document_frontend.mjs`. The authenticated workspace is
remounted per User so drafts and cached data do not survive logout/account changes. Pending Library loads
and autosave timers are invalidated on unmount. Authenticated HTTP clients are bound to that workspace;
logout aborts pending requests and prevents later callbacks from sending requests in a different session.
Late unauthorized responses from an old session cannot log out a new one.
`scripts/test_security_browser.mjs` starts and cleans up its
own fictional instance; it checks account switching, verifier choice, both native engines and browser origins.

## Known limitations

- Letter verification has no measured catch rate on labelled examples. Read letters before sending.
- Native isolation currently requires Linux, Bubblewrap, prlimit and working user namespaces; other server
  platforms need a separately tested isolated worker. Browser-only Typst download and prepared demo reads
  do not require native compilation.
- Document locks coordinate one Python process. Backend ownership enforces one worker per data
  directory; model/native slots and per-User daily model quotas are shared across processes.
- Daily model quotas count requests and requested output tokens, not money. Reported cost is stored when
  the provider states it; rows whose update failed stay `reserved`. Rows older than 400 days are pruned only
  when the backend starts.
- A quota refusal during posting analysis marks that analysis failed like other terminal errors and uses one
  of its retry chances; retry after the quota resets.
- If the holder itself is killed (final escalation, or a crash of both processes), Bubblewrap's
  parent-death chain removes the sandbox but the slot is released without waiting for it. A slot
  waiter is polled, not queued in arrival order.
- MCP still uses an existing account password file; scoped per-client read tokens and a session-management UI remain future work.
- Google Fonts can load from external servers. The UI remains usable with system font fallbacks when offline.
