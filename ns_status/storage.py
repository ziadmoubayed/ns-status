from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import RouteSnapshot


class Storage:
    def __init__(self, db_path: Path | str = Path("data/ns_status.db")) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON;")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT NOT NULL,
                    origin_name TEXT NOT NULL,
                    origin_uic_code TEXT NOT NULL,
                    destination_name TEXT NOT NULL,
                    destination_uic_code TEXT NOT NULL,
                    sampled_at TEXT NOT NULL,
                    requested_datetime TEXT NOT NULL,
                    api_source TEXT NOT NULL,
                    trip_count INTEGER NOT NULL,
                    raw_response TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS trip_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
                    route_id TEXT NOT NULL,
                    sampled_at TEXT NOT NULL,
                    requested_datetime TEXT NOT NULL,
                    trip_index INTEGER NOT NULL,
                    trip_uid TEXT NOT NULL,
                    ns_status TEXT NOT NULL,
                    status_label TEXT NOT NULL,
                    planned_departure_at TEXT NOT NULL,
                    actual_departure_at TEXT,
                    planned_arrival_at TEXT NOT NULL,
                    actual_arrival_at TEXT,
                    planned_duration_minutes INTEGER,
                    actual_duration_minutes INTEGER,
                    departure_delay_seconds INTEGER NOT NULL,
                    arrival_delay_seconds INTEGER NOT NULL,
                    max_delay_seconds INTEGER NOT NULL,
                    delay_grade INTEGER NOT NULL,
                    cancelled INTEGER NOT NULL,
                    part_cancelled INTEGER NOT NULL,
                    transfer_count INTEGER NOT NULL,
                    crowd_forecast TEXT,
                    train_category TEXT,
                    train_number TEXT,
                    train_direction TEXT,
                    punctuality REAL
                );

                CREATE INDEX IF NOT EXISTS idx_trip_samples_route_time
                    ON trip_samples(route_id, requested_datetime);

                CREATE INDEX IF NOT EXISTS idx_trip_samples_route_sampled
                    ON trip_samples(route_id, sampled_at);
                """
            )
            self._deduplicate_scrape_runs(connection)
            self._deduplicate_trip_samples(connection)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_scrape_runs_route_requested_datetime
                    ON scrape_runs(route_id, requested_datetime)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trip_samples_run_trip_index
                    ON trip_samples(run_id, trip_index)
                """
            )

    def store_snapshot(self, snapshot: RouteSnapshot) -> int:
        raw_response = json.dumps(snapshot.raw_response, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON;")
            connection.execute(
                """
                INSERT INTO scrape_runs (
                    route_id,
                    origin_name,
                    origin_uic_code,
                    destination_name,
                    destination_uic_code,
                    sampled_at,
                    requested_datetime,
                    api_source,
                    trip_count,
                    raw_response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(route_id, requested_datetime) DO UPDATE SET
                    origin_name = excluded.origin_name,
                    origin_uic_code = excluded.origin_uic_code,
                    destination_name = excluded.destination_name,
                    destination_uic_code = excluded.destination_uic_code,
                    sampled_at = excluded.sampled_at,
                    api_source = excluded.api_source,
                    trip_count = excluded.trip_count,
                    raw_response = excluded.raw_response
                """,
                (
                    snapshot.route.route_id,
                    snapshot.route.origin_name,
                    snapshot.route.origin_uic_code,
                    snapshot.route.destination_name,
                    snapshot.route.destination_uic_code,
                    snapshot.sampled_at.isoformat(),
                    snapshot.requested_datetime.isoformat(),
                    snapshot.source,
                    len(snapshot.trips),
                    raw_response,
                ),
            )
            run_id = int(
                connection.execute(
                    """
                    SELECT id
                    FROM scrape_runs
                    WHERE route_id = ? AND requested_datetime = ?
                    """,
                    (
                        snapshot.route.route_id,
                        snapshot.requested_datetime.isoformat(),
                    ),
                ).fetchone()[0]
            )
            connection.execute("DELETE FROM trip_samples WHERE run_id = ?", (run_id,))

            connection.executemany(
                """
                INSERT INTO trip_samples (
                    run_id,
                    route_id,
                    sampled_at,
                    requested_datetime,
                    trip_index,
                    trip_uid,
                    ns_status,
                    status_label,
                    planned_departure_at,
                    actual_departure_at,
                    planned_arrival_at,
                    actual_arrival_at,
                    planned_duration_minutes,
                    actual_duration_minutes,
                    departure_delay_seconds,
                    arrival_delay_seconds,
                    max_delay_seconds,
                    delay_grade,
                    cancelled,
                    part_cancelled,
                    transfer_count,
                    crowd_forecast,
                    train_category,
                    train_number,
                    train_direction,
                    punctuality
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        trip.route_id,
                        trip.sampled_at.isoformat(),
                        trip.requested_datetime.isoformat(),
                        trip.trip_index,
                        trip.trip_uid,
                        trip.ns_status,
                        trip.status_label,
                        trip.planned_departure_at.isoformat(),
                        trip.actual_departure_at.isoformat() if trip.actual_departure_at else None,
                        trip.planned_arrival_at.isoformat(),
                        trip.actual_arrival_at.isoformat() if trip.actual_arrival_at else None,
                        trip.planned_duration_minutes,
                        trip.actual_duration_minutes,
                        trip.departure_delay_seconds,
                        trip.arrival_delay_seconds,
                        trip.max_delay_seconds,
                        trip.delay_grade,
                        int(trip.cancelled),
                        int(trip.part_cancelled),
                        trip.transfer_count,
                        trip.crowd_forecast,
                        trip.train_category,
                        trip.train_number,
                        trip.train_direction,
                        trip.punctuality,
                    )
                    for trip in snapshot.trips
                ],
            )
            return run_id

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _deduplicate_scrape_runs(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM scrape_runs
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM scrape_runs
                GROUP BY route_id, requested_datetime
            )
            """
        )

    def _deduplicate_trip_samples(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM trip_samples
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM trip_samples
                GROUP BY run_id, trip_index
            )
            """
        )
