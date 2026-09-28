# Uptime Viewer

Service availability dashboard with Python/Sanic, aiohttp, MySQL and Chart.js.
Tracks status transitions, sampled response times, outage counts and durations,
with optional Telegram alerts for failures and recovery.

## Setup

1. Copy `.env.example` to `.env` and set `URLS` to comma-separated HTTP(S) URLs.
2. Set `MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD` explicitly, plus
   `MYSQL_DATA_DIR` for persistent MySQL storage. Neither password has a default.
   For an existing volume, supply its current credentials: changing `.env` does
   not change MySQL accounts inside an initialized volume. Rotate them separately
   using MySQL administration if necessary; do not delete the volume to reset them.
3. Optionally set both `TG_BOT_TOKEN` and `TG_CHAT_ID`. Empty values disable
   Telegram without disabling monitoring. Set `DASHBOARD_URL` to your public
   dashboard URL to add a `#service-{id}` link to alerts. It defaults to empty;
   when unset, empty or whitespace-only, both down and recovery alerts omit the
   dashboard link.
4. Run `docker compose up -d --build`. Compose exposes container port 8000 on an
   automatically allocated host port; `docker compose port backend 8000` shows it.
   A reverse proxy such as Coolify can route to backend port 8000 directly.

MySQL has no published host port; the backend reaches it through the Compose
network using `db:3306`. The backend runs as UID/GID 10001, without root privileges.

