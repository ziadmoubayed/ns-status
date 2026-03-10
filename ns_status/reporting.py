from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import RouteConfig


SCORE_CASE = """
CASE
    WHEN cancelled = 1 OR part_cancelled = 1 THEN 0
    WHEN delay_grade = 1 THEN 100
    WHEN delay_grade = 2 THEN 85
    WHEN delay_grade = 3 THEN 65
    WHEN delay_grade = 4 THEN 40
    ELSE 10
END
"""


@dataclass(frozen=True)
class DailyRouteStatus:
    day: date
    day_label: str
    availability_score: float | None
    sample_count: int
    run_count: int
    cancellation_count: int
    worst_delay_minutes: int | None
    last_sampled_at: datetime | None
    has_data: bool
    status_label: str
    tone: str


@dataclass(frozen=True)
class RouteDashboard:
    route_id: str
    origin_name: str
    destination_name: str
    display_name: str
    days: tuple[DailyRouteStatus, ...]
    latest_day: DailyRouteStatus | None
    thirty_day_average: float | None


@dataclass(frozen=True)
class TripDetail:
    trip_uid: str
    trip_index: int
    ns_status: str
    status_label: str
    planned_departure: str
    actual_departure: str | None
    planned_arrival: str
    actual_arrival: str | None
    planned_duration_minutes: int | None
    actual_duration_minutes: int | None
    departure_delay_seconds: int
    arrival_delay_seconds: int
    max_delay_seconds: int
    delay_grade: int
    delay_grade_label: str
    cancelled: bool
    part_cancelled: bool
    transfer_count: int
    crowd_forecast: str | None
    train_category: str | None
    train_number: str | None
    requested_datetime: str
    sampled_at: str


@dataclass(frozen=True)
class DayDetail:
    route_id: str
    display_name: str
    day: date
    day_label: str
    availability_score: float | None
    status_label: str
    tone: str
    sample_count: int
    cancellation_count: int
    worst_delay_minutes: int | None
    trips: tuple[TripDetail, ...]
    grade_distribution: dict[int, int]
    has_data: bool


@dataclass(frozen=True)
class DashboardOverview:
    route_dashboards: tuple[RouteDashboard, ...]
    total_routes: int
    routes_with_data: int
    healthy_routes: int
    alerting_routes: int
    thirty_day_average: float | None


