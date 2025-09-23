# Notion Webhook – Agent Guide

This document captures the full context required to maintain, extend, or operate the service. It complements the concise overview in `README.md`.

---

## 1. Architecture Overview

- **FastAPI application (`app/main.py`)**
  - Uses a lifespan context to perform startup/shutdown tasks (logging, Notion key warnings, database schema preparation).
  - Registers the webhook router (`/webhook/notion`) and basic health endpoints.

- **Configuration (`app/config.py`)**
  - Backed by `pydantic-settings`; reads `.env` files and environment variables.
  - Provides `settings` singleton with flags for Notion API, webhook, and database connectivity.

- **Webhook router (`app/routers/webhooks.py`)**
  - `/webhook/notion` accepts both verification payloads (containing `verification_token`) and event batches.
  - Normalizes the incoming payload (supports Notion v2025-09-03 event format with nested `items`/`events`).
  - Validates request signatures via `services.notion.validate_webhook_signature` when a verification token is configured.
  - For each normalized event:
    - Parses into `NotionEventPayload` (Pydantic model).
    - Fetches the latest entity snapshot and Markdown representation from Notion APIs.
    - Persists the snapshot using `services.notion.save_entity`.
    - Responds with a status message indicating success and, when available, the entity URL.

- **Notion service module (`app/services/notion.py`)**
  - Provides core operations: signature validation, entity fetching, Markdown rendering, persistence, and schema initialization.
  - Fetches Notion entities using the configured API version (default `2022-06-28`, supports `2025-09-03`).
  - Enriches entity data with:
    - Markdown content derived from block structure (`blocks_to_markdown`).
    - Title extraction (`extract_title`) for pages and databases.
    - Page URL fallback generation when Notion response omits `url`.
  - Persists snapshots via the content adapter when database credentials are provided.
  - `ensure_content_storage()` prepares the database schema during startup.

- **Adapters (`app/adapters/`)**
  - `content.py` implements `ContentStoreAdapter` using `pg8000` for pure-Python PostgreSQL access.
    - Lazily ensures `notion_contents` table exists with columns: `id`, `entity_type`, `title`, `url`, `markdown`, `updated_at`.
    - Upserts snapshots with `INSERT ... ON CONFLICT`.
  - `__init__.py` exposes `get_content_adapter()` as a singleton factory.
  - `postgres.py` (legacy) remains for future use but is currently unused.

- **Models (`app/models/`)**
  - `webhook.py` defines Pydantic models for Notion verification payload, event payload, and response.
  - `entity.py` retains legacy models (not used by the new content storage flow but available for extension).

---

## 2. Database Schema

`notion_contents`

| Column       | Type      | Notes                                      |
|--------------|-----------|--------------------------------------------|
| `id`         | TEXT (PK) | Notion entity ID                           |
| `entity_type`| TEXT      | `page` or `database`                       |
| `title`      | TEXT      | Extracted title (best effort)              |
| `url`        | TEXT      | Notion URL (direct or synthesized)         |
| `markdown`   | TEXT      | Markdown representation of the entity      |
| `updated_at` | TIMESTAMP | Automatically refreshed on every upsert    |

> The adapter will create the table (and add the `title` column if missing) every time the app starts and detects configured DB credentials.

---

## 3. Markdown Rendering

- `services.notion.blocks_to_markdown` iterates over block arrays and translates each block type into Markdown.
- Supports headings, lists, to-dos, quotes, callouts, code blocks, images (as links), bookmarks, toggles, etc.
- Nested blocks are rendered recursively with indentation.
- Highlights:
  - Numbered list counters tracked per nesting level.
  - Code blocks respect language metadata when available.
  - Fallback ensures unsupported block types still emit readable text.

---

## 4. Type Extraction

- `extract_title` explores multiple paths to derive a title:
  - Page: `properties -> title` or top-level `title`/`name` fields.
  - Database: `title` array or string fields.
  - Fallback: join plain-text fragments if structured data exists.
- Used both during fetch (to store in the entity) and before persistence (in case the persisted snapshot lacks `title`).

---

## 5. Webhook Flow Details

