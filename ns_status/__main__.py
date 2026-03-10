from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .client import NSClient
from .collector import collect_snapshot, collect_window_snapshots
from .config import DEFAULT_CONFIG_PATH, load_config
from .storage import Storage


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    config = load_config(args.config)
    timezone = ZoneInfo(config.timezone_name)

    if args.command == "list-routes":
        print("Routes:")
        for route in config.routes:
            print(
                f"- {route.route_id}: {route.origin_name} ({route.origin_uic_code}) -> "
                f"{route.destination_name} ({route.destination_uic_code})"
            )
        print("Sampling windows:")
        for window in config.sampling_windows:
            print(
                f"- {window.name}: {window.start.strftime('%H:%M')} to "
                f"{window.end.strftime('%H:%M')} every {window.interval_minutes}m"
            )
        return

    storage = Storage(args.db)
    storage.initialize()
    client = NSClient()

    if args.command == "collect-once":
        route = config.route_by_id(args.route_id)
        requested_datetime = parse_datetime_arg(args.at, timezone)
        snapshot = collect_snapshot(client, route, requested_datetime)
        run_id = storage.store_snapshot(snapshot)
        print(f"Upserted run {run_id} with {len(snapshot.trips)} trips for {route.route_id}.")
        _print_trip_summaries(snapshot)
        return

    if args.command == "collect-window":
        window = config.window_by_name(args.window)
        collection_date = date.fromisoformat(args.date) if args.date else datetime.now(timezone).date()
        route_ids = set(args.route_id) if args.route_id else None
        snapshots = collect_window_snapshots(client, config, window, collection_date, route_ids)
        run_count = 0
        for snapshot in snapshots:
            storage.store_snapshot(snapshot)
            run_count += 1
        print(
            f"Upserted {run_count} runs across {len(snapshots)} route/time combinations "
            f"for {window.name} on {collection_date.isoformat()}."
        )
        return

    if args.command == "serve":
        os.environ["NS_STATUS_CONFIG"] = str(args.config)
        os.environ["NS_STATUS_DB"] = str(args.db)
        import uvicorn

        uvicorn.run("ns_status.web:app", host=args.host, port=args.port, reload=args.reload)
        return

    raise ValueError(f"Unsupported command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect route-level NS delay data into SQLite.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the routes JSON config file.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/ns_status.db"),
        help="SQLite database path.",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-routes", help="List configured routes and sampling windows.")

    collect_once = subparsers.add_parser("collect-once", help="Collect one route at one time.")
    collect_once.add_argument("--route-id", required=True, help="Route identifier from routes.json.")
    collect_once.add_argument(
        "--at",
        required=True,
        help="Requested departure datetime in ISO-8601 format, for example 2026-03-10T21:22.",
    )

    collect_window = subparsers.add_parser(
        "collect-window",
        help="Collect all route snapshots for a configured sampling window.",
    )
    collect_window.add_argument("--window", required=True, help="Sampling window name from routes.json.")
    collect_window.add_argument("--date", help="Collection date in YYYY-MM-DD. Defaults to today.")
    collect_window.add_argument(
        "--route-id",
        action="append",
        help="Optional route filter. Repeat to collect more than one route.",
    )

    serve = subparsers.add_parser("serve", help="Run the FastAPI status dashboard.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host.")
    serve.add_argument("--port", type=int, default=8000, help="Bind port.")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development.")

    return parser


def parse_datetime_arg(raw: str, timezone: ZoneInfo) -> datetime:
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _print_trip_summaries(snapshot) -> None:
    for trip in snapshot.trips:
        planned_departure = trip.planned_departure_at.strftime("%H:%M")
        planned_arrival = trip.planned_arrival_at.strftime("%H:%M")
        actual_arrival = (
            trip.actual_arrival_at.strftime("%H:%M")
            if trip.actual_arrival_at is not None
            else planned_arrival
        )
        delay_minutes = trip.max_delay_seconds // 60
        train_label = " ".join(part for part in [trip.train_category, trip.train_number] if part)
        print(
            f"- trip {trip.trip_index}: {planned_departure}->{planned_arrival} "
            f"(actual arrival {actual_arrival}), grade {trip.delay_grade}, "
            f"status {trip.status_label}, delay {delay_minutes}m, {train_label or 'unknown train'}"
        )


if __name__ == "__main__":
    main()
