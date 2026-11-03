"""Diagnose each GFS column of a shared cube once per local run.

``AtmosphericCube.profile_at`` returns the *nearest* grid column and stamps that
node's own coordinates on the profile, so the normalized profile, its cloud
layers and its stability depend only on the column index ``(yi, xi)``. Neighbouring
cells of a local grid cross the same columns on their 800 km sunward paths many
times; memoizing on the index gives identical results with far fewer diagnoses.

Callers must treat returned objects as read-only: one instance is shared by every
cell whose observer or path sample falls in that column.
"""
from __future__ import annotations

from predictor.clouds import CloudDiagnosisConfig, DEFAULT_CLOUD_CONFIG, diagnose_clouds
from predictor.normalize import normalize
from predictor.profiles import (
    AtmosphericCube,
    NormalizedProfile,
    _nearest_index,
    _nearest_lon_index,
)
from predictor.stability import (
    DEFAULT_STABILITY_CONFIG,
    StabilityConfig,
    StabilityDiagnosis,
    diagnose_stability,
)


class ColumnDiagnosisCache:
    """Memoize ``normalize``, ``diagnose_clouds`` and ``diagnose_stability`` per column."""

    def __init__(
        self,
        cube: AtmosphericCube,
        config: CloudDiagnosisConfig = DEFAULT_CLOUD_CONFIG,
        stability_config: StabilityConfig = DEFAULT_STABILITY_CONFIG,
    ) -> None:
        self.cube = cube
        self.config = config
        self.stability_config = stability_config
        self.hits = 0
        self.misses = 0
        self._normalized: dict[tuple[int, int], NormalizedProfile] = {}
        self._layers: dict[tuple[int, int], list] = {}
        self._stability: dict[tuple[int, int], StabilityDiagnosis] = {}

    def key(self, lat: float, lon: float) -> tuple[int, int]:
        """The ``(yi, xi)`` column that ``cube.profile_at(lat, lon)`` would return."""
        return _nearest_index(self.cube.lats, lat), _nearest_lon_index(self.cube.lons, lon)

    def _normalized_for(self, key: tuple[int, int], lat: float, lon: float) -> NormalizedProfile:
        profile = self._normalized.get(key)
        if profile is None:
            profile = normalize(self.cube.profile_at(lat, lon))
            self._normalized[key] = profile
        return profile

    def normalized(self, lat: float, lon: float) -> NormalizedProfile:
        return self._normalized_for(self.key(lat, lon), lat, lon)

    def layers(self, lat: float, lon: float) -> list:
        key = self.key(lat, lon)
        layers = self._layers.get(key)
        if layers is None:
            self.misses += 1
            layers = diagnose_clouds(self._normalized_for(key, lat, lon), self.config)
            self._layers[key] = layers
        else:
            self.hits += 1
        return layers

    def stability(self, lat: float, lon: float) -> StabilityDiagnosis:
        key = self.key(lat, lon)
        diagnosis = self._stability.get(key)
        if diagnosis is None:
            diagnosis = diagnose_stability(
                self._normalized_for(key, lat, lon), self.stability_config
            )
            self._stability[key] = diagnosis
        return diagnosis
