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

List configured routes and windows:

```bash
python3 -m ns_status list-routes
```

Collect one route at one requested departure time:

```bash
python3 -m ns_status collect-once --route-id utrecht-amsterdam-centraal --at 2026-03-10T21:22
```

Collect all configured routes for a rush-hour window on a given day:

```bash
python3 -m ns_status collect-window --window morning_rush --date 2026-03-11
```

Use a custom database path if you want:

```bash
python3 -m ns_status collect-window --window evening_rush --db data/custom.db
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
- Re-running the same route/time collection updates the existing stored snapshot instead of inserting duplicates.
