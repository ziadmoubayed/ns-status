from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ns_status.collector import grade_delay, iter_window_datetimes
from ns_status.models import RouteConfig, RouteSnapshot, SamplingWindow, TripObservation
from ns_status.storage import Storage


class GradeDelayTests(unittest.TestCase):
    def test_grade_delay_bands(self) -> None:
        self.assertEqual(grade_delay(0), 1)
        self.assertEqual(grade_delay(120), 1)
        self.assertEqual(grade_delay(121), 2)
        self.assertEqual(grade_delay(300), 2)
        self.assertEqual(grade_delay(301), 3)
        self.assertEqual(grade_delay(600), 3)
        self.assertEqual(grade_delay(601), 4)
        self.assertEqual(grade_delay(1200), 4)
        self.assertEqual(grade_delay(1201), 5)

    def test_cancellation_forces_grade_five(self) -> None:
        self.assertEqual(grade_delay(0, cancelled=True), 5)
        self.assertEqual(grade_delay(0, part_cancelled=True), 5)


class WindowIteratorTests(unittest.TestCase):
    def test_window_generation_is_inclusive(self) -> None:
        window = SamplingWindow(name="morning", start=_time("07:00"), end=_time("07:30"), interval_minutes=15)
        points = iter_window_datetimes(window, date(2026, 3, 10), ZoneInfo("Europe/Amsterdam"))
        self.assertEqual(
            [point.strftime("%H:%M") for point in points],
            ["07:00", "07:15", "07:30"],
        )


class StorageTests(unittest.TestCase):
    def test_store_snapshot_is_idempotent_for_route_and_requested_datetime(self) -> None:
        route = RouteConfig(
            route_id="utrecht-amsterdam-centraal",
            origin_name="Utrecht Centraal",
            origin_uic_code="8400621",
            destination_name="Amsterdam Centraal",
            destination_uic_code="8400058",
        )
        requested_at = datetime.fromisoformat("2026-03-10T07:00:00+01:00")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ns_status.db"
            storage = Storage(db_path)
            storage.initialize()

            first = _snapshot(route, requested_at, sampled_at="2026-03-10T06:58:00+01:00", delay_seconds=0)
            second = _snapshot(route, requested_at, sampled_at="2026-03-10T07:01:00+01:00", delay_seconds=300)

            storage.store_snapshot(first)
            storage.store_snapshot(second)

            with sqlite3.connect(db_path) as connection:
                run_count = connection.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
                trip_count = connection.execute("SELECT COUNT(*) FROM trip_samples").fetchone()[0]
                sampled_at = connection.execute(
                    "SELECT sampled_at FROM scrape_runs WHERE route_id = ? AND requested_datetime = ?",
                    (route.route_id, requested_at.isoformat()),
                ).fetchone()[0]
                max_delay_seconds = connection.execute(
                    "SELECT max_delay_seconds FROM trip_samples"
                ).fetchone()[0]

            self.assertEqual(run_count, 1)
            self.assertEqual(trip_count, 1)
            self.assertEqual(sampled_at, "2026-03-10T07:01:00+01:00")
            self.assertEqual(max_delay_seconds, 300)

    def test_same_trip_uid_different_scrape_times_upserts(self) -> None:
        """When cron collects every 5 min, the same trip_uid on the same day should be upserted."""
        route = RouteConfig(
            route_id="utrecht-amsterdam-centraal",
            origin_name="Utrecht Centraal",
            origin_uic_code="8400621",
            destination_name="Amsterdam Centraal",
            destination_uic_code="8400058",
        )
        first_at = datetime.fromisoformat("2026-03-10T07:00:00+01:00")
        second_at = datetime.fromisoformat("2026-03-10T07:05:00+01:00")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ns_status.db"
            storage = Storage(db_path)
            storage.initialize()

            first = _snapshot(route, first_at, sampled_at="2026-03-10T07:00:00+01:00", delay_seconds=0)
            second = _snapshot(route, second_at, sampled_at="2026-03-10T07:05:00+01:00", delay_seconds=120)

            storage.store_snapshot(first)
            storage.store_snapshot(second)

            with sqlite3.connect(db_path) as connection:
                trip_count = connection.execute("SELECT COUNT(*) FROM trip_samples").fetchone()[0]
                max_delay = connection.execute("SELECT max_delay_seconds FROM trip_samples").fetchone()[0]
                service_day = connection.execute("SELECT service_day FROM trip_samples").fetchone()[0]

            # Same trip_uid on same day → one row, updated with latest data
            self.assertEqual(trip_count, 1)
            self.assertEqual(max_delay, 120)
            self.assertEqual(service_day, "2026-03-10")


def _time(raw: str):
    hour, minute = raw.split(":")
    from datetime import time

    return time(hour=int(hour), minute=int(minute))


def _snapshot(route: RouteConfig, requested_at: datetime, *, sampled_at: str, delay_seconds: int) -> RouteSnapshot:
    sampled_datetime = datetime.fromisoformat(sampled_at)
    planned_departure = requested_at
    planned_arrival = requested_at + timedelta(minutes=26)
    actual_arrival = planned_arrival + timedelta(seconds=delay_seconds)
    trip = TripObservation(
        route_id=route.route_id,
        sampled_at=sampled_datetime,
        requested_datetime=requested_at,
        trip_index=0,
        trip_uid="trip-0",
        ns_status="NORMAL",
        status_label="on_time" if delay_seconds == 0 else "delayed",
        planned_departure_at=planned_departure,
        actual_departure_at=planned_departure,
        planned_arrival_at=planned_arrival,
        actual_arrival_at=actual_arrival,
        planned_duration_minutes=26,
        actual_duration_minutes=26 + (delay_seconds // 60),
        departure_delay_seconds=0,
        arrival_delay_seconds=delay_seconds,
        max_delay_seconds=delay_seconds,
        delay_grade=1 if delay_seconds == 0 else 2,
        cancelled=False,
        part_cancelled=False,
        transfer_count=0,
        crowd_forecast="LOW",
        train_category="IC",
        train_number="2974",
        train_direction="Enkhuizen",
        punctuality=100.0,
    )
    return RouteSnapshot(
        route=route,
        sampled_at=sampled_datetime,
        requested_datetime=requested_at,
        source="HARP",
        raw_response={"source": "HARP", "trips": [{"uid": "trip-0"}]},
        trips=(trip,),
    )


if __name__ == "__main__":
    unittest.main()
