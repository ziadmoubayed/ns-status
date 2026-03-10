from __future__ import annotations

import json
from datetime import time
from pathlib import Path

from .models import AppConfig, RouteConfig, SamplingWindow


DEFAULT_CONFIG_PATH = Path("routes.json")


def load_config(path: Path | str | None = None) -> AppConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    routes = tuple(
        RouteConfig(
            route_id=item["route_id"],
            origin_name=item["origin_name"],
            origin_uic_code=item["origin_uic_code"],
            destination_name=item["destination_name"],
            destination_uic_code=item["destination_uic_code"],
            disabled_transport_modalities=tuple(
                item.get("disabled_transport_modalities", ("BUS", "TRAM", "METRO", "FERRY"))
            ),
        )
        for item in raw["routes"]
    )

    route_ids = {route.route_id for route in routes}
    if len(route_ids) != len(routes):
        raise ValueError("Duplicate route_id values found in config.")

    windows = tuple(
        SamplingWindow(
            name=item["name"],
            start=_parse_time(item["start"]),
            end=_parse_time(item["end"]),
            interval_minutes=int(item["interval_minutes"]),
        )
        for item in raw["sampling_windows"]
    )

    window_names = {window.name for window in windows}
    if len(window_names) != len(windows):
        raise ValueError("Duplicate sampling window names found in config.")

    return AppConfig(
        timezone_name=raw.get("timezone", "Europe/Amsterdam"),
        routes=routes,
        sampling_windows=windows,
    )


def _parse_time(raw: str) -> time:
    hour_text, minute_text = raw.split(":")
    return time(hour=int(hour_text), minute=int(minute_text))
