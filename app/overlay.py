"""Precomputed national fire-cloud overlay, clipped to country borders.

The field is a fixed function of (lat, lon, date) on a FIXED geographic grid —
independent of the map viewport — so zooming/panning never changes it and never
triggers recomputation (the viewport-grid approach did both, which was a bug).

One overlay is built per (date, refresh-slot), rendered as a transparent PNG
clipped to the country outline (so the edge is a coastline/border, not a
rectangle), and cached in memory + on disk. The frontend loads this single
static image over the country bbox.
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
from datetime import date as date_cls, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from predictor.gfs import GFSSource
from predictor.national_field import build_national_field

CACHE_DIR = Path("research/data/cache/overlays")
OVERLAY_FLOOR = 0.06
# Increment whenever scoring inputs, rules, or rendering semantics change.
# Keeping it in the key prevents a new deployment from serving an old image
# produced by different forecast logic during the same refresh slot.
CACHE_SCHEMA_VERSION = "v3"  # v3: SunsetWx-style turbo quality colormap (#40)

# China domain (a small margin around the border bounds).
CN_BBOX = (17.0, 73.0, 54.0, 136.0)   # south, west, north, east
# Open-Meteo is a point API, so a dense national field can exhaust its fair-use
# budget and starve interactive point lookups. This deliberately coarse 4°
# field is a national trend overview (~190 samples); clicks still query exact
# coordinates. A true dense national field needs a gridded GFS/ICON source.
CN_STEP = 4.0                          # grid spacing in degrees (fixed grid)

# SunsetWx-style quality scale: a "better sunset is denoted by warmer colors",
# i.e. the perceptual turbo ramp deep-blue (low) → cyan → green → yellow →
# orange → red (high). Masked no-data cells stay transparent over the basemap.
_QUALITY_CMAP = matplotlib.colormaps["turbo"].copy()
_QUALITY_CMAP.set_bad(alpha=0.0)

# The national overview now reads one GFS 0.25° grid and scores it vectorized
# (#19), instead of ~190 per-point Open-Meteo requests.
_GFS = GFSSource()


# --------------------------------------------------------------------------- #
# Country geometry → matplotlib clip path
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=4)
def _country_geometry(name: str = "China"):
    import cartopy.io.shapereader as shpreader

    shp = shpreader.natural_earth(resolution="110m", category="cultural",
                                  name="admin_0_countries")
    for rec in shpreader.Reader(shp).records():
        a = rec.attributes
        if a.get("NAME") == name or a.get("ADMIN") == name:
            return rec.geometry
    raise ValueError(f"country not found: {name}")


def _geom_to_clip_path(geom) -> MplPath:
    """Compound matplotlib Path from a shapely (Multi)Polygon for clipping."""
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    verts: list[tuple[float, float]] = []
    codes: list[int] = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            xy = list(ring.coords)
            if len(xy) < 3:
                continue
            verts.extend(xy)
            codes.append(MplPath.MOVETO)
            codes.extend([MplPath.LINETO] * (len(xy) - 2))
            codes.append(MplPath.CLOSEPOLY)
    return MplPath(verts, codes)


# --------------------------------------------------------------------------- #
# Field smoothing / rendering (shared style with the rest of the app)
# --------------------------------------------------------------------------- #
def _smooth(arr: np.ndarray, passes: int = 1) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    for _ in range(passes):
        p = np.pad(a, 1, mode="edge")
        a = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4 * p[1:-1, 1:-1]) / 8.0
    return a


def _upsample(arr: np.ndarray, factor: int = 6) -> np.ndarray:
    ny, nx = arr.shape
    xi = np.linspace(0, nx - 1, nx * factor)
    yi = np.linspace(0, ny - 1, ny * factor)
    rows = np.vstack([np.interp(xi, np.arange(nx), arr[r]) for r in range(ny)])
    return np.vstack([np.interp(yi, np.arange(ny), rows[:, c]) for c in range(rows.shape[1])]).T


def _render_clipped_png(lats, lons, P, geom, *, upsample: int = 6) -> str | None:
    arr = _smooth(np.array(P, dtype=float), passes=1)
    if float(np.nanmax(arr)) < OVERLAY_FLOOR:
        return None

    fine = _upsample(arr, factor=upsample) if upsample > 1 else arr
    lon_fine = np.linspace(lons[0], lons[-1], fine.shape[1])
    lat_fine = np.linspace(lats[0], lats[-1], fine.shape[0])
    field = np.ma.masked_less(fine, OVERLAY_FLOOR)

    lon_span = max(lons[-1] - lons[0], 1e-6)
    lat_span = max(lats[-1] - lats[0], 1e-6)
    aspect = lon_span / lat_span
    long_in = 11.0
    W, H = (long_in, long_in / aspect) if aspect >= 1 else (long_in * aspect, long_in)

    # Object-oriented Figure (not pyplot): pyplot keeps global state that is not
    # thread-safe, and this renders inside a background build thread. Creating a
    # standalone Figure + Agg canvas avoids any global state entirely.
    fig = Figure(figsize=(W, H), dpi=200)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(lons[0], lons[-1])
    ax.set_ylim(lats[0], lats[-1])

    clip_patch = PathPatch(_geom_to_clip_path(geom), transform=ax.transData,
                           facecolor="none", edgecolor="none")
    ax.add_patch(clip_patch)

    levels = np.linspace(0.0, 1.0, 25)
    cf = ax.contourf(lon_fine, lat_fine, field, levels=levels, cmap=_QUALITY_CMAP,
                     vmin=0.0, vmax=1.0, extend="max", antialiased=True)
    # matplotlib ≥3.8: the ContourSet is itself a clippable artist. No contour
    # lines — SunsetWx's quality field is a smooth, line-free gradient.
    cf.set_clip_path(clip_patch)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- #
# Refresh-slot scheduling
# --------------------------------------------------------------------------- #
def _refresh_slot(now_utc: datetime) -> datetime:
    """Quantize the national overview to three-hour forecast cycles."""
    hour = (now_utc.hour // 3) * 3
    return now_utc.replace(hour=hour, minute=0, second=0, microsecond=0)


def _next_refresh(now_utc: datetime, slot: datetime) -> datetime:
    return slot + timedelta(hours=3)


# --------------------------------------------------------------------------- #
# Build + cache
# --------------------------------------------------------------------------- #
_MEM_CACHE_MAX = 24
_RECENT_CACHE_GRACE = timedelta(hours=1)
_mem_cache: dict[str, dict] = {}
_build_errors: dict[str, tuple[str, float]] = {}
_building: set[str] = set()
_cache_lock = threading.Lock()
_build_semaphore = threading.Semaphore(1)


def _mem_put(key: str, meta: dict) -> None:
    with _cache_lock:
        _mem_cache[key] = meta
        while len(_mem_cache) > _MEM_CACHE_MAX:
            oldest = next(iter(_mem_cache))
            _mem_cache.pop(oldest, None)


def _disk_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


_CACHE_KEY_RE = re.compile(
    rf"cn-{re.escape(CACHE_SCHEMA_VERSION)}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{8}}T\d{{4}}"
)


def _cache_prefix(d: date_cls) -> str:
    return f"cn-{CACHE_SCHEMA_VERSION}-{d.isoformat()}-"


def cached_image_path(key: str) -> Path | None:
    """Return a materialized PNG cache path for a validated overlay key."""
    if _CACHE_KEY_RE.fullmatch(key) is None:
        return None
    path = CACHE_DIR / f"{key}.png"
    return path if path.exists() else None


def _public_meta(key: str, meta: dict) -> dict:
    """Replace an in-cache data URI with a small browser-friendly image URL."""
    out = {**meta}
    image = out.get("image")
    if isinstance(image, str) and image.startswith("data:image/png;base64,"):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        png = CACHE_DIR / f"{key}.png"
        if not png.exists():
            png.write_bytes(base64.b64decode(image.split(",", 1)[1]))
        out["image"] = f"/api/overlay/image/{key}.png"
    return out


def _load_disk(key: str) -> dict | None:
    disk = _disk_path(key)
    if not disk.exists():
        return None
    try:
        return json.loads(disk.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _latest_cached(d: date_cls) -> tuple[str, dict] | None:
    prefix = _cache_prefix(d)
    with _cache_lock:
        mem_keys = sorted((k for k in _mem_cache if k.startswith(prefix)), reverse=True)
        if mem_keys:
            key = mem_keys[0]
            return key, _mem_cache[key]

    if not CACHE_DIR.exists():
        return None
    disks = sorted(CACHE_DIR.glob(f"{prefix}*.json"), reverse=True)
    for disk in disks:
        meta = _load_disk(disk.stem)
        if meta is not None:
            _mem_put(disk.stem, meta)
            return disk.stem, meta
    return None


def _slot_from_key(key: str) -> datetime:
    stamp = key.rsplit("-", 1)[-1]
    return datetime.strptime(stamp, "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)


def _axis_values(start: float, end: float, step: float) -> list[float]:
    """Build an inclusive grid axis even when ``step`` does not divide its span."""
    values = [round(float(v), 4) for v in np.arange(start, end + 1e-9, step)]
    if not values or values[-1] < end:
        values.append(round(end, 4))
    return values


def _center_sunset_utc(d: date_cls) -> datetime:
    """Sunset (UTC) at the domain centre — the national overview's valid time."""
    from astral import Observer
    from astral.sun import sun

    south, west, north, east = CN_BBOX
    obs = Observer(latitude=(south + north) / 2.0, longitude=(west + east) / 2.0)
    return sun(obs, date=d, tzinfo=timezone.utc)["sunset"]


