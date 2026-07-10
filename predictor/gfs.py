"""GFS 0.25° pressure-level data adapter.

Produces standardized vertical data (``AtmosphericProfile`` for a point,
``AtmosphericCube`` for a bbox region) from the free GFS 0.25° GRIB, for use by
point soundings, the 800 km sunward cross-section, and the national grid.

Key constraint: GFS GRIB byte-range subsetting is per message = per
(variable × level), and each message is the *global* 0.25° field. Download cost
is reduced only by selecting fewer variables/levels, never by bbox; a region is
cropped in memory after parsing. A global cube over 20 levels × 8 variables is
~6.6 GB, so ``fetch_cube`` always crops to the requested bbox.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from dataclasses import dataclass

logger = logging.getLogger(__name__)

from predictor.profiles import (
    PROFILE_VARS,
    AtmosphericCube,
    _nearest_index,
    _nearest_lon_index,
)


@dataclass
class EtageCloudCover:
    """GFS three-tier (étage) cloud cover at a point, percent (0–100)."""

    low_pct: float
    mid_pct: float
    high_pct: float

    def for_tier(self, tier: str) -> float:
        return {"low": self.low_pct, "mid": self.mid_pct, "high": self.high_pct}[tier]


@dataclass
class SurfaceGrid:
    """GFS surface fields over a bbox: one read for the whole national grid (#19)."""

    lats: np.ndarray  # 1-D (ny)
    lons: np.ndarray  # 1-D (nx)
    cloud_low_pct: np.ndarray   # (ny, nx); remaining fields share this shape
    cloud_mid_pct: np.ndarray
    cloud_high_pct: np.ndarray
    humidity_pct: np.ndarray
    visibility_m: np.ndarray
    run_time: datetime
    valid_time: datetime
    source_label: str
    missing: list[str]
    # GRIB subset bytes computed from Herbie's inventory byte ranges.  This is
    # the logical download size; a disk-cache hit can use 0 network bytes while
    # consuming the same payload.
    download_bytes: int | None = None

    @property
    def n_points(self) -> int:
        return int(self.lats.size * self.lons.size)

    @property
    def decoded_bytes(self) -> int:
        arrays = (
            self.lats,
            self.lons,
            self.cloud_low_pct,
            self.cloud_mid_pct,
            self.cloud_high_pct,
            self.humidity_pct,
            self.visibility_m,
        )
        return sum(np.asarray(array).nbytes for array in arrays)


_DOWNLOAD_BYTES_ATTR = "firecloud_download_bytes"


def _subset_byte_ranges(herbie, search: str) -> list[tuple[int, int]] | None:
    """Contiguous source-byte ranges selected by a Herbie search."""
    try:
        inventory = herbie.inventory(search).sort_values("grib_message")
        messages = np.asarray(inventory["grib_message"], dtype=int)
        starts = np.asarray(inventory["start_byte"], dtype=float)
        ends = np.asarray(inventory["end_byte"], dtype=float)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if messages.size == 0 or not (
        np.isfinite(starts).all() and np.isfinite(ends).all()
    ):
        return None

    # Herbie combines consecutive GRIB messages into one HTTP Range request.
    # Reproduce that grouping so the metric matches the downloaded payload, not
    # merely the sum of selected message bodies.
    group_starts = np.r_[0, np.where(np.diff(messages) != 1)[0] + 1]
    group_ends = np.r_[group_starts[1:], messages.size]
    return [
        (int(starts[start]), int(ends[stop - 1]))
        for start, stop in zip(group_starts, group_ends)
    ]


def _subset_payload_bytes(herbie, search: str) -> int | None:
    """Logical GRIB bytes Herbie will request for a regex subset."""
    ranges = _subset_byte_ranges(herbie, search)
    if not ranges:
        return None
    return sum(end - start + 1 for start, end in ranges)


# Announce transfers at least this large at INFO. A default exact-level pressure
# subset is ~130 MB (legacy supersets are ~210 MB), while one surface hour is
# ~0.6 MB and stays quiet.
_PROGRESS_ANNOUNCE_BYTES = 50_000_000

# Slow pressure downloads need visible liveness and a generous per-read timeout.
# Requests' tuple is (connect timeout, socket-read timeout), not total duration.
_PROGRESS_HEARTBEAT_S = 15.0
_RANGE_CONNECT_TIMEOUT_S = 10.0
_RANGE_READ_TIMEOUT_S = 90.0
_RANGE_CHUNK_BYTES = 1024 * 1024


def _progress_line(
    what: str, fxx: int, size: int, expected: int, rate_bytes_s: float, stalled: bool
) -> str:
    """Format one heartbeat for an in-flight subset download."""
    done_mb, total_mb = size / 1e6, expected / 1e6
    if stalled:
        return (
            f"GFS {what} subset f{fxx:02d}: {done_mb:.0f}/{total_mb:.0f} MB — "
            f"no progress in the last {_PROGRESS_HEARTBEAT_S:.0f} s "
            "(server stall or slow link; transient drops retry automatically)"
        )
    eta = ""
    if rate_bytes_s > 0:
        eta = f", ~{(expected - size) / rate_bytes_s:.0f} s left"
    return (
        f"GFS {what} subset f{fxx:02d}: {done_mb:.0f}/{total_mb:.0f} MB "
        f"({rate_bytes_s / 1e6:.1f} MB/s{eta})"
    )


def _download_with_heartbeat(download, local: Path, what: str, fxx: int, expected: int):
    """Run a blocking download while a daemon thread reports file growth."""
    stop = threading.Event()

    def _size() -> int:
        try:
            return local.stat().st_size
        except OSError:
            return 0

    def _beat() -> None:
        started = time.perf_counter()
        initial = _size()
        previous = initial
        while not stop.wait(_PROGRESS_HEARTBEAT_S):
            size = _size()
            elapsed = time.perf_counter() - started
            rate = (size - initial) / elapsed if elapsed > 0 else 0.0
            logger.info(
                "%s", _progress_line(what, fxx, size, expected, rate, size <= previous)
            )
            previous = size

    beater = threading.Thread(
        target=_beat, name=f"gfs-heartbeat-{what}-f{fxx:02d}", daemon=True
    )
    beater.start()
    try:
        return download()
    finally:
        stop.set()
        beater.join(timeout=1.0)


def _resumable_source(herbie) -> str | Path | None:
    """Return a byte-range-capable source, or None for test/stub handles."""
    source = getattr(herbie, "grib", None)
    if isinstance(source, Path):
        return source if source.exists() else None
    if isinstance(source, str):
        if source.startswith(("http://", "https://")):
            return source
        path = Path(source)
        return path if path.exists() else None
    return None


def _download_resumable_subset(herbie, search: str) -> int:
    """Download selected GRIB ranges, resuming from any retained prefix.

    Herbie writes each selected range group in order, so its interrupted subset
    is a prefix of the final concatenated file. Mapping that prefix back onto
    source ranges lets a retry continue inside the interrupted group instead of
    deleting tens or hundreds of megabytes and starting over.
    """
    ranges = _subset_byte_ranges(herbie, search)
    source = _resumable_source(herbie)
    if not ranges or source is None:
        raise ValueError("subset source does not support resumable byte ranges")

    local = Path(herbie.get_localFilePath(search))
    local.parent.mkdir(parents=True, exist_ok=True)
    expected = sum(end - start + 1 for start, end in ranges)
    actual = local.stat().st_size if local.exists() else 0
    if actual > expected:
        local.unlink()
        actual = 0
    if actual == expected:
        return 0

    offset = actual
    transferred = 0
    for start, end in ranges:
        group_size = end - start + 1
        if offset >= group_size:
            offset -= group_size
            continue

        range_start = start + offset
        remaining = end - range_start + 1
        mode = "ab" if local.exists() else "wb"
        if isinstance(source, Path):
            with source.open("rb") as src, local.open(mode) as dst:
                src.seek(range_start)
                while remaining:
                    chunk = src.read(min(_RANGE_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise GFSUnavailable(
                            f"GFS local subset truncated at source byte {src.tell()}"
                        )
                    dst.write(chunk)
                    transferred += len(chunk)
                    remaining -= len(chunk)
        else:
            headers = {"Range": f"bytes={range_start}-{end}"}
            try:
                with requests.get(
                    source,
                    headers=headers,
                    stream=True,
                    timeout=(_RANGE_CONNECT_TIMEOUT_S, _RANGE_READ_TIMEOUT_S),
                ) as response:
                    response.raise_for_status()
                    if response.status_code != 206:
                        raise RuntimeError(
                            f"range server returned HTTP {response.status_code}"
                        )
                    with local.open(mode) as dst:
                        for chunk in response.iter_content(chunk_size=_RANGE_CHUNK_BYTES):
                            if not chunk:
                                continue
                            if len(chunk) > remaining:
                                chunk = chunk[:remaining]
                            dst.write(chunk)
                            transferred += len(chunk)
                            remaining -= len(chunk)
                            if remaining == 0:
                                break
            except requests.RequestException as exc:
                raise RuntimeError(f"Processing failed: {exc}") from exc
            if remaining:
                raise GFSUnavailable(
                    f"GFS subset range truncated ({remaining} bytes still missing)"
                )
        offset = 0

    return transferred


def _dataset_download_bytes(ds: xr.Dataset) -> int | None:
    """Logical download bytes from inventory metadata or retained local files."""
    measured = ds.attrs.get(_DOWNLOAD_BYTES_ATTR)
    if isinstance(measured, (int, np.integer)) and measured >= 0:
        return int(measured)

    sources: set[Path] = set()
    for variable in ds.data_vars.values():
        source = variable.encoding.get("source")
        if isinstance(source, (str, Path)):
            sources.add(Path(source))
    sizes: list[int] = []
    for source in sources:
        try:
            sizes.append(source.stat().st_size)
        except OSError:
            continue
    return sum(sizes) if sizes else None


# GFS cfgrib shortname -> our profile field name.
GFS_VAR_MAP: dict[str, str] = {
    "t": "temperature_k",
    "r": "relative_humidity_pct",
    "q": "specific_humidity_kg_kg",
    "gh": "geopotential_height_m",
    "u": "u_wind_m_s",
    "v": "v_wind_m_s",
    "w": "vertical_velocity_pa_s",
    "clmr": "cloud_water_kg_kg",
    "clwmr": "cloud_water_kg_kg",
    "icmr": "cloud_ice_kg_kg",
}

CYCLE_HOURS = 6   # GFS runs at 00/06/12/18Z
LAG_HOURS = 4     # pgrb2.0p25 is typically published ~3.5–4 h after the cycle
# Herbie's default GFS source list ends with NCAR RDA/UCAR. Its GRIB HEAD
# check is not exception-safe, so an expired UCAR TLS certificate can abort a
# current forecast even when earlier NOAA/open-data mirrors are simply missing.
# Firecloud only needs recent GFS runs; these mirrors cover that path.
HERBIE_GFS_PRIORITY = ["aws", "nomads", "google", "azure"]


class GFSUnavailable(RuntimeError):
    """Raised when no usable GFS cycle could be loaded after fallbacks."""


_TRANSIENT_NETWORK_MARKERS = (
    "timed out", "timeout", "connection", "reset by peer",
    "temporarily unavailable", "throttl", " 500", " 502", " 503", " 504",
    # A truncated subset download (verified against the idx byte count) is a
    # dropped transfer: the cycle exists, so re-downloading is the right move.
    "truncated",
)


def _is_transient_network_error(exc: Exception) -> bool:
    """Heuristic: does this look like a transient S3/network hiccup worth a retry?

    A read timeout or dropped connection to AWS is transient — the cycle exists,
    the socket just stalled — so retrying the single hour is right. A genuinely
    unpublished cycle raises a different message and is NOT retried (it falls
    through to the caller's cycle fallback immediately).
    """
    return any(marker in str(exc).lower() for marker in _TRANSIENT_NETWORK_MARKERS)


def _is_empty_xarray_selection_error(exc: ValueError) -> bool:
    """cfgrib can surface absent sparse levels as an empty lazy index."""
    message = str(exc).lower()
    return "zero-size array" in message and "reduction operation" in message


_GRIB_CHATTER_SILENCED = False


def _silence_grib_chatter() -> None:
    """Suppress the two recurring third-party warnings of every GRIB fetch.

    Targeted by message so anything unexpected still surfaces:
    - herbie warns "Will not remove GRIB file…" whenever it parses an
      already-cached subset — which is our normal path, not a problem;
    - cfgrib's internal ``xr.merge`` triggers xarray's compat-default
      FutureWarning once per opened dataset (our own merges pass ``compat``
      explicitly and never warn).
    Herbie's prints ("✅ Found…", per-message download rows) are silenced
    separately via ``Herbie(verbose=False)`` in ``_herbie``.
    """
    import warnings

    warnings.filterwarnings(
        "ignore", message=r"Will not remove GRIB file"
    )
    warnings.filterwarnings(
        "ignore",
        message=r"In a future version of xarray the default value for compat",
        category=FutureWarning,
    )


class GFSSource:
    """Fetch GFS 0.25° pressure-level profiles and region cubes."""

    DEFAULT_CACHE_DIR = Path("research/data/cache/gfs")
    DEFAULT_LEVELS_HPA: tuple[float, ...] = (
        1000.0, 975.0, 950.0, 925.0, 900.0, 850.0, 800.0, 750.0, 700.0, 650.0,
        600.0, 550.0, 500.0, 450.0, 400.0, 350.0, 300.0, 250.0, 200.0, 150.0,
    )
    # Half-width (degrees) of the bbox used to crop a single-point fetch.
    POINT_PAD_DEG = 0.5
    MAX_CYCLE_FALLBACK = 2
    # The national grid spans several sunset forecast hours; each is an
    # independent network read, so download cache-misses concurrently.
    MAX_SURFACE_WORKERS = 8
    # Pressure cubes are large; the national refine needs only a few
    # distinct forecast hours, so 4 parallel downloads is enough to overlap them
    # without a swarm of large range requests fighting for one slow link (#108).
    MAX_CUBE_WORKERS = 4
    # A transient S3 read timeout on one hour shouldn't fail the whole batch;
    # retry the individual download a few times before giving up to the cycle
    # fallback. (Genuinely-unpublished cycles fail fast — not retried.)
    SURFACE_DOWNLOAD_ATTEMPTS = 3
    SURFACE_RETRY_BACKOFF_S = 1.5
    # The surface subset (étage cover, 2 m RH, visibility). Shared by the parallel
    # prefetch (network) and the serial parse so both reference the same file.
    _SURFACE_SEARCH = r":(?:LCDC|MCDC|HCDC):|:RH:2 m above ground:|:VIS:surface:"
    _PRESSURE_VARS = r"(?:TMP|RH|SPFH|HGT|UGRD|VGRD|VVEL|CLMR|CLWMR|ICMR)"
    # Kept only to reuse complete caches produced before exact-level filtering.
    # Its unanchored ``\d+`` also matches decimal levels such as ``0.01 mb``.
    _LEGACY_PRESSURE_SEARCH = rf":{_PRESSURE_VARS}:\d+ mb:"

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        levels: tuple[float, ...] | None = None,
        as_of: datetime | None = None,
    ):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.levels = tuple(levels) if levels else self.DEFAULT_LEVELS_HPA
        # Freeze publication availability for one source/run. This prevents a
        # long invocation crossing a cycle boundary halfway through its batch.
        self.as_of = _as_utc(as_of or datetime.now(timezone.utc))
        # Install once per process, before any download threads exist
        # (warnings filters are global, mutating them from workers races).
        global _GRIB_CHATTER_SILENCED
        if not _GRIB_CHATTER_SILENCED:
            _silence_grib_chatter()
            _GRIB_CHATTER_SILENCED = True
        # Per-instance in-memory caches keyed by (run_dt, fxx), mirroring
        # HRRRSource: avoids re-parsing for repeated same-cycle queries.
        self._ds_cache: dict[tuple[datetime, int], xr.Dataset] = {}
        self._cover_cache: dict[tuple[datetime, int], xr.Dataset] = {}
        self._surface_cache: dict[tuple[datetime, int], xr.Dataset] = {}
        # Logical payload bytes actually transferred, keyed by subset kind
        # ("pressure"/"surface"/"cover"). Disk-cache hits do not count, so the
        # national refine metadata can report the true cube download cost.
        self.network_bytes: dict[str, int] = {}

    @property
    def _pressure_search(self) -> str:
        """Pressure variables at exactly the configured levels.

        The old ``\\d+ mb`` expression accidentally matched every integer and
        decimal pressure level in GFS, including ``0.01 mb``. The default 20
        levels are the only ones later retained by ``_cube_from_datasets``.
        """
        labels = dict.fromkeys(re.escape(f"{float(level):g}") for level in self.levels)
        return rf":{self._PRESSURE_VARS}:(?:{'|'.join(labels)}) mb:"

    def _select_pressure_search(self, herbie) -> str:
        """Prefer the lean search, but reuse a complete legacy superset cache."""
        exact = self._pressure_search
        for search in (exact, self._LEGACY_PRESSURE_SEARCH):
            expected = _subset_payload_bytes(herbie, search)
            if expected is None:
                continue
            local = Path(herbie.get_localFilePath(search))
            try:
                if local.stat().st_size == expected:
                    return search
            except OSError:
                pass
        return exact

    # ---- public API -----------------------------------------------------

    def fetch_profile(
        self, lat: float, lon: float, valid_time: datetime
    ) -> "AtmosphericProfile":
        bbox = (
            lat - self.POINT_PAD_DEG, lat + self.POINT_PAD_DEG,
            lon - self.POINT_PAD_DEG, lon + self.POINT_PAD_DEG,
        )
        return self.fetch_cube(bbox, valid_time).profile_at(lat, lon)

    def fetch_cube(
        self, bbox: tuple[float, float, float, float], valid_time: datetime
    ) -> AtmosphericCube:
        valid_utc = _as_utc(valid_time)
        run_dt, fxx = self._select_cycle(valid_utc)
        ds, run_used, fxx_used = self._load_with_fallback(run_dt, fxx)
        return self._cube_from_datasets(
            ds,
            bbox=bbox,
            levels=self.levels,
            run_time=run_used,
            valid_time=valid_utc,
            source_label=f"gfs@{run_used:%Y-%m-%dT%HZ}+f{fxx_used:02d}",
            retrieved_at=datetime.now(timezone.utc),
        )

    def fetch_cloud_cover(
        self, lat: float, lon: float, valid_time: datetime
    ) -> EtageCloudCover:
        """GFS three-tier cloud cover (LCDC/MCDC/HCDC) at a point.

        GFS reports its own étage cloud covers, so a canvas diagnosed from GFS
        can be scored against GFS coverage instead of a possibly-disagreeing
        Open-Meteo value (#35).
        """
        valid_utc = _as_utc(valid_time)
        run_dt, fxx = self._select_cycle(valid_utc)
        ds, _run, _fxx = self._load_with_fallback(run_dt, fxx, self._load_cover)
        return self._cover_from_dataset(ds, lat, lon)

    def fetch_surface_grid(
        self, bbox: tuple[float, float, float, float], valid_time: datetime
    ) -> SurfaceGrid:
        """GFS surface fields (cloud cover, 2 m RH, visibility) over a bbox (#19).

        One read + decode for the whole region — the national overview then
        scores every cell with numpy instead of a per-point HTTP request.
        """
        return self.fetch_surface_grids(bbox, (valid_time,))[0]

    def fetch_surface_grids(
        self,
        bbox: tuple[float, float, float, float],
        valid_times: Iterable[datetime],
    ) -> list[SurfaceGrid]:
        """Fetch several forecast hours from one common GFS model run.

        Choosing each hour independently can cross a 6-hour cycle boundary and
        create a false longitudinal seam.  The earliest selected candidate run
        covers every requested valid time; if any hour is unavailable, the whole
        batch falls back together so all cells retain the same model-cycle age.
        """
        valid_utc = tuple(_as_utc(time) for time in valid_times)
        if not valid_utc:
            return []
        candidate_runs = [self._select_cycle(time)[0] for time in valid_utc]
        common_run = min(candidate_runs)
        base_fxx = [
            max(0, round((time - common_run).total_seconds() / 3600.0))
            for time in valid_utc
        ]

        last_exc: Exception | None = None
        for step in range(self.MAX_CYCLE_FALLBACK + 1):
            run = common_run - timedelta(hours=CYCLE_HOURS * step)
            fxxs = [fxx + CYCLE_HOURS * step for fxx in base_fxx]
            try:
                datasets = self._load_surface_batch(run, fxxs)
                grids = [
                    self._surface_grid_from_dataset(
                        ds,
                        bbox=bbox,
                        run_time=run,
                        valid_time=time,
                        source_label=f"gfs@{run:%Y-%m-%dT%HZ}+f{fxx:02d}",
                    )
                    for ds, time, fxx in zip(datasets, valid_utc, fxxs)
                ]
            except Exception as exc:  # noqa: BLE001 — batch-fallback one cycle
                last_exc = exc
                continue
            return grids
        raise GFSUnavailable(
            f"no complete GFS surface batch near {common_run:%Y-%m-%dT%HZ} "
            f"after {self.MAX_CYCLE_FALLBACK} fallbacks"
        ) from last_exc

    # ---- cycle selection / loading -------------------------------------

    def _select_cycle(self, valid_time: datetime) -> tuple[datetime, int]:
        """Most recent published 6-hourly cycle and the nearest forecast hour."""
        valid_utc = _as_utc(valid_time)
        # Publication lag is relative to wall-clock availability, not the
        # forecast's future valid time. Without this cap, a tomorrow forecast
        # probes future 12Z/18Z cycles and can fail only after older hours have
        # already downloaded hundreds of megabytes.
        available = min(valid_utc, self.as_of) - timedelta(hours=LAG_HOURS)
        run = available.replace(minute=0, second=0, microsecond=0)
        run -= timedelta(hours=run.hour % CYCLE_HOURS)
        fxx = max(0, round((valid_utc - run).total_seconds() / 3600.0))
        return run, fxx

    def _load_with_fallback(
        self, run_dt: datetime, fxx: int, loader=None
    ) -> tuple[xr.Dataset, datetime, int]:
        loader = loader or self._load_dataset
        last_exc: Exception | None = None
        for step in range(self.MAX_CYCLE_FALLBACK + 1):
            run = run_dt - timedelta(hours=CYCLE_HOURS * step)
            # Stepping back a cycle keeps the same valid time, so the forecast
            # hour grows by one cycle length per step.
            f = fxx + CYCLE_HOURS * step
            try:
                return loader(run, f), run, f
            except Exception as exc:  # noqa: BLE001 — try the previous cycle
                last_exc = exc
        raise GFSUnavailable(
            f"no usable GFS cycle near {run_dt:%Y-%m-%dT%HZ} after "
            f"{self.MAX_CYCLE_FALLBACK} fallbacks"
        ) from last_exc

    def _load_dataset(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        key = (run_dt, fxx)
        cached = self._ds_cache.get(key)
        if cached is not None:
            return cached
        ds = self._retry_transient(
            lambda: self._download_dataset(run_dt, fxx), fxx, "pressure cube download"
        )
        self._ds_cache[key] = ds
        return ds

    def _prefetch_dataset(self, run_dt: datetime, fxx: int) -> None:
        """Download one pressure cube's GRIB subset to disk — network only, no parse."""
        H = self._herbie(run_dt, fxx, cache_namespace="pressure")
        search = self._select_pressure_search(H)
        self._verified_subset_download(
            H, search, fxx, "pressure", resumable=True
        )

    def prefetch_cubes(self, valid_times: Iterable[datetime]) -> None:
        """Warm the disk cache for several forecast hours in parallel (#108).

        The national refine decodes and scores one hour's cube at a time (bounded
        peak memory, #59). On a slow link the dominant cost is the *serial*
        download of each distinct hour's ~130 MB subset. Downloading them
        concurrently — but still parsing serially, since eccodes/cfgrib is not
        thread-safe — overlaps that wait without holding more than one decoded
        dataset. Only the on-disk subsets accumulate (cheap, reused across runs).

        Best-effort: a failed prefetch is logged and swallowed. The serial
        ``fetch_cube`` path (retries + cycle fallback) stays the source of truth,
        so the worst case is falling back to today's one-at-a-time behaviour.
        """
        pending: list[tuple[datetime, int]] = []
        seen: set[tuple[datetime, int]] = set()
        for valid_time in valid_times:
            run_dt, fxx = self._select_cycle(_as_utc(valid_time))
            key = (run_dt, fxx)
            if key in seen or key in self._ds_cache:
                continue  # duplicate hour, or already decoded → nothing to fetch
            seen.add(key)
            pending.append(key)

        if pending:
            workers = min(len(pending), self.MAX_CUBE_WORKERS)
            logger.info(
                "GFS pressure: preparing %d forecast hours "
                "(%d parallel, interrupted files resume)",
                len(pending), workers,
            )

        if len(pending) <= 1:
            for run_dt, fxx in pending:
                self._safe_prefetch_dataset(run_dt, fxx)
            return

        workers = min(len(pending), self.MAX_CUBE_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self._safe_prefetch_dataset, run_dt, fxx)
                for run_dt, fxx in pending
            ]
            for future in futures:
                future.result()  # _safe_prefetch_dataset never raises

    def _safe_prefetch_dataset(self, run_dt: datetime, fxx: int) -> bool:
        try:
            self._retry_transient(
                lambda: self._prefetch_dataset(run_dt, fxx),
                fxx,
                "pressure prefetch",
            )
            return True
        except Exception as exc:  # noqa: BLE001 — prefetch is a best-effort optimization
            logger.warning(
                "GFS pressure prefetch f%02d unavailable: %s "
                "— refinement will retry/fallback when needed",
                fxx, exc,
            )
            return False

    def release_cube(self, valid_time: datetime) -> int:
        """Drop decoded pressure datasets for one valid hour from memory.

        A decoded global dataset is ~300 MB resident; the national refine walks
        several sunset hours and would otherwise keep every one alive until the
        product finishes. Matching by ``run + fxx == valid`` also catches
        entries loaded through the cycle fallback. The on-disk GRIB cache is
        untouched — a later fetch re-parses without re-downloading.
        """
        valid_utc = _as_utc(valid_time)
        keys = [
            key for key in self._ds_cache
            if key[0] + timedelta(hours=key[1]) == valid_utc
        ]
        for key in keys:
            del self._ds_cache[key]
        return len(keys)

    def _load_cover(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        key = (run_dt, fxx)
        cached = self._cover_cache.get(key)
        if cached is not None:
            return cached
        ds = self._retry_transient(
            lambda: self._download_cover(run_dt, fxx), fxx, "cover download"
        )
        self._cover_cache[key] = ds
        return ds

    def _retry_transient(self, action, fxx: int, what: str):
        """Run a download ``action``, retrying transient network failures.

        Without this a single AWS read timeout among the many sunset hours fails
        the whole national batch and forces a wasteful cycle fallback. A genuine
        404 (unpublished cycle) is not transient and is re-raised immediately.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.SURFACE_DOWNLOAD_ATTEMPTS + 1):
            try:
                return action()
            except Exception as exc:  # noqa: BLE001 — retry only transient network errors
                last_exc = exc
                if attempt == self.SURFACE_DOWNLOAD_ATTEMPTS or not _is_transient_network_error(exc):
                    raise
                logger.warning(
                    "GFS %s f%02d: 网络中断,自动重试 (%d/%d)…",
                    what, fxx, attempt, self.SURFACE_DOWNLOAD_ATTEMPTS,
                )
                logger.debug("GFS %s f%02d transient detail: %r", what, fxx, exc)
                time.sleep(self.SURFACE_RETRY_BACKOFF_S * attempt)
        raise last_exc  # pragma: no cover - loop returns or raises above

    def _load_surface(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        key = (run_dt, fxx)
        cached = self._surface_cache.get(key)
        if cached is not None:
            return cached
        # Parse (eccodes/cfgrib). If the file was prefetched this is a local read;
        # otherwise _download_surface also fetches it. Retried for the latter case.
        ds = self._retry_transient(
            lambda: self._download_surface(run_dt, fxx), fxx, "surface parse"
        )
        self._surface_cache[key] = ds
        return ds

    def _load_surface_batch(self, run_dt: datetime, fxxs: list[int]) -> list[xr.Dataset]:
        """Load several forecast hours for one cycle: parallel download, serial parse.

        The national map spans several sunset forecast hours; downloading them
        serially is the dominant cost (and looks like a hang). The *network* reads
        are independent, so prefetch the uncached, de-duplicated hours to disk
        concurrently — but PARSE them serially, because eccodes/cfgrib is not
        assumed thread-safe. Any download error propagates so the caller's
        whole-batch cycle fallback still triggers.
        """
        pending = [
            f for f in dict.fromkeys(fxxs) if (run_dt, f) not in self._surface_cache
        ]
        if len(pending) > 1:
            logger.info(
                "GFS surface: downloading %d forecast hours for %s (parallel)…",
                len(pending), f"{run_dt:%Y-%m-%dT%HZ}",
            )
            workers = min(len(pending), self.MAX_SURFACE_WORKERS)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # Submit all, let the pool drain, THEN surface errors — deterministic
                # attempt set (no map early-exit race). Download only, no parse.
                futures = [
                    pool.submit(
                        self._retry_transient,
                        lambda f=f: self._prefetch_surface(run_dt, f),
                        f,
                        "surface download",
                    )
                    for f in pending
                ]
            for future in futures:
                future.result()   # re-raise the first failure → caller's cycle fallback
        # Parse serially; prefetched hours are now local files.
        return [self._load_surface(run_dt, f) for f in fxxs]

    def _prefetch_surface(self, run_dt: datetime, fxx: int) -> None:
        """Download one surface hour's GRIB subset to disk — network only, no parse."""
        H = self._herbie(run_dt, fxx, cache_namespace="surface")
        self._verified_subset_download(H, self._SURFACE_SEARCH, fxx, "surface")

    def _herbie(self, run_dt: datetime, fxx: int, *, cache_namespace: str):
        """Construct a Herbie handle for a GFS 0.25° cycle (network on .xarray)."""
        from herbie import Herbie

        save_dir = self.cache_dir / cache_namespace
        # Pre-create the dated subdir herbie writes into: its download() emits
        # an ungated "Created directory" print when the dir is missing.
        (save_dir / "gfs" / f"{run_dt:%Y%m%d}").mkdir(parents=True, exist_ok=True)
        return Herbie(
            run_dt.strftime("%Y-%m-%d %H:%M"),
            model="gfs",
            product="pgrb2.0p25",
            fxx=fxx,
            save_dir=save_dir,
            priority=HERBIE_GFS_PRIORITY,
            # Silence herbie's per-fetch chatter ("✅ Found …", subset download
            # rows, "Note: Returning a list of …") — a national run makes
            # dozens of fetches and each would print several lines into the
            # product output. Meaningful state still reaches the user via our
            # own logger (retries, truncation heals, batch progress).
            verbose=False,
        )

    def _verified_subset_download(
        self,
        herbie,
        search: str,
        fxx: int,
        what: str,
        *,
        resumable: bool = False,
    ) -> int | None:
        """Download a GRIB subset to disk, then verify it against the idx inventory.

        Large pressure subsets use a range-aware downloader that keeps a partial
        prefix and resumes it. Small subsets retain Herbie's original behavior;
        a mismatched cache there is deleted before retry. No incomplete file is
        ever parsed.

        Big transfers log progress at INFO (herbie's own chatter is silenced, so
        without this a multi-minute cube download looks hung from the CLI).
        Verified fresh transfers accumulate into ``self.network_bytes[what]``;
        disk-cache hits do not.
        """
        expected = _subset_payload_bytes(herbie, search)
        local: Path | None = None
        initial_size = 0
        was_complete = False
        if expected is not None:
            local = Path(herbie.get_localFilePath(search))
            initial_size = local.stat().st_size if local.exists() else 0
            was_complete = initial_size == expected
        can_resume = (
            resumable
            and expected is not None
            and local is not None
            and _resumable_source(herbie) is not None
        )
        announce = expected is not None and expected >= _PROGRESS_ANNOUNCE_BYTES
        if announce and was_complete:
            logger.info(
                "GFS %s subset f%02d: using cached %.0f MB",
                what, fxx, expected / 1e6,
            )
        elif announce and can_resume and 0 < initial_size < expected:
            logger.info(
                "GFS %s subset f%02d: resuming %.0f/%.0f MB from disk…",
                what, fxx, initial_size / 1e6, expected / 1e6,
            )
        elif announce:
            logger.info(
                "GFS %s subset f%02d: downloading %.0f MB (one-off per cycle, "
                "cached on disk afterwards)…",
                what, fxx, expected / 1e6,
            )
        started = time.perf_counter()
        if not was_complete:
            if can_resume:
                download = lambda: _download_resumable_subset(herbie, search)
            else:
                download = lambda: herbie.download(search)
            if announce and local is not None:
                _download_with_heartbeat(download, local, what, fxx, expected)
            else:
                download()
        if expected is not None:
            assert local is not None
            actual = local.stat().st_size if local.exists() else None
            if actual != expected:
                if local.exists() and not can_resume:
                    local.unlink()
                disposition = (
                    "kept for resume" if can_resume else "deleted for re-download"
                )
                raise GFSUnavailable(
                    f"GFS {what} subset f{fxx:02d} truncated "
                    f"({actual}/{expected} bytes) — {disposition}"
                )
            if not was_complete:
                credited = (
                    expected - min(initial_size, expected) if can_resume else expected
                )
                self.network_bytes[what] = (
                    self.network_bytes.get(what, 0) + credited
                )
        if announce and not was_complete:
            logger.info(
                "GFS %s subset f%02d: ready (%.0f MB in %.0f s)",
                what, fxx, expected / 1e6, time.perf_counter() - started,
            )
        return expected

    def _download_dataset(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        """Download + parse the GFS pressure-level subset via Herbie (network)."""
        H = self._herbie(run_dt, fxx, cache_namespace="pressure")
        search = self._select_pressure_search(H)
        self._verified_subset_download(
            H, search, fxx, "pressure", resumable=True
        )
        # cfgrib may split into several datasets by step/type; merge into one
        # isobaric dataset. join="outer" is explicit (not the deprecated
        # default): GFS variables like CLWMR/ICMR are reported on fewer levels
        # than TMP, so the union of levels must be kept (missing levels
        # NaN-filled), and a future xarray default of join="exact" would
        # otherwise raise on the mismatch.
        parsed = H.xarray(search)
        if isinstance(parsed, list):
            return xr.merge(
                parsed, compat="override", combine_attrs="override", join="outer"
            )
        return parsed

    def _download_cover(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        """Download the GFS three-tier cloud covers (LCDC/MCDC/HCDC) via Herbie."""
        H = self._herbie(run_dt, fxx, cache_namespace="cover")
        search = r":(?:LCDC|MCDC|HCDC):"
        self._verified_subset_download(H, search, fxx, "cover")
        # Each étage cover sits on its own cloud-layer level type, so Herbie
        # returns one dataset per cover; merge them on the shared lat/lon grid.
        parsed = H.xarray(search)
        if isinstance(parsed, list):
            return xr.merge(parsed, compat="override", combine_attrs="override")
        return parsed

    def _download_surface(self, run_dt: datetime, fxx: int) -> xr.Dataset:
        """Download (if needed) + parse GFS surface fields (cover, 2 m RH, visibility)."""
        H = self._herbie(run_dt, fxx, cache_namespace="surface")
        search = self._SURFACE_SEARCH
        download_bytes = self._verified_subset_download(H, search, fxx, "surface")
        parsed = H.xarray(search)
        if isinstance(parsed, list):
            parsed = xr.merge(
                parsed, compat="override", combine_attrs="override", join="outer"
            )
        if not any(short in parsed.data_vars for short in self._COVER_SHORTNAMES):
            cover = self._download_cover(run_dt, fxx)
            parsed = xr.merge(
                [parsed, cover], compat="override", combine_attrs="override", join="outer"
            )
        if download_bytes is not None:
            parsed.attrs[_DOWNLOAD_BYTES_ATTR] = download_bytes
        return parsed

    # cfgrib shortnames: LCDC→lcc, MCDC→mcc, HCDC→hcc.
    _COVER_SHORTNAMES = ("lcc", "mcc", "hcc")

    @classmethod
    def _cover_from_dataset(cls, ds: xr.Dataset, lat: float, lon: float) -> EtageCloudCover:
        """Nearest-grid-point three-tier cover.

        A missing single tier defaults to 0%, but if *none* of the expected
        shortnames are present (a parse/shortname mismatch) we raise, so the
        caller degrades to the Open-Meteo coverage instead of silently scoring
        every tier as 0% (which would wrongly zero the presence gate).
        """
        present = [s for s in cls._COVER_SHORTNAMES if s in ds.data_vars]
        if not present:
            raise GFSUnavailable(
                f"GFS cover dataset has none of {cls._COVER_SHORTNAMES}; "
                f"got {list(ds.data_vars)}"
            )

        lats = np.asarray(ds["latitude"].values, dtype=float)
        lons = np.asarray(ds["longitude"].values, dtype=float)
        yi = _nearest_index(lats, lat)
        xi = _nearest_lon_index(lons, lon)

        def cover(short: str) -> float:
            if short not in ds.data_vars:
                return 0.0
            # Squeeze any residual (step/level) dims so extraction is robust.
            arr = np.asarray(ds[short].isel(latitude=yi, longitude=xi).values).ravel()
            if arr.size == 0:
                return 0.0
            value = float(arr[0])
            return value if np.isfinite(value) else 0.0

        return EtageCloudCover(
            low_pct=cover("lcc"), mid_pct=cover("mcc"), high_pct=cover("hcc")
        )

    @staticmethod
    def _surface_grid_from_dataset(
        ds: xr.Dataset,
        bbox: tuple[float, float, float, float],
        run_time: datetime,
        valid_time: datetime,
        source_label: str,
    ) -> SurfaceGrid:
        """Crop GFS surface fields to a bbox; cover→0, RH/VIS→NaN where absent.

        ``bbox`` is ``(lat_min, lat_max, lon_min, lon_max)`` — the same convention
        as ``fetch_cube`` (NOT the (south, west, north, east) order of CN_BBOX).
        Raises ``GFSUnavailable`` if the crop is empty or no cover tier resolves,
        so the caller degrades loudly instead of rendering a blank "ready" map.
        """
        lat_min, lat_max, lon_min, lon_max = bbox
        lats = np.asarray(ds["latitude"].values, dtype=float)
        grid_lons = np.asarray(ds["longitude"].values, dtype=float)
        uses_0_360 = float(np.nanmax(grid_lons)) > 180.0

        def _norm(x: float) -> float:
            return x % 360.0 if uses_0_360 else ((x + 180.0) % 360.0 - 180.0)

        lat_mask = (lats >= lat_min) & (lats <= lat_max)
        lo, hi = _norm(lon_min), _norm(lon_max)
        lon_mask = (grid_lons >= lo) & (grid_lons <= hi) if lo <= hi else (
            (grid_lons >= lo) | (grid_lons <= hi)
        )
        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]
        if lat_idx.size == 0 or lon_idx.size == 0:
            raise GFSUnavailable(f"GFS surface crop is empty for bbox {bbox}")
        sub = ds.isel(latitude=lat_idx, longitude=lon_idx)

        out_lats = np.asarray(sub["latitude"].values, dtype=float)
        out_lons = np.asarray(sub["longitude"].values, dtype=float)
        ny, nx = out_lats.size, out_lons.size
        missing: list[str] = []

        def field(short: str, default: float) -> np.ndarray:
            if short not in sub.data_vars:
                missing.append(short)
                return np.full((ny, nx), default)
            da = sub[short]
            # Collapse any residual (step / single-level) dims cfgrib may keep.
            extra = [d for d in da.dims if d not in ("latitude", "longitude")]
            if extra:
                da = da.isel({d: 0 for d in extra})
            return da.transpose("latitude", "longitude").values.astype(float)

        # cfgrib shortnames: cover lcc/mcc/hcc, 2 m RH r2, surface VIS vis.
        cover = {
            "cloud_low_pct": field("lcc", 0.0),
            "cloud_mid_pct": field("mcc", 0.0),
            "cloud_high_pct": field("hcc", 0.0),
        }
        if all(s in missing for s in ("lcc", "mcc", "hcc")):
            raise GFSUnavailable(
                f"GFS surface dataset has no cover tier (lcc/mcc/hcc); "
                f"got {list(sub.data_vars)}"
            )
        return SurfaceGrid(
            **cover,
            lats=out_lats,
            lons=out_lons,
            humidity_pct=field("r2", np.nan),
            visibility_m=field("vis", np.nan),
            run_time=run_time,
            valid_time=valid_time,
            source_label=source_label,
            missing=missing,
            download_bytes=_dataset_download_bytes(ds),
        )

    # ---- pure transform (tested with synthetic xarray) -----------------

    @staticmethod
    def _cube_from_datasets(
        ds: xr.Dataset,
        bbox: tuple[float, float, float, float],
        levels: tuple[float, ...],
        run_time: datetime,
        valid_time: datetime,
        source_label: str,
        retrieved_at: datetime,
    ) -> AtmosphericCube:
        lat_min, lat_max, lon_min, lon_max = bbox

        grid_levels = [float(v) for v in np.asarray(ds["isobaricInhPa"].values).ravel()]
        present_levels = sorted(
            (lv for lv in levels if lv in set(grid_levels)), reverse=True
        )
        if not present_levels:
            raise GFSUnavailable(
                f"GFS pressure dataset has none of the requested levels {levels}; "
                f"got {grid_levels}"
            )

        lats = np.asarray(ds["latitude"].values, dtype=float)
        grid_lons = np.asarray(ds["longitude"].values, dtype=float)
        uses_0_360 = float(np.nanmax(grid_lons)) > 180.0

        def _norm(x: float) -> float:
            return x % 360.0 if uses_0_360 else ((x + 180.0) % 360.0 - 180.0)

        lat_mask = (lats >= lat_min) & (lats <= lat_max)
        lo, hi = _norm(lon_min), _norm(lon_max)
        if lo <= hi:
            lon_mask = (grid_lons >= lo) & (grid_lons <= hi)
        else:  # bbox crosses the 0/360 seam
            lon_mask = (grid_lons >= lo) | (grid_lons <= hi)

        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]
        if lat_idx.size == 0 or lon_idx.size == 0:
            raise GFSUnavailable(f"GFS pressure crop is empty for bbox {bbox}")

        sub = ds.isel(latitude=lat_idx, longitude=lon_idx)

        out_lats = np.asarray(sub["latitude"].values, dtype=float)
        out_lons = np.asarray(sub["longitude"].values, dtype=float)
        nz, ny, nx = len(present_levels), out_lats.size, out_lons.size

        shorts_by_field: dict[str, list[str]] = {}
        for short, field in GFS_VAR_MAP.items():
            shorts_by_field.setdefault(field, []).append(short)
        arrays: dict[str, np.ndarray] = {}
        missing: list[str] = []
        for field_name in PROFILE_VARS:
            short = next(
                (candidate for candidate in shorts_by_field[field_name] if candidate in sub.data_vars),
                None,
            )
            if short is not None:
                da = sub[short]
                required_dims = {"isobaricInhPa", "latitude", "longitude"}
                if not required_dims.issubset(da.dims):
                    arr = np.full((nz, ny, nx), np.nan)
                    missing.append(field_name)
                    arrays[field_name] = arr
                    continue

                extra_dims = [dim for dim in da.dims if dim not in required_dims]
                if extra_dims:
                    da = da.isel({dim: 0 for dim in extra_dims})

                try:
                    arr = (
                        da.sel(isobaricInhPa=present_levels)
                        .transpose("isobaricInhPa", "latitude", "longitude")
                        .values.astype(float)
                    )
                except ValueError as exc:
                    if not _is_empty_xarray_selection_error(exc):
                        raise
                    arr = np.full((nz, ny, nx), np.nan)
                    for zi, level in enumerate(present_levels):
                        try:
                            values = (
                                da.sel(isobaricInhPa=level)
                                .transpose("latitude", "longitude")
                                .values.astype(float)
                            )
                        except KeyError:
                            continue
                        except ValueError as level_exc:
                            if not _is_empty_xarray_selection_error(level_exc):
                                raise
                            continue
                        if values.shape != (ny, nx):
                            values = np.asarray(values, dtype=float).squeeze()
                        if values.shape != (ny, nx):
                            raise GFSUnavailable(
                                f"GFS field {short!r} has unexpected shape "
                                f"{values.shape}; expected {(ny, nx)}"
                            )
                        arr[zi] = values
                if arr.shape != (nz, ny, nx):
                    arr = np.asarray(arr, dtype=float).squeeze()
                if arr.shape != (nz, ny, nx):
                    raise GFSUnavailable(
                        f"GFS field {short!r} has unexpected shape {arr.shape}; "
                        f"expected {(nz, ny, nx)}"
                    )
                if not np.isfinite(arr).any():
                    missing.append(field_name)
            else:
                arr = np.full((nz, ny, nx), np.nan)
                missing.append(field_name)
            arrays[field_name] = arr

        return AtmosphericCube(
            lats=out_lats,
            lons=out_lons,
            levels_hpa=np.asarray(present_levels, dtype=float),
            run_time=run_time,
            valid_time=valid_time,
            source_label=source_label,
            retrieved_at=retrieved_at,
            missing=missing,
            **arrays,
        )


def _as_utc(time: datetime) -> datetime:
    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    return time.astimezone(timezone.utc)
