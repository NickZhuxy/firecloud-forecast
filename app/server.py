"""FastAPI backend for the firecloud-forecast web app.

Endpoints:

    GET /api/overlay/cn?date     precomputed national fire-cloud overlay image
                                 (fixed geographic grid, clipped to China's
                                 border, cached per refresh slot)

The overlay is a fixed function of (date) — independent of the map viewport —
so zoom/pan never changes it or triggers recomputation. It uses the gate ×
modifier predictor (predictor.standard_predictor) over Open-Meteo data,
evaluated ~10 minutes before local sunset.

Single-point click analysis was removed (#40): the point-level score is not yet
mature enough to surface, so the app presents only the SunsetWx-style national
quality overview.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import app.overlay as overlay_mod
from predictor.fetch import OpenMeteoSource
from predictor.rules import standard_predictor

STATIC_DIR = Path(__file__).parent / "static"
CHINA_TZ = ZoneInfo("Asia/Shanghai")

app = FastAPI(title="Firecloud Forecast", version="0.2.0")

# Local single-user tool: permissive CORS so the page works even opened
# standalone (file:// preview) against this server.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"]
)

_source = OpenMeteoSource()
_predictor = standard_predictor(_source)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_date(date_str: str | None) -> date_cls:
    if not date_str:
        return datetime.now(CHINA_TZ).date()
    try:
        return date_cls.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"bad date: {date_str!r} (want YYYY-MM-DD)")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/overlay/cn")
def api_overlay_cn(date: str | None = Query(None)) -> dict:
    d = _parse_date(date)
    try:
        return overlay_mod.get_overlay(d, _source, _predictor, datetime.now(timezone.utc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"overlay failed: {exc}")


@app.get("/api/overlay/image/{cache_key}.png")
def api_overlay_image(cache_key: str) -> FileResponse:
    path = overlay_mod.cached_image_path(cache_key)
    if path is None:
        raise HTTPException(status_code=404, detail="overlay image not found")
    return FileResponse(path, media_type="image/png")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