1. **Verification**
   - Payload: `{ "verification_token": "..." }`
   - Router responds `Verification token received: ...` and logs the token for secure storage.

2. **Signature Validation**
   - Uses `HMAC-SHA256` with the stored verification token.
   - Skips validation if token absent to simplify local testing.

3. **Event Processing**
   - Normalizer flattens nested event batches and ensures a consistent shape for Pydantic validation.
   - Each event triggers fetching, logging, and optional persistence.
   - Returns aggregated message summarizing processed events.

4. **Error Handling**
   - Invalid JSON → `400` with detail message.
   - Invalid signature → `401`.
   - Pydantic validation errors → `400` with error summary.
   - Internal fetch/persist failures log errors but still return success (`success: true`) to avoid webhook retries, while the message indicates the failure.

---

## 6. Environment & Tooling

- **Dependency management**: [uv](https://github.com/astral-sh/uv) (see `run.sh` for automation).
- **Configuration**: `.env` + `.env.example` align with `pyproject.toml` extras (`dev`, `postgres`).
- **Testing**: `pytest` with auto-discovered test paths, asynchronous tests supported by `pytest-asyncio`.
- **Formatting/Linting**: not enforced here, but `pyproject.toml` sets `ruff` preferences.

---

## 7. Local Setup and Testing

1. Sync dependencies:

   ```bash
   uv sync --extra dev
   uv sync --extra postgres  # if using PostgreSQL persistence
   ```

2. Run Postgres (example via Docker):

   ```bash
   docker run --rm -d --name notion-postgres \
     -e POSTGRES_USER=notion \
     -e POSTGRES_PASSWORD=notion \
     -e POSTGRES_DB=notion_webhook \
     -p 5433:5432 \
     postgres:16-alpine
   ```

3. Copy config:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with Notion credentials, webhook URL, and database parameters.

5. Run tests:

   ```bash
   uv run pytest -q
   ```

6. Start app:

   ```bash
   ./run.sh serve
   ```

   If you want the helper script to synchronise the PostgreSQL extra before
   starting the server (useful on fresh environments), set `USE_POSTGRES=1`:

   ```bash
   USE_POSTGRES=1 ./run.sh serve
   ```

7. Run with Docker Compose:

   ```bash
   docker compose up --build
   ```

   The compose setup starts two services:
   - `app`: builds the FastAPI application image (installs dependencies via `uv`).
   - `db`: PostgreSQL 16 with credentials sourced from environment variables (defaults align with `.env.example`).

   The app container overrides `DB_HOST` to `db` and `DB_PORT` to `5432`; external clients can reach the API on `http://localhost:8000`, and the database is exposed at `localhost:5433` for debugging.

---

## 8. Deployment Notes

- Replace the dev webhook URL (`https://example.ngrok.app/...`) with your production endpoint.
- Set `DEBUG=False` and tighten CORS if exposing to the public internet.
- Use `uvicorn` with multiple workers or run behind Gunicorn for production load.
- Ensure environment variables (`NOTION_API_KEY`, `NOTION_VERIFICATION_TOKEN`, DB credentials) are injected in the target environment.

---

## 9. Troubleshooting

- **Verification token missing**: Check webhook payloads and ensure the endpoint logs the token. Store it in `.env` to enable signature validation.
- **Signature errors**: Confirm `NOTION_VERIFICATION_TOKEN` matches the token configured in Notion’s UI.
- **Database not persisting**: Verify `uv sync --extra postgres` was run and env vars are set. Startup logs should show the schema creation. Use `pg8000` or psql to inspect `notion_contents`.
- **Markdown missing content**: Some block types may not be fully represented; review `blocks_to_markdown` and extend handling for new block types.
- **Event payload changes**: Notion may introduce new schemas. Update `normalize_events` and Pydantic models to accommodate new fields.

---

## 10. Future Enhancements

- Add queued retry mechanism for persistence failures instead of logging only.
- Introduce structured logging and metrics (e.g., OpenTelemetry).
- Provide GraphQL/REST endpoints to query stored snapshots.
- Extend Markdown conversion to support toggle details, synced blocks, etc.

---

This guide should equip maintainers and automation agents with the details necessary to operate and extend the Notion Webhook service confidently.
