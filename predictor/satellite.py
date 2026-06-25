"""Himawari-9 infrared (B13 ≈10.4 µm) brightness-temperature ingestion (#15).

Per spike #14, Himawari-9 is the primary satellite IR source: the NOAA
``noaa-himawari9`` bucket on AWS Open Data is anonymously readable, so a full-disk
B13 segment can be pulled over plain HTTPS (the project already depends on
``requests``) with no credentials and no new hard dependency. HSD decoding uses
the optional ``satpy`` extra (``ahi_hsd`` reader); the decoded geostationary
field is reprojected onto the project's 0.25° China grid with ``pyresample`` so
that "register the pixel to the model grid" reduces to an exact nearest-grid-point
lookup — the same convention as the GFS ``SurfaceGrid``.

This module is the I/O layer only. The pure retrieval/correction algorithm and
the missing-data fallback live in :mod:`predictor.cloud_top`, which never imports
satpy, so the algorithm runs in environments without the satellite extra.
"""
from __future__ import annotations

import bz2
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from predictor.profiles import _nearest_index, _nearest_lon_index

# China domain as (lat_min, lat_max, lon_min, lon_max), matching the GFS adapter
# bbox convention (national_product.CN_BBOX expressed in the same axis order).
CHINA_BBOX: tuple[float, float, float, float] = (17.0, 54.0, 73.0, 136.0)

# Himawari Standard Data full-disk layout: every band is split into 10 segments
# (north→south). B13 (10.4 µm) is a 2 km band → resolution tag ``R20``.
N_SEGMENTS = 10
_BAND_RESOLUTION = {
    "B01": "R10", "B02": "R10", "B03": "R05", "B04": "R10",
    **{f"B{n:02d}": "R20" for n in range(5, 17)},
}
_BUCKET_URL = "https://noaa-himawari9.s3.amazonaws.com"
_FULL_DISK_CADENCE_MIN = 10


class SatelliteUnavailable(RuntimeError):
    """Raised when no usable Himawari-9 IR field could be obtained."""


@dataclass
class BrightnessTempField:
    """IR window brightness temperature on the 0.25° China grid.

    ``lats`` descend and ``lons`` ascend (one read serves many points, like the
    GFS ``SurfaceGrid``). Pixels outside the satellite disk or otherwise without
    a valid retrieval are ``NaN``.
    """

    lats: np.ndarray              # 1-D, descending
    lons: np.ndarray              # 1-D, ascending
    brightness_temp_k: np.ndarray  # (ny, nx)
    observation_time: datetime    # nominal satellite slot (UTC)
    band: str
    source_label: str
    retrieved_at: datetime

    def sample(self, lat: float, lon: float) -> float:
        """Nearest-grid-point brightness temperature (``NaN`` if masked)."""
        yi = _nearest_index(self.lats, lat)
        xi = _nearest_lon_index(self.lons, lon)
        return float(self.brightness_temp_k[yi, xi])


def _as_utc(time: datetime) -> datetime:
    if time.tzinfo is None:
        time = time.replace(tzinfo=timezone.utc)
    return time.astimezone(timezone.utc)


def nearest_slot(valid_time: datetime, cadence_min: int = _FULL_DISK_CADENCE_MIN) -> datetime:
    """Floor a model valid time to the most recent Himawari full-disk slot."""
    t = _as_utc(valid_time).replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % cadence_min)


def _resolution_for(band: str) -> str:
    try:
        return _BAND_RESOLUTION[band]
    except KeyError as exc:
        raise SatelliteUnavailable(f"unsupported Himawari band {band!r}") from exc


def himawari_keys(
    slot: datetime,
    band: str = "B13",
    resolution: str | None = None,
    n_segments: int = N_SEGMENTS,
) -> list[str]:
    """S3 object keys for every segment of one full-disk band at ``slot``."""
    slot = _as_utc(slot)
    resolution = resolution or _resolution_for(band)
    prefix = f"AHI-L1b-FLDK/{slot:%Y/%m/%d/%H%M}"
    stem = f"HS_H09_{slot:%Y%m%d_%H%M}_{band}_FLDK_{resolution}"
    return [
        f"{prefix}/{stem}_S{seg:02d}{n_segments:02d}.DAT.bz2"
        for seg in range(1, n_segments + 1)
    ]


