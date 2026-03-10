from __future__ import annotations

import os
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
    repository = StatusRepository(db_path)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    app = FastAPI(title="NS Route Status", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        overview = repository.build_dashboard(config.routes, days=30)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "overview": overview,
                "page_title": "NS Route Status",
                "page_subtitle": "Daily availability for the past 30 days, based on collected rush-hour samples.",
                "window_days": 30,
            },
        )

    @app.get("/routes/{route_id}", response_class=HTMLResponse)
    def route_detail(request: Request, route_id: str) -> HTMLResponse:
        try:
            route = config.route_by_id(route_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown route.") from exc

        dashboard = repository.build_route_dashboard(route, days=30)
        return templates.TemplateResponse(
            request=request,
            name="route_detail.html",
            context={
                "route": dashboard,
                "page_title": dashboard.display_name,
                "page_subtitle": "Past 30 days of daily route health from stored NS trip samples.",
                "window_days": 30,
            },
        )

    return app


app = create_app()