def _build(d: date_cls, source, predictor, geom) -> dict:
    # One GFS 0.25° read, scored vectorized over the whole region (#19). The
    # `source`/`predictor` parameters are kept for call-site/signature
    # compatibility; the overview no longer makes per-point Open-Meteo requests.
    valid_time = _center_sunset_utc(d)
    field = build_national_field(_GFS, CN_BBOX, valid_time)
    print(
        f"[overlay] national field {field.source_label}: {field.n_points} cells, "
        f"{field.runtime_s:.2f}s, peak {field.peak_mem_mb:.1f} MB",
        flush=True,
    )

    # The GFS grid is already ~25 km; a light 2× upsample is enough for a smooth
    # render (the old coarse 4° grid needed 6×).
    image = _render_clipped_png(field.lats, field.lons, field.probability, geom, upsample=2)
    return {
        "country": "China",
        "date": d.isoformat(),
        "bounds": [
            [float(field.lats[0]), float(field.lons[0])],
            [float(field.lats[-1]), float(field.lons[-1])],
        ],
        "image": image,
        "max_probability": round(float(np.nanmax(field.probability)), 4),
        "valid_utc": field.valid_time.isoformat(),
        "n_points": field.n_points,
    }


def _build_and_store(
    key: str,
    d: date_cls,
    source,
    predictor,
    delay_seconds: float = 0.0,
) -> None:
    try:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        with _build_semaphore:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            geom = _country_geometry("China")
            meta = _build(d, source, predictor, geom)
            disk = _disk_path(key)
            tmp = disk.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta))
            tmp.replace(disk)
            _mem_put(key, meta)
            with _cache_lock:
                _build_errors.pop(key, None)
    except Exception as exc:
        with _cache_lock:
            _build_errors[key] = (str(exc), time.monotonic() + 60.0)
    finally:
        with _cache_lock:
            _building.discard(key)


