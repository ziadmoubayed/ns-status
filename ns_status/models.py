from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any


@dataclass(frozen=True)
class RouteConfig:
    route_id: str
    origin_name: str
    origin_uic_code: str
    destination_name: str
    destination_uic_code: str
    disabled_transport_modalities: tuple[str, ...] = ("BUS", "TRAM", "METRO", "FERRY")


@dataclass(frozen=True)
class RushHourWindow:
    start: time
    end: time


@dataclass(frozen=True)
class AppConfig:
    timezone_name: str
    routes: tuple[RouteConfig, ...]
    rush_hours: tuple[RushHourWindow, ...]

    def route_by_id(self, route_id: str) -> RouteConfig:
        for route in self.routes:
            if route.route_id == route_id:
                return route
        raise KeyError(f"Unknown route_id: {route_id}")


@dataclass(frozen=True)
class TripObservation:
    route_id: str
    sampled_at: datetime
    requested_datetime: datetime
    trip_index: int
    trip_uid: str
    ns_status: str
    status_label: str
    planned_departure_at: datetime
    actual_departure_at: datetime | None
    planned_arrival_at: datetime
    actual_arrival_at: datetime | None
    planned_duration_minutes: int | None
    actual_duration_minutes: int | None
    departure_delay_seconds: int
    arrival_delay_seconds: int
    max_delay_seconds: int
    delay_grade: int
    cancelled: bool
    part_cancelled: bool
    transfer_count: int
    crowd_forecast: str | None
    train_category: str | None
    train_number: str | None
    train_direction: str | None
    punctuality: float | None


@dataclass(frozen=True)
class RouteSnapshot:
    route: RouteConfig
    sampled_at: datetime
    requested_datetime: datetime
    source: str
    raw_response: dict[str, Any]
    trips: tuple[TripObservation, ...] = field(default_factory=tuple)