def himawari_urls(slot: datetime, **kwargs) -> list[str]:
    """Anonymous HTTPS URLs for the segments returned by :func:`himawari_keys`."""
    return [f"{_BUCKET_URL}/{key}" for key in himawari_keys(slot, **kwargs)]


class Himawari9Source:
    """Fetch a Himawari-9 IR brightness-temperature field over a bbox.

    Downloads the full-disk B13 segments anonymously over HTTPS, decodes them
    with satpy's ``ahi_hsd`` reader, and reprojects onto a regular 0.25° China
    grid with pyresample so a point query is a nearest-grid-point lookup. satpy
    and pyresample are imported lazily (the ``[satellite]`` extra) so this module
    stays importable without them.
    """

    DEFAULT_CACHE_DIR = Path("research/data/cache/himawari")

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        resolution_deg: float = 0.25,
        n_segments: int = N_SEGMENTS,
    ):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolution_deg = float(resolution_deg)
        self.n_segments = int(n_segments)

    def fetch_brightness_temp(
        self,
        valid_time: datetime,
        bbox: tuple[float, float, float, float] = CHINA_BBOX,
        band: str = "B13",
    ) -> BrightnessTempField:  # pragma: no cover - network/satpy path, integration-only
        slot = nearest_slot(valid_time)
        keys = himawari_keys(slot, band=band, n_segments=self.n_segments)
        try:
            paths = [self._ensure_segment(key) for key in keys]
            bt, lats, lons = self._decode_and_grid(paths, bbox, band)
        except SatelliteUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any I/O/decoder failure uniformly
            raise SatelliteUnavailable(
                f"Himawari-9 {band} unavailable for {slot:%Y-%m-%dT%H%MZ}: {exc}"
            ) from exc
        return BrightnessTempField(
            lats=lats, lons=lons, brightness_temp_k=bt,
            observation_time=slot, band=band,
            source_label=f"himawari9@{slot:%Y-%m-%dT%H%MZ}/{band}",
            retrieved_at=datetime.now(timezone.utc),
        )

    # ---- internals ------------------------------------------------------

    def _ensure_segment(self, key: str) -> Path:  # pragma: no cover - network, integration-only
        """Download + decompress one ``.DAT.bz2`` segment, caching the ``.DAT``."""
        import requests

        dat_path = self.cache_dir / Path(key).name[:-4]  # strip ".bz2"
        if dat_path.exists() and dat_path.stat().st_size > 0:
            return dat_path
        url = f"{_BUCKET_URL}/{key}"
        resp = requests.get(url, timeout=120)
        if resp.status_code != 200:
            raise SatelliteUnavailable(f"{url} → HTTP {resp.status_code}")
        tmp = dat_path.with_suffix(dat_path.suffix + ".part")
        tmp.write_bytes(bz2.decompress(resp.content))
        tmp.replace(dat_path)
        return dat_path

    def _decode_and_grid(self, paths, bbox, band):  # pragma: no cover - satpy/pyresample, integration-only
        """satpy decode of B13 → nearest-neighbour resample onto the bbox grid."""
        from pyresample.geometry import AreaDefinition
        from satpy import Scene

        lat_min, lat_max, lon_min, lon_max = (float(v) for v in bbox)
        step = self.resolution_deg
        nx = max(1, round((lon_max - lon_min) / step))
        ny = max(1, round((lat_max - lat_min) / step))
        area = AreaDefinition(
            "china025", "China 0.25°", "china025",
            {"proj": "longlat", "datum": "WGS84"},
            nx, ny, (lon_min, lat_min, lon_max, lat_max),
        )
        scene = Scene(reader="ahi_hsd", filenames=[str(p) for p in paths])
        scene.load([band], calibration="brightness_temperature")
        local = scene.resample(area, resampler="nearest", radius_of_influence=5000)
        bt = np.asarray(local[band].values, dtype=float)  # (ny, nx), row 0 = north

        # Pixel centres of the regular longlat grid: lats descend, lons ascend.
        lats = lat_max - (np.arange(ny) + 0.5) * step
        lons = lon_min + (np.arange(nx) + 0.5) * step
        return bt, lats, lons