def _start_build(
    key: str,
    d: date_cls,
    source,
    predictor,
    *,
    delay_seconds: float = 0.0,
) -> bool:
    with _cache_lock:
        if key in _building:
            return False
        previous_error = _build_errors.get(key)
        if previous_error is not None and time.monotonic() < previous_error[1]:
            return False
        _building.add(key)
        _build_errors.pop(key, None)
    threading.Thread(
        target=_build_and_store,
        args=(key, d, source, predictor, delay_seconds),
        name=f"firecloud-overlay-{key}",
        daemon=True,
    ).start()
    return True


def get_overlay(d: date_cls, source, predictor, now_utc: datetime) -> dict:
    """Return an overlay immediately and refresh the current slot in background.

    An exact memory/disk hit is returned as ``ready``. On a slot miss we start a
    single background build and return the most recent cached image as ``stale``;
    the very first request returns ``building`` with no image instead of holding
    the HTTP request open for a country-wide Open-Meteo fetch.
    """
    slot = _refresh_slot(now_utc)
    key = f"{_cache_prefix(d)}{slot.strftime('%Y%m%dT%H%M')}"

    with _cache_lock:
        exact = _mem_cache.get(key)
    if exact is None:
        exact = _load_disk(key)
        if exact is not None:
            _mem_put(key, exact)

    if exact is not None:
        meta = exact
        meta_key = key
        generated = slot
        status = "ready"
        error = None
    else:
        latest = _latest_cached(d)
        latest_generated = _slot_from_key(latest[0]) if latest is not None else None
        if (
            latest is not None
            and latest_generated is not None
            and timedelta(0) <= slot - latest_generated <= _RECENT_CACHE_GRACE
        ):
            # Cache keys from older app versions used finer refresh slots. A
            # recent image is already newer than the national overview needs,
            # so adopt it for this cycle instead of spending upstream quota.
            meta_key, meta = latest
            generated = latest_generated
            status = "ready"
            error = None
        elif latest is None:
            _start_build(key, d, source, predictor)
            south, west, north, east = CN_BBOX
            meta = {
                "country": "China",
                "date": d.isoformat(),
                "bounds": [[south, west], [north, east]],
                "image": None,
                "max_probability": None,
            }
            meta_key = key
            generated = None
            with _cache_lock:
                error_info = _build_errors.get(key)
                is_building = key in _building
            error = error_info[0] if error_info is not None else None
            status = "building" if is_building or error is None else "error"
        else:
            # Give interactive point requests a short head start before the
            # coarse batch refresh consumes upstream capacity.
            _start_build(
                key,
                d,
                source,
                predictor,
                delay_seconds=5.0,
            )
            latest_key, meta = latest
            meta_key = latest_key
            generated = _slot_from_key(latest_key)
            with _cache_lock:
                error_info = _build_errors.get(key)
            error = error_info[0] if error_info is not None else None
            status = "stale"

    return {
        **_public_meta(meta_key, meta),
        "status": status,
        "error": error,
        "retry_after_seconds": 60 if error is not None else 4,
        "generated_utc": generated.isoformat() if generated is not None else None,
        "next_refresh_utc": _next_refresh(now_utc, slot).isoformat(),
    }
