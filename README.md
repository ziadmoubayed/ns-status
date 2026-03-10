# NS Route Status Collector

This project collects route-level snapshots from the same trips API used by the public NS journey planner and stores normalized results in SQLite for later visualization.

## Why this approach

Scraping rendered HTML from `ns.nl` would be brittle. The journey planner frontend currently calls a public trips endpoint directly, so this collector uses that backend instead and stores:

- the raw API response for each route/time request
- one normalized row per returned trip option
- a simple delay grade from `1` to `5`
- cancellation and partial-cancellation flags
- idempotent writes keyed by `route_id + requested_datetime`

## Files

- `routes.json`: route definitions and rush-hour windows
- `data/ns_status.db`: SQLite database created on first run

## Commands

All commands are run via `.venv/bin/python -m ns_status <subcommand>`. Two global options apply to every subcommand:

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `routes.json` | Path to the routes JSON config file |
| `--db PATH` | `data/ns_status.db` | SQLite database path |

Install the project into the local virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

### `list-routes`

Prints all configured routes and sampling windows from the config file. No network calls.

```bash
.venv/bin/python -m ns_status list-routes
```

### `collect-now`

Collects all configured routes at the current time. Designed for cron — no window or time arguments needed.

```bash
.venv/bin/python -m ns_status collect-now
```

Example crontab entry to collect every 5 minutes:

```
*/5 * * * * cd /path/to/ns-status && .venv/bin/python -m ns_status collect-now
```

### `collect-once`

Fetches trip data for one route at one departure time from the NS trips API and upserts it into SQLite. Prints a per-trip summary with times, delay grade, and train info.

| Option | Required | Description |
|--------|----------|-------------|
| `--route-id` | yes | Route identifier from `routes.json` |
| `--at` | yes | Requested departure datetime in ISO-8601 (e.g. `2026-03-10T21:22`). Uses the config timezone when no offset is given. |

```bash
.venv/bin/python -m ns_status collect-once --route-id utrecht-amsterdam-centraal --at 2026-03-10T21:22
```

### `collect-window`

Collects all routes across every time slot in a named sampling window (defined in `routes.json` with start/end times and an interval). Generates each slot (e.g. every 15 minutes from 07:00–09:00), fetches trips for each route at each slot, and bulk-upserts everything.

| Option | Required | Description |
|--------|----------|-------------|
| `--window` | yes | Sampling window name from `routes.json` (e.g. `morning_rush`) |
| `--date` | no | Collection date as `YYYY-MM-DD`. Defaults to today. |
| `--route-id` | no | Optional filter; can be repeated to limit to specific routes. |

```bash
.venv/bin/python -m ns_status collect-window --window morning_rush --date 2026-03-11
```

Use a custom database path if you want:

```bash
.venv/bin/python -m ns_status collect-window --window evening_rush --db data/custom.db
```

### `serve`

Starts the FastAPI status dashboard via uvicorn. The `--config` and `--db` global options are forwarded to the web app so it reads from the same database.

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Bind port |
| `--reload` | off | Enable auto-reload for development |

```bash
.venv/bin/python -m ns_status serve --host 127.0.0.1 --port 8000
```

## Delay grades

- `1`: 0 to 2 minutes
- `2`: more than 2 to 5 minutes
- `3`: more than 5 to 10 minutes
- `4`: more than 10 to 20 minutes
- `5`: more than 20 minutes, or any cancellation/partial cancellation

## Notes

- The collector is built around a public frontend API contract, so NS may change it without notice.
- The default route file includes the Utrecht Centraal -> Amsterdam Centraal route from your example.
- Re-running collection for a trip that was already seen today updates the existing row instead of inserting a duplicate (keyed by `route_id + trip_uid + service_day`).
- The dashboard shows daily route status for the past 30 days, based only on whatever samples you have collected.
