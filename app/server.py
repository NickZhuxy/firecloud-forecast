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

import base64
import io
from datetime import date as date_cls, datetime, time as time_cls, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless render, before pyplot import
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

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
OVERLAY_FLOOR = 0.06  # probabilities below this render transparent

# Sunset-glow palette: transparent at the low end, deepening through lilac and
# pink to magenta — mirrors the reference "vividness index" maps. Alpha ramps in
# so the field reads as colour painted onto a light basemap only where clouds matter.
_SUNSET_CMAP = LinearSegmentedColormap.from_list(
    "sunset_pink",
    [
        (0.00, (1.00, 1.00, 1.00, 0.00)),
        (0.18, (0.92, 0.89, 0.96, 0.55)),
        (0.38, (0.84, 0.72, 0.88, 0.70)),
        (0.58, (0.90, 0.56, 0.78, 0.80)),
        (0.78, (0.89, 0.35, 0.65, 0.88)),
        (1.00, (0.74, 0.16, 0.48, 0.94)),
    ],
)

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


def _grid_field(
    lat: float, lon: float, d: date_cls, radius_deg: float, step_deg: float
):
    """Score a regular grid around (lat, lon) at the center's sunset.

    Returns (lats, lons, P) where P[i][j] is the probability at (lats[i],
    lons[j]), plus the sunset instant. One Open-Meteo batch call for the grid.
    """
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
    if len(coords) > 500:
        raise HTTPException(status_code=400, detail="grid too large; increase step_deg")

    snaps = _source.fetch_many(coords, t_score)
    P = [[0.0] * len(lons) for _ in range(len(lats))]
    for k, ((la, lo), snap) in enumerate(zip(coords, snaps)):
        f = _predictor.score_snapshot(snap, la, lo, t_score)
        P[k // len(lons)][k % len(lons)] = round(f.probability, 4)
    return lats, lons, P, sunset


def _grid_forecast(
    lat: float, lon: float, d: date_cls, radius_deg: float, step_deg: float
) -> dict:
    lats, lons, P, sunset = _grid_field(lat, lon, d, radius_deg, step_deg)
    cells = [
        {"lat": lats[i], "lon": lons[j], "probability": P[i][j]}
        for i in range(len(lats))
        for j in range(len(lons))
    ]
    return {
        "center": {"lat": lat, "lon": lon},
        "date": d.isoformat(),
        "sunset_utc": sunset.isoformat(),
        "radius_deg": radius_deg,
        "step_deg": step_deg,
        "cells": cells,
    }


def _smooth(arr: np.ndarray, passes: int = 2) -> np.ndarray:
    """Light 5-point smoothing (edge-padded), no SciPy dependency.

    Rounds off the contours so the filled field reads as a smooth cloud band
    rather than a faceted grid.
    """
    a = np.asarray(arr, dtype=float)
    for _ in range(passes):
        p = np.pad(a, 1, mode="edge")
        a = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4 * p[1:-1, 1:-1]) / 8.0
    return a


def _render_overlay_png(lats: list[float], lons: list[float], P: list[list[float]]) -> str | None:
    """Render the probability field as a transparent filled-contour PNG.

    Returns a base64 data URI, or None when the field is everywhere below the
    floor (nothing to paint). The image maps 1:1 onto the lat/lon bounding box
    for Leaflet's imageOverlay.
    """
    arr = _smooth(np.array(P, dtype=float), passes=2)
    if float(np.nanmax(arr)) < OVERLAY_FLOOR:
        return None
    field = np.ma.masked_less(arr, OVERLAY_FLOOR)

    nlat, nlon = field.shape
    fig = plt.figure(figsize=(nlon / 24, nlat / 24), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(lons[0], lons[-1])
    ax.set_ylim(lats[0], lats[-1])

    levels = np.linspace(0.0, 1.0, 21)
    ax.contourf(lons, lats, field, levels=levels, cmap=_SUNSET_CMAP, extend="max", antialiased=True)
    # Subtle contour lines for a weather-map feel.
    ax.contour(lons, lats, field, levels=np.linspace(0.2, 1.0, 5),
               colors="#7a3a64", linewidths=0.35, alpha=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _overlay(lat: float, lon: float, d: date_cls, radius_deg: float, step_deg: float) -> dict:
    lats, lons, P, sunset = _grid_field(lat, lon, d, radius_deg, step_deg)
    image = _render_overlay_png(lats, lons, P)
    return {
        "center": {"lat": lat, "lon": lon},
        "date": d.isoformat(),
        "sunset_utc": sunset.isoformat(),
        "bounds": [[lats[0], lons[0]], [lats[-1], lons[-1]]],  # [[S,W],[N,E]]
        "image": image,
        "max_probability": round(float(np.nanmax(np.array(P))), 4),
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


@app.get("/api/forecast/overlay")
def api_forecast_overlay(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    date: str | None = Query(None),
    radius_deg: float = Query(3.0, gt=0, le=6),
    step_deg: float = Query(0.375, gt=0, le=2),
) -> dict:
    d = _parse_date(date)
    try:
        return _overlay(lat, lon, d, radius_deg, step_deg)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"overlay failed: {exc}")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
