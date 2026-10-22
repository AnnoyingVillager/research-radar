# Research Radar Project Memory

This file is repository-level context for future Codex sessions. Read
`README.md` for user-facing deployment instructions and
`docs/AI_MODIFICATION_GUIDE.md` before changing collection, scoring, reporting,
authentication, encryption, database, or deployment behavior.

## Project Purpose

Research Radar (科研雷达) is a venue-first research monitoring system. Its
default domain is aeroacoustics, computational acoustics, and fluid mechanics.
It collects journal metadata from Crossref and publisher RSS feeds, enriches
papers through OpenAlex, monitors public conference pages, scores relevance,
generates Chinese AI summaries, and publishes Markdown/HTML daily and weekly
reports. It is not an arXiv-first paper downloader.

The project is intended for single-host, low-concurrency deployment on a
campus network, including an x86_64 iStoreOS Docker host. The public repository
is `https://github.com/AnnoyingVillager/research-radar`.

## Runtime And Architecture

- Python 3.12, FastAPI, APScheduler, SQLite, Jinja2, `httpx`, and `uv`.
- `web` runs FastAPI and serves setup, login, dashboard, paper details, reports,
  settings, feedback, and manual AI-summary actions.
- `worker` runs `python -m app.cli scheduler` for daily collection and weekly
  reports.
- Both containers use the same five named volumes: `data`, `logs`, `cache`,
  `papers`, and `secrets`.
- SQLite uses WAL mode. It is appropriate for one host, not multi-host writers.
- The public image is `ghcr.io/annoyingvillager/research-radar`; GitHub Actions
  tests the project and publishes `linux/amd64` images to GHCR.

## Main Code Map

- `app/pipeline.py`: daily collection, enrichment, scoring, summary, conference,
  and report orchestration.
- `app/sources/`: Crossref, RSS, OpenAlex, conference-page, and HTTP collectors.
- `app/domain.py`: normalized `RawPaper` model shared by collectors.
- `app/config.py`: environment settings plus validation and database overrides.
- `app/db.py` and `app/schema.sql`: persistence, deduplication, migrations,
  settings, reports, conference changes, and job status.
- `app/scoring.py`: venue, relevance, momentum, openness, novelty, and feedback
  scoring.
- `app/llm.py`: OpenAI-compatible Chat Completions client, prompt, JSON parsing,
  and error redaction.
- `app/reporting.py`: daily and weekly report generation.
- `app/main.py`, `app/auth.py`, `app/crypto.py`: admin web UI, signed sessions,
  CSRF, password hashing, encrypted settings, and TLS material.
- `config/interests.yaml`: research profile, topic groups, keyword weights, and
  negative keywords.
- `config/venues.yaml`: journal ISSNs, RSS feeds, tier, topics, and conference
  pages to monitor.
- `config/sources.yaml`: lookback windows, request limits, retry policy, and
  enrichment limits.
- `tests/`: unit and FastAPI interface tests.

## Data Flow And Behavioral Rules

1. Seed configured journals and conferences into `venues`.
2. Collect journals concurrently from Crossref and RSS.
3. Normalize to `RawPaper`; deduplicate by DOI, otherwise normalized title plus
   venue slug.
4. Enrich a bounded recent set through OpenAlex.
5. Score recent papers, then summarize a bounded top set through the configured
   OpenAI-compatible endpoint.
6. Re-score with AI novelty, monitor conference pages, and generate the report.
7. Record status and errors in `job_runs`.

Batch AI summarization must remain scoped to the configured top N papers. Papers
in that top N that already have complete summaries are skipped; the pipeline
must not move past the top N to find more unsummarized papers. Manual summary
refresh is an explicit admin action and may replace an existing summary.

Conference support currently monitors public page changes. It does not create
paper records from conference proceedings. Adding proceedings is a new
collector/data-flow feature, not only a YAML edit.

## Configuration And Secret Boundaries

Changing the research field should normally start with `config/interests.yaml`
and `config/venues.yaml`; collection scale belongs in `config/sources.yaml`.
New source protocols, conference-paper ingestion, new database fields, score
formula changes, and dynamic report grouping require code and tests.

