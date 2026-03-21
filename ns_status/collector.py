from __future__ import annotations

from datetime import datetime, timedelta

from .client import NSClient
from .models import RouteConfig, RouteSnapshot, TripObservation


def collect_snapshot(
    client: NSClient,
    route: RouteConfig,
    requested_datetime: datetime,
    *,
    sampled_at: datetime | None = None,
) -> RouteSnapshot:
    sampled_at = sampled_at or datetime.now(requested_datetime.tzinfo)
    raw_response = client.fetch_route(route, requested_datetime)
    raw_trips = raw_response.get("trips", [])
    if not isinstance(raw_trips, list):
        raise ValueError("Expected trips to be a list.")

    trips = tuple(
        _build_trip_observation(
            route=route,
            raw_trip=raw_trip,
            trip_index=index,
            requested_datetime=requested_datetime,
            sampled_at=sampled_at,
        )
        for index, raw_trip in enumerate(raw_trips)
        if isinstance(raw_trip, dict)
    )

    return RouteSnapshot(
        route=route,
        sampled_at=sampled_at,
        requested_datetime=requested_datetime,
        source=str(raw_response.get("source", "")),
        raw_response=raw_response,
        trips=trips,
    )


def grade_delay(
    delay_seconds: int,
    *,
    cancelled: bool = False,
    part_cancelled: bool = False,
) -> int:
    if cancelled or part_cancelled:
        return 5
    normalized = max(delay_seconds, 0)
    if normalized <= 120:
        return 1
    if normalized <= 300:
        return 2
    if normalized <= 600:
        return 3
    if normalized <= 1200:
        return 4
    return 5


def status_label(
    *,
    cancelled: bool,
    part_cancelled: bool,
    delay_grade: int,
) -> str:
    if cancelled:
        return "cancelled"
    if part_cancelled:
        return "part_cancelled"
    if delay_grade == 1:
        return "on_time"
    return "delayed"


def _build_trip_observation(
    *,
    route: RouteConfig,
    raw_trip: dict[str, object],
    trip_index: int,
    requested_datetime: datetime,
    sampled_at: datetime,
) -> TripObservation:
    legs = [leg for leg in raw_trip.get("legs", []) if isinstance(leg, dict)]
    first_leg = legs[0] if legs else {}
    last_leg = legs[-1] if legs else {}
    origin = first_leg.get("origin", {}) if isinstance(first_leg.get("origin", {}), dict) else {}
    destination = (
        last_leg.get("destination", {}) if isinstance(last_leg.get("destination", {}), dict) else {}
    )

    planned_departure = _parse_ns_datetime(origin.get("plannedDateTime"))
    actual_departure = _parse_ns_datetime(origin.get("actualDateTime"))
    planned_arrival = _parse_ns_datetime(destination.get("plannedDateTime"))
    actual_arrival = _parse_ns_datetime(destination.get("actualDateTime"))

    departure_delay = _delay_seconds(planned_departure, actual_departure)
    arrival_delay = _delay_seconds(planned_arrival, actual_arrival)
    stop_delay_values = _collect_stop_delay_values(legs)
    max_delay_seconds = max([departure_delay, arrival_delay, *stop_delay_values], default=0)

    cancelled = any(bool(leg.get("cancelled")) for leg in legs)
    part_cancelled = any(bool(leg.get("partCancelled")) for leg in legs)
    delay_grade = grade_delay(
        max_delay_seconds,
        cancelled=cancelled,
        part_cancelled=part_cancelled,
    )
    primary_leg = _find_primary_public_transit_leg(legs)
    train_product = primary_leg.get("product", {}) if isinstance(primary_leg.get("product", {}), dict) else {}

    return TripObservation(
        route_id=route.route_id,
        sampled_at=sampled_at,
        requested_datetime=requested_datetime,
        trip_index=trip_index,
        trip_uid=str(raw_trip.get("uid", "")),
        ns_status=str(raw_trip.get("status", "")),
        status_label=status_label(
            cancelled=cancelled,
            part_cancelled=part_cancelled,
            delay_grade=delay_grade,
        ),
        planned_departure_at=planned_departure or requested_datetime,
        actual_departure_at=actual_departure,
        planned_arrival_at=planned_arrival or requested_datetime,
        actual_arrival_at=actual_arrival,
        planned_duration_minutes=_safe_int(raw_trip.get("plannedDurationInMinutes")),
        actual_duration_minutes=_safe_int(raw_trip.get("actualDurationInMinutes")),
        departure_delay_seconds=departure_delay,
        arrival_delay_seconds=arrival_delay,
        max_delay_seconds=max_delay_seconds,
        delay_grade=delay_grade,
        cancelled=cancelled,
        part_cancelled=part_cancelled,
        transfer_count=_safe_int(raw_trip.get("transfers")) or 0,
        crowd_forecast=_safe_str(raw_trip.get("crowdForecast")),
        train_category=_safe_str(train_product.get("shortCategoryName")),
        train_number=_safe_str(train_product.get("number")),
        train_direction=_safe_str(primary_leg.get("direction")),
        punctuality=_safe_float(raw_trip.get("punctuality")),
    )


def _find_primary_public_transit_leg(legs: list[dict[str, object]]) -> dict[str, object]:
    for leg in legs:
        if leg.get("travelType") == "PUBLIC_TRANSIT":
            return leg
    return legs[0] if legs else {}


def _collect_stop_delay_values(legs: list[dict[str, object]]) -> list[int]:
    values: list[int] = []
    for leg in legs:
        stops = leg.get("stops", [])
        if not isinstance(stops, list):
            continue
        for stop in stops:
            if not isinstance(stop, dict):
                continue
            values.append(_safe_int(stop.get("departureDelayInSeconds")) or 0)
            values.append(_safe_int(stop.get("arrivalDelayInSeconds")) or 0)
    return values


def _delay_seconds(planned: datetime | None, actual: datetime | None) -> int:
    if planned is None or actual is None:
        return 0
    return max(int((actual - planned).total_seconds()), 0)


def _parse_ns_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _safe_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
