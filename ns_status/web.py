from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import load_config
from .reporting import StatusRepository


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app() -> FastAPI:
    config_path = Path(os.getenv("NS_STATUS_CONFIG", BASE_DIR / "routes.json"))
    db_path = Path(os.getenv("NS_STATUS_DB", BASE_DIR / "data/ns_status.db"))

    config = load_config(config_path)
    repository = StatusRepository(db_path, rush_hours=config.rush_hours)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app = FastAPI(title="NS Route Status", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        today = date.today()
        overview = repository.build_dashboard(config.routes, days=30, today=today)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "overview": overview,
                "page_title": "Dashboard",
                "page_subtitle": "Daily availability for the past 30 days, based on collected rush-hour samples.",
                "window_days": 30,
                "is_index": True,
                "start_day": today - timedelta(days=29),
                "end_day": today,
            },
        )

    @app.get("/routes/{route_id}/days/{day}", response_class=HTMLResponse)
    def day_detail(request: Request, route_id: str, day: str) -> HTMLResponse:
        try:
            route = config.route_by_id(route_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown route.") from exc

        try:
            service_day = date.fromisoformat(day)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.") from exc

        detail = repository.build_day_detail(route, service_day)
        return templates.TemplateResponse(
            request=request,
            name="day_detail.html",
            context={
                "detail": detail,
                "route_id": route_id,
                "page_title": f"{detail.display_name} · {detail.day_label}",
                "page_subtitle": f"All trip samples collected for {detail.day.isoformat()}.",
                "window_days": 30,
                "is_index": False,
            },
        )

    return app


app = create_app()