Deployment should require only editing `docker-compose.yml` and running
`docker compose up -d`. Non-sensitive deployment parameters belong in Compose
environment variables. SMTP credentials and API keys must be entered after
login in the web UI.

`app_settings` stores sensitive values encrypted with the key in the
`radar-secrets` volume. Never put SMTP passwords, LLM API keys, OpenAlex keys, or
other credentials in `docker-compose.yml`, `.env`, source, logs, reports, or Git.
Never expose saved secrets back into HTML. Back up `radar-data` and
`radar-secrets` together; either volume alone is insufficient for recovery.

Preserve these security properties unless the user explicitly requests a
reviewed security change:

- HTTPS is enabled by default with an automatically generated self-signed
  certificate.
- Admin passwords use salted PBKDF2-SHA256 hashes.
- Login cookies are signed and marked `HttpOnly`, `Secure`, and `SameSite=Lax`.
- CSRF protection remains on state-changing web actions.
- Stored API keys and SMTP passwords remain Fernet-encrypted.
- LLM keys are sent only over HTTPS. SMTP requires SSL or STARTTLS with
  certificate verification.
- Do not bypass paywalls, CAPTCHAs, CARSI/Shibboleth, or publisher access
  controls.

Trusted-LAN HTTP is technically possible by setting `TLS_ENABLED=false` and
`SESSION_HTTPS_ONLY=false`, but it must not be used over an untrusted network
because login credentials and session traffic are not encrypted.

## Database And Migration Rules

`schema.sql` creates a new database but does not add columns to an existing
production table. Any schema change must include an idempotent migration in
`app/db.py`, with a test that starts from an older schema. Do not rewrite or
delete user data during migration. Keep the secret re-encryption and plaintext
cleanup behavior intact.

## Development Commands

Use PowerShell on this Windows workspace:

```powershell
uv sync --frozen
uv run python -m app.cli init-db
uv run python -m app.run
uv run pytest -q
uv run ruff check .
git diff --check
```

If the sandbox blocks the system temporary directory during tests, use a
workspace-local base directory:

```powershell
uv run pytest -q --basetemp=.pytest-tmp\check -p no:cacheprovider
```

Useful task commands:

```powershell
uv run python -m app.cli run-daily
uv run python -m app.cli run-daily --no-report
uv run python -m app.cli report-daily
uv run python -m app.cli report-weekly
uv run python -m app.cli scheduler
```

## Docker And Operations

The supported iStoreOS deployment is:

```sh
mkdir -p /root/research-radar
cd /root/research-radar
curl -fsSLO https://raw.githubusercontent.com/AnnoyingVillager/research-radar/main/docker-compose.yml
# Edit TLS_HOSTNAMES, contact email, schedule, proxy, or WEB_PORT as needed.
docker compose pull
docker compose up -d
docker compose ps
```

Initial setup reads the one-time token from
`docker compose exec web cat /app/secrets/setup-token`, then opens
`https://<LAN-IP>:8443/setup`.

Update an existing deployment with:

```sh
docker compose pull
docker compose up -d --remove-orphans
```

If port 8443 is occupied, change the host side of the Compose port mapping
through `WEB_PORT` or the direct mapping. Do not run `docker compose down -v`
unless the user explicitly intends to erase databases, reports, keys, and TLS
material.

## LLM Compatibility

The application calls OpenAI-compatible `/chat/completions`. For OpenCode Go,
the current base URL is `https://opencode.ai/inference/go/openai/v1`; the legacy
`https://opencode.ai/zen/go/v1` path is normalized at runtime. Use the exact model
ID returned by the compatible API. Models that require OpenAI Responses or
Anthropic Messages APIs are not supported by the current client.

When changing LLM behavior, preserve request compatibility normalization,
structured JSON validation, bounded retries/timeouts, and redacted error logs.
Tests must not make real external API calls.

## Change Checklist

- Read `docs/AI_MODIFICATION_GUIDE.md` before structural changes.
- Keep edits scoped and preserve unrelated user changes.
- Add or update tests for behavior changes.
- Run pytest, Ruff, and `git diff --check`.
- Update README or the AI modification guide when deployment, configuration, or
  extension behavior changes.
- Confirm no credentials, generated databases, logs, certificates, or private
  files are staged.
- Do not commit or push unless the user asks.
