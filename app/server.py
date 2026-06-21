"""FastAPI backend for the firecloud-forecast web app.

Serves a Leaflet map frontend and two JSON endpoints:

    GET /api/forecast?lat&lon&date         single-point forecast at that
                                           location's sunset
    GET /api/forecast/grid?lat&lon&date    a probability grid around the point,
        &radius_deg&step_deg               fetched in one batch call

The predictor is the full physics-motivated gate × modifier model
(predictor.standard_predictor) fed by the free, global, key-less Open-Meteo
point-forecast API. Forecasts are evaluated at ~10 minutes before the local
sunset of the requested date, which is the heart of the fire-cloud window.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from predictor.features import derive
from predictor.fetch import OpenMeteoSource
from predictor.geometry import compute_geometry
from predictor.rules import standard_predictor

STATIC_DIR = Path(__file__).parent / "static"
SCORE_OFFSET = timedelta(minutes=10)  # score this long before sunset

app = FastAPI(title="Firecloud Forecast", version="0.1.0")

# Allow the page to call the API even when opened standalone (file:// preview
# panel, or a different host). This is a local single-user tool, so a permissive
# policy is appropriate.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_source = OpenMeteoSource()
_predictor = standard_predictor(_source)


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def _parse_date(date_str: str | None) -> date_cls:
    if not date_str:
        return datetime.now(timezone.utc).date()
    try:
        return date_cls.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"bad date: {date_str!r} (want YYYY-MM-DD)")


def _evening_instant(lon: float, d: date_cls) -> datetime:
    """A UTC instant near local evening (≈18:00 local) for date ``d``.

    Uses longitude to approximate the local-to-UTC offset, avoiding a timezone
    database. Good enough to land Open-Meteo's nearest-sunset pick on the
    correct evening.
    """
    base = datetime.combine(d, time_cls(18, 0), tzinfo=timezone.utc)
    return base - timedelta(hours=lon / 15.0)


def _resolve_sunset(lat: float, lon: float, d: date_cls) -> datetime:
    """Return the sunset instant for the local evening of date ``d``."""
    evening = _evening_instant(lon, d)
    probe = _source.fetch(lat, lon, evening)
    return probe.sunset_time or evening


# --------------------------------------------------------------------------- #
# Forecast assembly
# --------------------------------------------------------------------------- #
def _point_forecast(lat: float, lon: float, d: date_cls) -> dict:
    sunset = _resolve_sunset(lat, lon, d)
    t_score = sunset - SCORE_OFFSET

    snap = _source.fetch(lat, lon, t_score)
    feats = derive(snap, lat, lon, t_score)
    forecast = _predictor.score_snapshot(snap, lat, lon, t_score)
    geo = compute_geometry(feats.cloud_base_m, feats.visibility_m, lat)

    return {
        "lat": lat,
        "lon": lon,
        "date": d.isoformat(),
        "sunset_utc": sunset.isoformat(),
        "scored_utc": t_score.isoformat(),
        "probability": round(forecast.probability, 4),
        "gate_score": round(forecast.gate_score, 4) if forecast.gate_score is not None else None,
        "modifier_score": round(forecast.modifier_score, 4) if forecast.modifier_score is not None else None,
        "components": {k: round(v, 4) for k, v in forecast.components.items()},
        "explanation": forecast.explanation,
        "geometry": {
            "cloud_base_m": geo.cloud_base_m,
            "equivalent_cloud_base_m": round(geo.equivalent_cloud_base_m) if geo.equivalent_cloud_base_m is not None else None,
            "max_reach_km": round(geo.max_reach_km, 1) if geo.max_reach_km is not None else None,
            "duration_min": round(geo.duration_min, 1) if geo.duration_min is not None else None,
        },
        "inputs": {
            "cloud_low_pct": snap.cloud_low_pct,
            "cloud_mid_pct": snap.cloud_mid_pct,
            "cloud_high_pct": snap.cloud_high_pct,
            "humidity_pct": snap.humidity_pct,
            "visibility_m": snap.visibility_m,
            "source": snap.source_label,
        },
    }


def _grid_forecast(
    lat: float, lon: float, d: date_cls, radius_deg: float, step_deg: float
) -> dict:
    # Resolve the center's sunset and score the whole grid at that one instant,
    # so the map is a coherent snapshot "at the center's sunset".
    sunset = _resolve_sunset(lat, lon, d)
    t_score = sunset - SCORE_OFFSET

    lats: list[float] = []
    v = -radius_deg
    while v <= radius_deg + 1e-9:
        lats.append(round(lat + v, 4))
        v += step_deg
    lons: list[float] = []
    v = -radius_deg
    while v <= radius_deg + 1e-9:
        lons.append(round(lon + v, 4))
        v += step_deg

    coords = [(la, lo) for la in lats for lo in lons]
    if len(coords) > 400:
        raise HTTPException(status_code=400, detail="grid too large; increase step_deg")

    snaps = _source.fetch_many(coords, t_score)
    cells = []
    for (la, lo), snap in zip(coords, snaps):
        f = _predictor.score_snapshot(snap, la, lo, t_score)
        cells.append({"lat": la, "lon": lo, "probability": round(f.probability, 4)})

    return {
        "center": {"lat": lat, "lon": lon},
        "date": d.isoformat(),
        "sunset_utc": sunset.isoformat(),
        "radius_deg": radius_deg,
        "step_deg": step_deg,
        "cells": cells,
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/forecast")
def api_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    date: str | None = Query(None),
) -> dict:
    d = _parse_date(date)
    try:
        return _point_forecast(lat, lon, d)
    except HTTPException:
        raise
    except Exception as exc:  # upstream/data failure
        raise HTTPException(status_code=502, detail=f"forecast failed: {exc}")


@app.get("/api/forecast/grid")
def api_forecast_grid(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    date: str | None = Query(None),
    radius_deg: float = Query(2.0, gt=0, le=6),
    step_deg: float = Query(0.5, gt=0, le=2),
) -> dict:
    d = _parse_date(date)
    try:
        return _grid_forecast(lat, lon, d, radius_deg, step_deg)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"grid forecast failed: {exc}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
