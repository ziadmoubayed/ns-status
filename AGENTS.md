# AGENTS.md

## Purpose

This repository tracks NS route health by collecting trip data from the same backend API used by the public NS journey planner, storing normalized snapshots in SQLite, and exposing a FastAPI dashboard with daily route status for the past 30 days.

## Working Rules

- Do not build new features around scraping rendered `ns.nl` HTML. The intended integration point is the trips API used in [`ns_status/client.py`](./ns_status/client.py).
- Preserve idempotency for collection writes. The storage contract is keyed by `route_id + requested_datetime`, and reruns must update existing data instead of creating duplicates.
- Keep the collector lightweight. Prefer the standard library unless there is a clear need for another dependency.
- Treat the web app as a read-only layer over SQLite. Route health and availability scores should be derived from stored samples, not recomputed from live external calls in request handlers.

## Project Layout

- `ns_status/client.py`: NS API client and SSL/curl fallback.
- `ns_status/collector.py`: snapshot collection, delay grading, and sampling window logic.
- `ns_status/storage.py`: SQLite schema and upsert behavior.
- `ns_status/reporting.py`: daily aggregation and availability score calculation for the dashboard.
- `ns_status/web.py`: FastAPI app.
- `templates/` and `static/`: server-rendered HTML and CSS.
- `routes.json`: route definitions and rush-hour windows.
- `data/ns_status.db`: local SQLite database created at runtime.

## Commands

Use the local virtualenv for all repo commands:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Useful commands:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ns_status list-routes
.venv/bin/python -m ns_status collect-once --route-id utrecht-amsterdam-centraal --at 2026-03-10T21:22
.venv/bin/python -m ns_status collect-window --window morning_rush --date 2026-03-11
.venv/bin/python -m ns_status serve --host 127.0.0.1 --port 8000
```

## Data Semantics

- `delay_grade` is a 1-5 scale derived from the worst delay in a trip, with cancellations and partial cancellations forced to grade `5`.
- The dashboard availability score is daily and route-based. It is derived from stored `trip_samples`, not from `scrape_runs`.
- Missing days in the dashboard are valid and should render as `No Data`, not as zero availability.

## When Changing Code

- If you touch storage logic, verify both schema compatibility and deduplication behavior against an existing database.
- If you change dashboard aggregation, keep the 30-day daily view intact unless the product requirement changes.
- If you add tests, prefer focused `unittest` coverage that can run without network access.
- If you add dependencies, update `pyproject.toml` and keep package discovery restricted to `ns_status`.