class StatusRepository:
    def __init__(self, db_path: Path | str = Path("data/ns_status.db")) -> None:
        self.db_path = Path(db_path)

    def build_dashboard(
        self,
        routes: tuple[RouteConfig, ...],
        *,
        days: int = 30,
        today: date | None = None,
    ) -> DashboardOverview:
        route_dashboards = tuple(self._build_route_dashboard(route, days=days, today=today) for route in routes)
        sorted_dashboards = tuple(sorted(route_dashboards, key=_dashboard_sort_key))
        with_data = [dashboard for dashboard in sorted_dashboards if dashboard.latest_day is not None]
        latest_scores = [dashboard.latest_day.availability_score for dashboard in with_data if dashboard.latest_day]
        healthy_routes = sum(1 for dashboard in with_data if dashboard.latest_day and dashboard.latest_day.tone == "good")
        alerting_routes = sum(1 for dashboard in with_data if dashboard.latest_day and dashboard.latest_day.tone not in {"good", "no-data"})
        return DashboardOverview(
            route_dashboards=sorted_dashboards,
            total_routes=len(sorted_dashboards),
            routes_with_data=len(with_data),
            healthy_routes=healthy_routes,
            alerting_routes=alerting_routes,
            thirty_day_average=_average_score([score for score in latest_scores if score is not None]),
        )

    def build_route_dashboard(
        self,
        route: RouteConfig,
        *,
        days: int = 30,
        today: date | None = None,
    ) -> RouteDashboard:
        return self._build_route_dashboard(route, days=days, today=today)

    def _build_route_dashboard(
        self,
        route: RouteConfig,
        *,
        days: int = 30,
        today: date | None = None,
    ) -> RouteDashboard:
        today = today or date.today()
        start_day = today - timedelta(days=days - 1)
        metrics_by_route = self._load_daily_metrics(start_day=start_day, end_day=today)
        metrics = metrics_by_route.get(route.route_id, {})

        day_series = tuple(
            self._build_day_status(day_cursor, metrics.get(day_cursor))
            for day_cursor in _iter_days(start_day, today)
        )
        scored_days = [day for day in day_series if day.has_data and day.availability_score is not None]
        latest_day = scored_days[-1] if scored_days else None
        average = _average_score([day.availability_score for day in scored_days if day.availability_score is not None])
        return RouteDashboard(
            route_id=route.route_id,
            origin_name=route.origin_name,
            destination_name=route.destination_name,
            display_name=f"{route.origin_name} -> {route.destination_name}",
            days=day_series,
            latest_day=latest_day,
            thirty_day_average=average,
        )

    def _load_daily_metrics(
        self,
        *,
        start_day: date,
        end_day: date,
    ) -> dict[str, dict[date, sqlite3.Row]]:
        if not self.db_path.exists():
            return {}

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT
                    route_id,
                    substr(requested_datetime, 1, 10) AS service_day,
                    COUNT(*) AS sample_count,
                    COUNT(DISTINCT run_id) AS run_count,
                    ROUND(AVG({SCORE_CASE}), 1) AS availability_score,
                    SUM(CASE WHEN cancelled = 1 OR part_cancelled = 1 THEN 1 ELSE 0 END) AS cancellation_count,
                    MAX(max_delay_seconds) AS worst_delay_seconds,
                    MAX(sampled_at) AS last_sampled_at
                FROM trip_samples
                WHERE substr(requested_datetime, 1, 10) BETWEEN ? AND ?
                GROUP BY route_id, service_day
                ORDER BY service_day ASC
                """,
                (start_day.isoformat(), end_day.isoformat()),
            ).fetchall()

        metrics: dict[str, dict[date, sqlite3.Row]] = {}
        for row in rows:
            route_id = str(row["route_id"])
            service_day = date.fromisoformat(str(row["service_day"]))
            metrics.setdefault(route_id, {})[service_day] = row
        return metrics

    def _build_day_status(self, service_day: date, row: sqlite3.Row | None) -> DailyRouteStatus:
        if row is None:
            return DailyRouteStatus(
                day=service_day,
                day_label=service_day.strftime("%b %d"),
                availability_score=None,
                sample_count=0,
                run_count=0,
                cancellation_count=0,
                worst_delay_minutes=None,
                last_sampled_at=None,
                has_data=False,
                status_label="No Data",
                tone="no-data",
            )

        score = float(row["availability_score"])
        cancellation_count = int(row["cancellation_count"])
        label, tone = classify_score(score)
        return DailyRouteStatus(
            day=service_day,
            day_label=service_day.strftime("%b %d"),
            availability_score=score,
            sample_count=int(row["sample_count"]),
            run_count=int(row["run_count"]),
            cancellation_count=cancellation_count,
            worst_delay_minutes=_seconds_to_minutes(row["worst_delay_seconds"]),
            last_sampled_at=datetime.fromisoformat(str(row["last_sampled_at"])),
            has_data=True,
            status_label=label,
            tone=tone,
        )


    def build_day_detail(
        self,
        route: RouteConfig,
        service_day: date,
    ) -> DayDetail:
        display_name = f"{route.origin_name} -> {route.destination_name}"
        if not self.db_path.exists():
            return DayDetail(
                route_id=route.route_id,
                display_name=display_name,
                day=service_day,
                day_label=service_day.strftime("%b %d, %Y"),
                availability_score=None,
                status_label="No Data",
                tone="no-data",
                sample_count=0,
                cancellation_count=0,
                worst_delay_minutes=None,
                trips=(),
                grade_distribution={},
                has_data=False,
            )

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT
                    trip_uid,
                    trip_index,
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
                    requested_datetime,
                    sampled_at,
                    {SCORE_CASE} AS trip_score
                FROM trip_samples
                WHERE route_id = ?
                  AND substr(requested_datetime, 1, 10) = ?
                ORDER BY requested_datetime ASC, trip_index ASC
                """,
                (route.route_id, service_day.isoformat()),
            ).fetchall()

        trips: list[TripDetail] = []
        grade_dist: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        cancellation_count = 0
        worst_delay_seconds = 0
        score_sum = 0.0

        for row in rows:
            grade = int(row["delay_grade"])
            grade_dist[grade] = grade_dist.get(grade, 0) + 1
            cancelled = bool(row["cancelled"])
            part_cancelled = bool(row["part_cancelled"])
            if cancelled or part_cancelled:
                cancellation_count += 1
            delay = int(row["max_delay_seconds"])
            if delay > worst_delay_seconds:
                worst_delay_seconds = delay
            score_sum += float(row["trip_score"])
            trips.append(TripDetail(
                trip_uid=str(row["trip_uid"]),
                trip_index=int(row["trip_index"]),
                ns_status=str(row["ns_status"]),
                status_label=str(row["status_label"]),
                planned_departure=str(row["planned_departure_at"]),
                actual_departure=str(row["actual_departure_at"]) if row["actual_departure_at"] else None,
                planned_arrival=str(row["planned_arrival_at"]),
                actual_arrival=str(row["actual_arrival_at"]) if row["actual_arrival_at"] else None,
                planned_duration_minutes=int(row["planned_duration_minutes"]) if row["planned_duration_minutes"] is not None else None,
                actual_duration_minutes=int(row["actual_duration_minutes"]) if row["actual_duration_minutes"] is not None else None,
                departure_delay_seconds=int(row["departure_delay_seconds"]),
                arrival_delay_seconds=int(row["arrival_delay_seconds"]),
                max_delay_seconds=delay,
                delay_grade=grade,
                delay_grade_label=_grade_label(grade),
                cancelled=cancelled,
                part_cancelled=part_cancelled,
                transfer_count=int(row["transfer_count"]),
                crowd_forecast=str(row["crowd_forecast"]) if row["crowd_forecast"] else None,
                train_category=str(row["train_category"]) if row["train_category"] else None,
                train_number=str(row["train_number"]) if row["train_number"] else None,
                requested_datetime=str(row["requested_datetime"]),
                sampled_at=str(row["sampled_at"]),
            ))

        has_data = len(trips) > 0
        avg_score = round(score_sum / len(trips), 1) if trips else None
        label, tone = classify_score(avg_score) if avg_score is not None else ("No Data", "no-data")

        return DayDetail(
            route_id=route.route_id,
            display_name=display_name,
            day=service_day,
            day_label=service_day.strftime("%b %d, %Y"),
            availability_score=avg_score,
            status_label=label,
            tone=tone,
            sample_count=len(trips),
            cancellation_count=cancellation_count,
            worst_delay_minutes=_seconds_to_minutes(worst_delay_seconds) if worst_delay_seconds > 0 else None,
            trips=tuple(trips),
            grade_distribution=grade_dist,
            has_data=has_data,
        )


def _grade_label(grade: int) -> str:
    return {
        1: "On time",
        2: "Small delay",
        3: "Moderate delay",
        4: "Large delay",
        5: "Severe / Cancelled",
    }.get(grade, f"Grade {grade}")


def classify_score(score: float) -> tuple[str, str]:
    if score >= 95:
        return "Operational", "good"
    if score >= 80:
        return "Minor Delays", "watch"
    if score >= 60:
        return "Degraded", "warning"
    if score >= 40:
        return "Severe Delays", "bad"
    return "Major Disruption", "critical"


def _dashboard_sort_key(dashboard: RouteDashboard) -> tuple[bool, float, str]:
    latest_score = dashboard.latest_day.availability_score if dashboard.latest_day and dashboard.latest_day.availability_score is not None else 101.0
    return (dashboard.latest_day is None, latest_score, dashboard.display_name)


def _iter_days(start_day: date, end_day: date) -> tuple[date, ...]:
    days: list[date] = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor)
        cursor += timedelta(days=1)
    return tuple(days)


def _average_score(scores: list[float]) -> float | None:
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def _seconds_to_minutes(value: object) -> int | None:
    if value is None:
        return None
    seconds = int(value)
    return (seconds + 59) // 60
