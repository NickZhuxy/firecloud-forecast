"""FastAPI backend for the firecloud-forecast web app.

Endpoints:

    GET /api/overlay/cn?date     precomputed national fire-cloud overlay image
                                 (fixed geographic grid, clipped to China's
                                 border, cached per refresh slot)
    GET /api/forecast?lat&lon&date   single-point detail for the click panel

The overlay is a fixed function of (lat, lon, date) — independent of the map
viewport — so zoom/pan never changes it or triggers recomputation. The point
endpoint backs the on-click detail panel. Both use the gate × modifier
predictor (predictor.standard_predictor) over Open-Meteo data, evaluated ~10
minutes before local sunset.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date as date_cls, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from astral import Observer
from astral.sun import azimuth, sun

import app.overlay as overlay_mod
from app.timing import SCORE_OFFSET, evening_instant
from predictor.clouds import diagnose_clouds
from predictor.features import derive
from predictor.fetch import OpenMeteoSource
from predictor.geometry import compute_geometry
from predictor.gfs import GFSSource
from predictor.normalize import normalize
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

# GFS pressure-level source for the single-point DETAILED forecast only. It is
# slow (GRIB download/parse) so the national overview grid deliberately does not
# use it; the per-instance dataset cache makes repeat same-cycle points cheap.
_gfs_source = GFSSource()


def _diagnose_cloud_layers(lat: float, lon: float, t_score: datetime):
    """Best-effort diagnosed cloud layers for the detail panel (#30).

    Returns a CloudLayer list, or None if GFS is unavailable — in which case the
    forecast degrades gracefully to the source-reported / fixed-estimate base.
    """
    try:
        profile = _gfs_source.fetch_profile(lat, lon, t_score)
        return diagnose_clouds(normalize(profile))
    except Exception:
        return None

# Small LRU for point lookups (the overlay has its own slot cache in overlay.py).
_POINT_CACHE_MAX = 512
_point_cache: "OrderedDict[tuple, dict]" = OrderedDict()


def _point_cache_get(key: tuple):
    if key in _point_cache:
        _point_cache.move_to_end(key)
        return _point_cache[key]
    return None


def _point_cache_put(key: tuple, value: dict) -> None:
    _point_cache[key] = value
    _point_cache.move_to_end(key)
    while len(_point_cache) > _POINT_CACHE_MAX:
        _point_cache.popitem(last=False)


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


def _astral_sunset(lat: float, lon: float, d: date_cls) -> datetime:
    """Exact sunset for the requested China-calendar date, returned in UTC."""
    observer = Observer(latitude=lat, longitude=lon)
    local_sunset = sun(observer, date=d, tzinfo=CHINA_TZ)["sunset"]
    return local_sunset.astimezone(timezone.utc)


def _point_forecast(lat: float, lon: float, d: date_cls) -> dict:
    evening = evening_instant(lon, d)
    try:
        sunset = _astral_sunset(lat, lon, d)
    except ValueError:
        # Polar day/night or an unsupported out-of-domain location: retain the
        # source-based path so the endpoint fails gracefully rather than during
        # the local astronomy pre-computation.
        sunset = None
    t_score = (sunset or evening) - SCORE_OFFSET

    observer = Observer(latitude=lat, longitude=lon)
    used_spatial_profile = False
    if sunset is not None and hasattr(_source, "fetch_sunward_profile"):
        sunset_azimuth = azimuth(observer, sunset)
        try:
            snap = _source.fetch_sunward_profile(
                lat, lon, t_score, sunset_azimuth
            )
            used_spatial_profile = True
        except Exception:
            # A detailed transect is an enhancement. If its weather request is
            # unavailable, retain the established local-only forecast.
            snap = _source.fetch_for_sunset(lat, lon, evening, SCORE_OFFSET)
    else:
        snap = _source.fetch_for_sunset(lat, lon, evening, SCORE_OFFSET)

    if not used_spatial_profile and snap.sunset_time is not None:
        sunset = snap.sunset_time
    sunset = sunset or evening
    snap.sunset_time = sunset
    t_score = sunset - SCORE_OFFSET

    # Single-point detail upgrades the canvas base to diagnosed cloud geometry
    # when GFS is reachable; the national grid path never calls this (#30).
    cloud_layers = _diagnose_cloud_layers(lat, lon, t_score)
    feats = derive(snap, lat, lon, t_score, cloud_layers=cloud_layers)
    forecast = _predictor.score_snapshot(snap, lat, lon, t_score, cloud_layers=cloud_layers)
    path_aod = (
        feats.sunward_aod_mean
        if feats.sunward_aod_mean is not None
        else feats.aerosol_optical_depth
    )
    # Geometry uses column AOD when available. Visibility is deliberately not
    # substituted here: the manual warns that fog/humidity can lower surface
    # visibility without representing aerosol extinction through the full path.
    geo = compute_geometry(
        feats.cloud_base_m,
        None,
        lat,
        aerosol_optical_depth=path_aod,
    )

    return {
        "lat": lat,
        "lon": lon,
        "date": d.isoformat(),
        "sunset_utc": sunset.isoformat(),
        "scored_utc": t_score.isoformat(),
        "probability": round(forecast.probability, 4),
        "gate_score": (
            round(forecast.gate_score, 4)
            if forecast.gate_score is not None
            else None
        ),
        "modifier_score": (
            round(forecast.modifier_score, 4)
            if forecast.modifier_score is not None
            else None
        ),
        "components": {k: round(v, 4) for k, v in forecast.components.items()},
        "explanation": forecast.explanation,
        "geometry": {
            "cloud_base_m": geo.cloud_base_m,
            "equivalent_cloud_base_m": (
                round(geo.equivalent_cloud_base_m)
                if geo.equivalent_cloud_base_m is not None
                else None
            ),
            "max_reach_km": (
                round(geo.max_reach_km, 1) if geo.max_reach_km is not None else None
            ),
            "duration_min": (
                round(geo.duration_min, 1) if geo.duration_min is not None else None
            ),
            # Provenance + the retained three-tier estimate so a consumer can
            # compare the diagnosed base against the old fixed height (#13).
            "cloud_base_source": feats.cloud_base_source,
            "cloud_base_fixed_m": feats.cloud_base_fixed_m,
            "cloud_base_confidence": feats.cloud_base_confidence,
        },
        "spatial": {
            "sun_azimuth_deg": (
                round(feats.sun_azimuth_deg, 1)
                if feats.sun_azimuth_deg is not None
                else None
            ),
            "cloud_boundary_km": (
                round(feats.sunward_cloud_boundary_km, 1)
                if feats.sunward_cloud_boundary_km is not None
                else None
            ),
            "profile_max_km": feats.sunward_profile_max_km,
            "boundary_gradient_pct_per_km": (
                round(feats.sunward_boundary_gradient_pct_per_km, 3)
                if feats.sunward_boundary_gradient_pct_per_km is not None
                else None
            ),
            "boundary_motion_m_s": (
                round(feats.boundary_motion_m_s, 1)
                if feats.boundary_motion_m_s is not None
                else None
            ),
            "obstruction_pct": (
                round(feats.sunward_obstruction_pct, 1)
                if feats.sunward_obstruction_pct is not None
                else None
            ),
            "aod_mean": (
                round(feats.sunward_aod_mean, 3)
                if feats.sunward_aod_mean is not None
                else None
            ),
        },
        # Diagnosed vertical structure (#31): graded canvas obstruction by lower
        # decks plus the per-layer breakdown. Null when GFS diagnosis is absent.
        "diagnosed": {
            "obstruction_pct": (
                round(feats.diagnosed_obstruction_pct, 1)
                if feats.diagnosed_obstruction_pct is not None
                else None
            ),
            "layers": [
                {
                    "base_m": round(c.base_m),
                    "top_m": round(c.top_m),
                    "phase_hint": c.phase_hint,
                    "confidence": c.confidence,
                    "duration_min": round(c.duration_min, 1),
                    "obstruction_fraction": round(c.obstruction_fraction, 3),
                    "is_canvas": c.is_canvas,
                }
                for c in (feats.layer_contributions or [])
            ],
        },
        "inputs": {
            "cloud_low_pct": snap.cloud_low_pct,
            "cloud_mid_pct": snap.cloud_mid_pct,
            "cloud_high_pct": snap.cloud_high_pct,
            "humidity_pct": snap.humidity_pct,
            "visibility_m": snap.visibility_m,
            "aerosol_optical_depth": snap.aerosol_optical_depth,
            "canvas_layer": feats.canvas_layer,
            "canvas_cloud_pct": feats.canvas_cloud_pct,
            "source": snap.source_label,
        },
    }


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


@app.get("/api/forecast")
def api_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    date: str | None = Query(None),
) -> dict:
    d = _parse_date(date)
    now_utc = datetime.now(timezone.utc)
    cache_slot = now_utc.replace(
        minute=(now_utc.minute // 15) * 15,
        second=0,
        microsecond=0,
    )
    # Keep cache coordinates aligned with the four decimal places accepted by
    # the frontend; coarser rounding can return another click's coordinates and
    # weather snapshot in the response body.
    key = (round(lat, 4), round(lon, 4), d.isoformat(), cache_slot)
    cached = _point_cache_get(key)
    if cached is not None:
        return cached
    try:
        result = _point_forecast(lat, lon, d)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"forecast failed: {exc}")
    _point_cache_put(key, result)
    return result


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