Known fresh-install issue: the current unique URL index can exceed MySQL's key
length limit with `utf8mb4`. The audit did not migrate existing schema or data;
see [the repository audit](docs/repository-audit.md#open-schema-issue) before
provisioning a new database.

Run only one backend replica. Its single Sanic process owns the monitor and
cleanup jobs; multiple replicas would duplicate checks, transitions and alerts.
Services are inserted from `URLS` at startup. Removing a URL from this variable
does not remove an existing service or its monitoring history.

## Configuration

All options below are forwarded by `docker-compose.yml`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `URLS` | empty | URLs registered at startup |
| `TG_BOT_TOKEN`, `TG_CHAT_ID` | empty | Both required for Telegram delivery |
| `DASHBOARD_URL` | empty | Optional public HTTP(S) dashboard URL; blank omits the link |
| `CHECK_INTERVAL_SECONDS` | `10` | Target start-to-start interval; allowed 5-300 seconds |
| `PING_SAMPLE_SECONDS` | `60` | Minimum spacing of stored response samples per process; allowed 60-3600 seconds |
| `HISTORY_RETENTION_DAYS` | `90` | History horizon; allowed 30-365 days |
| `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` | required | Existing or newly provisioned MySQL account passwords |

Blank numeric values use their defaults. Invalid settings fail startup.
Database connection settings are `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`,
and `DB_NAME`; Compose maps the credentials from the `MYSQL_*` variables.
Direct backend startup also requires `DB_PASSWORD`. Credentials are passed through
SQLAlchemy's structured URL API, so passwords containing `@`, `#`, `/` or `%`
work without manual URL encoding. Stale pooled connections are checked on checkout.
Outbound site checks release their read connection before waiting for HTTP, then
open a separate transaction to save the observation. A removed service or changed
URL causes that in-flight observation to be discarded.

`URLS` defaults to empty and never starts polling example third-party sites.
URLs must use HTTP(S), have a valid host/port, and contain no embedded credentials,
fragments, whitespace or control characters. Private/LAN targets are allowed.
Startup also validates previously stored service URLs and reports only the service
ID for invalid entries. Correct legacy entries before starting; validation never
silently rewrites or deletes stored URLs.

The dashboard/API intentionally publish service names and target URLs, and alerts
include them too. Do not put API keys, tokens or other secrets in URL paths/query
strings. Put private deployments behind an authenticated reverse proxy; the app
does not implement user authentication.

## Measurements And Dashboard

Checks run concurrently with an isolated database session per service. Requests
time out after 10 seconds. Statuses below 400, plus 401, 403 and 405, count as up,
preserving the existing behavior. The target cadence includes check time; slow
requests or database contention may extend it. State changes are saved on every
check, independently of the less frequent response-time samples.

Durations represent time between observations, not exact real-world outage
boundaries. A two-second failure between checks can be missed. A detected failure
is timed until the next successful observation; faster checks reduce this error.
The UI displays seconds instead of rounding short outages to whole minutes.
Old minute-spaced history cannot be made more precise retrospectively.

Services appear in separate rounded dark cards with inset content, pill-shaped
status labels and a rounded period selector; the layout adapts to narrow screens.
The original near-black palette uses a black background (`#000000`) and slightly
lighter cards (`#0a0a0a`) with subtle borders.
The refresh timestamp is centered below the period selector.
The header leads directly into the service cards, with no aggregate status strip,
color legend or footer. Status and downtime details live inside each service card.

The 24H / 7D / 30D views refresh every 20 seconds while visible. Each service shows:

- Uptime over recorded state intervals; time before its first observation is
  excluded and drawn gray, rather than assumed healthy.
- Number of outages overlapping the selected period, total downtime and longest
  outage, all clipped to that period. An already-running outage counts once.
- Average sampled response time, weighted by sample counts across hourly buckets.
- The latest ten overlapping outages, with their original start times and
  durations inside the selected period. Ongoing outages expand automatically.
- Sixty timeline intervals. Color uses downtime divided by recorded time inside
  each interval: RGB interpolation from the original green (`#18d43b`) at 0%, to amber at 5%, to red at
  25% or more. Partial-history intervals are faded; unknown intervals are gray.
  Hover, focus or tap shows the precise fraction and duration.

The last recorded state is assumed to continue until the next observation.
There is no monitor heartbeat, so downtime of the monitor itself is not separately
identified; gaps caused by stopping it can bridge a state interval. Current status
means the last recorded status, not a fresh check performed by the browser.

Response-time charts use pinned Chart.js from jsDelivr. If the CDN cannot load,
the remaining dashboard still works and the chart shows an unavailable state.

## Storage And Cleanup

Previously, every poll inserted a ping indefinitely. New checks default to every
10 seconds but persist at most one ping per 60 seconds per service per process,
approximately 129,600 samples over 90 days. A restart can add one extra sample.
These are samples, not an average of every intervening check; failed requests also
contribute their elapsed response time. State transitions are always persisted.

An independent task runs on startup and then hourly. It deletes pings older than
the retention horizon and closed state intervals ending before that horizon.
Open intervals and intervals crossing the boundary survive. Each transaction
deletes at most 1,000 rows; each pass processes at most 100 batches per table.
A large backlog is drained over subsequent hourly passes, without an unbounded
cleanup transaction inside the monitor loop. Retention is destructive for old
history: take a backup before deploying to an existing installation if needed.

Deleting rows allows InnoDB to reuse space; it does **not** promise that existing
database files shrink. No `OPTIMIZE TABLE`, database rebuild, or volume deletion
is performed. Already-exhausted storage may need operator attention before the
application can start. Monitor database capacity and cleanup logs.

Startup creates missing tables, adds `services.notified_down` if absent and adds
an index on `state_logs.end_time` if absent. Both the original master schema and
the earlier Telegram branch schema are supported. ALTER/CREATE INDEX privileges
are needed for existing installations; building an index on a large table may
take time. Genuine migration failures propagate, and startup stops after 15
failed initialization attempts instead of launching a broken monitor.

Telegram notifications are queued after a successful database commit. Delivery
is best effort: an in-memory FIFO holds up to 1,000 messages, retries transient
failures up to five times, respects Telegram retry delays and spaces messages by
three seconds. Full queues, permanent API errors, exhausted retries or a process
restart can lose notifications. There is no persistent delivery outbox, and
enabling Telegram does not replay old alerts. Names and URLs are HTML-escaped.

## Health Checks

`GET /health` returns HTTP 200 with `{"status":"ok"}` when the named monitor
task exists and is still running, and the application can execute `SELECT 1`
using its database credentials. A missing/completed/cancelled monitor task,
database error or timeout returns HTTP 503 with `{"status":"unavailable"}`.
The three-second database deadline includes acquiring a session/connection.
Responses are not cached and do not expose connection details or exceptions.
An external monitored site being down does not fail the application's healthcheck.

Docker Compose probes MySQL with `mysqladmin ping` over TCP every 10 seconds,
with a five-second timeout, ten retries and a 30-second startup grace period.
This checks server availability, not database credentials; the backend probe
checks authenticated database access. Backend startup waits for MySQL to become
healthy via `depends_on: condition: service_healthy`.

The backend image and Compose both use `backend/healthcheck.py` to request
`http://127.0.0.1:8000/health`. The probe bypasses environment HTTP proxies so it
always checks the local application. This needs no curl installation. It has a four-second
HTTP timeout; Docker runs it every 30 seconds with a five-second process timeout,
three retries and a 60-second startup grace period. No new environment variables
are required. `docker compose ps` shows health; a reverse proxy can use `/health`.

Health verifies database access and a live monitor task, not polling progress or
the health of every background worker. Docker marking a container `unhealthy`
does not by itself restart it: `restart: always` applies to exited containers.
The dependency condition gates initial startup, not later database recovery.

## Code Map

| Path | Responsibility |
| --- | --- |
| `backend/app.py` | Sanic entry point, static frontend, lifecycle, REST routes |
| `backend/settings.py` | Validated runtime configuration loaded at startup |
| `backend/healthcheck.py` | Standard-library HTTP probe used by Dockerfile and Compose |
| `backend/database.py` | SQLAlchemy models, async sessions, idempotent schema initialization |
| `backend/monitor.py` | Polling, transition recording, Telegram worker, retention worker |
| `frontend/index.html` | Dashboard structure and service template |
| `frontend/css/style.css` | Desktop/mobile layout and status styling |
| `frontend/js/main.js` | API loading, refresh, charts, outage history and interactions |
| `frontend/js/metrics.mjs` | Pure duration, overlap, uptime and timeline-color calculations |
| `tests/test_monitor.py` | SQLite-backed migration, cleanup, sampling and notification tests |
| `tests/metrics.test.mjs` | Deterministic duration, clipping, unknown-state and color tests |
| `tests/test_http.py`, `tests/http_smoke_app.py` | Real loopback Sanic startup/routes/health smoke test with SQLite and synthetic checks |
| `tests/test_repository.py` | Compose exposure, credential and example-config invariants |
| `tests/test_mysql_driver.py` | Installed MySQL dialect/async adapter pre-ping compatibility without a database server |
| `requirements-dev.txt` | Reproducible development/test/browser/audit dependencies |
| `tools/run_checks.py` | Time-bounded Python/Node verification runner |
| `tools/preview.py` | Temporary synthetic API and screenshot orchestration; never uses real DB |
| `tools/browser_check.py` | Playwright layout, interactions and chart pixel checks; 2x screenshots |
| `backend/Dockerfile`, `docker-compose.yml` | Python 3.11 backend and persistent MySQL 8 deployment |
| `.gitignore`, `.dockerignore` | Exclude local/private artifacts and allow only application source into Docker builds |
| `docs/repository-audit.md` | Public-repository audit, fixed findings and remaining schema issue |

Tables: `services` stores monitored URLs and last down-state flag; `state_logs`
stores UP/DOWN intervals; `ping_logs` stores sampled response times. Foreign keys
associate both history tables with services. Times are stored as naive UTC and
returned as ISO 8601 UTC strings.

API: `GET /api/services` returns service IDs/names/URLs.
`GET /health` is the container readiness endpoint described below.
`GET /api/status/{id}?hours=24` returns state `logs`, `period_hours`, authoritative
`now`/`cutoff`, and `check_interval_seconds`.
`GET /api/ping/{id}?hours=24` returns hourly `pings` with `time`, `ping_ms` and
`samples`. Hours are clamped to 1-720; invalid values fall back to 24.

## Verification And Preview

Use Python 3.11, matching the Docker image, and Node.js 18 or newer. Create a
virtual environment, activate it, and install `requirements-dev.txt`. Run:

```sh
python tools/run_checks.py
```

Each subprocess has a 90-second limit. Tests do not contact production databases,
live monitoring targets or Telegram. The HTTP test briefly starts Sanic on a
loopback port with synthetic checks and stops it afterwards. SQLite tests cover
migration and retention semantics, but cannot
establish MySQL locking or migration performance on a large existing volume.
Validate those separately before deployment.

For screenshots, have Chrome available. Playwright is included in the development
requirements; no personal Codex skill or machine-specific path is required:

```sh
python tools/preview.py
```

The preview serves real frontend files with synthetic API history on loopback,
checks 320/390/820/1440px layouts and interactions, and writes screenshots plus
browser results under `.artifacts/preview/`. Browser subprocesses are bounded and
the server stops afterwards. Preview URLs and outages are fictional fixtures.
`--renderer /path/to/render_site.py` optionally adds another renderer; normal
preview and browser checks work without it.

Run `python -m pip_audit -r backend/requirements.txt` to resolve and audit production
dependencies, or `python -m pip_audit` inside a clean environment to audit installed
packages including transitive dependencies. Audits need network access. Dependency
updates should be followed by `tools/run_checks.py` and a MySQL/Docker smoke test.

Local `.env` variants, IDE state, Telegram attachments, generated previews,
virtual environments and database files are ignored by Git. `.dockerignore`
allows only backend source/requirements and frontend HTML/CSS/JS into build
contexts; add explicit patterns when introducing a new application asset type.
