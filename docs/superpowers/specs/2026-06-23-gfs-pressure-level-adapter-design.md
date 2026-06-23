# GFS 0.25° 压力层数据适配器 — 设计 (#9)

Parent epic: #4 — 基于免费数据诊断真实云层
Milestone: v0.2 · 真实云层诊断
Branch: `codex/9-gfs-adapter`

## 目标

为点位探空、800 km 剖面和全国栅格提供同一套免费原始模式数据入口:从 GFS
0.25° 压力层 GRIB 取出诊断所需变量,标准化为带单位和坐标的
`AtmosphericProfile`(单点垂直列)与 `AtmosphericCube`(区域网格),供下游
#6(标准化廓线)、#10(多层云诊断)消费。

## 关键约束(决定架构)

GFS 的 GRIB byte-range 子集按 message = 按(变量 × 层级)切,每条 message 是
**全球** 0.25° 场。因此:

- 下载量只能靠"少选变量/层级"降低,**不能靠 bbox 降低**。
- 单点与区域下载成本相同;区别仅在解析后内存里如何取值。
- 全球 cube(721×1441×20 层×8 变量×4B ≈ 6.6 GB)不可整存 →
  **Cube 必须按 bbox 在内存裁剪**;单点取最近格点列。

## 模块与数据模型

把"数据类型"与"拉取机制"解耦,使 #6 能在不依赖 Herbie 的情况下消费 profile。

### `predictor/profiles.py` — 纯数据类型(仅依赖 numpy)

```python
@dataclass
class AtmosphericProfile:          # 单点垂直列
    lat: float; lon: float                  # 实际命中的格点
    levels_hpa: np.ndarray                  # 压力层,降序(高压在前)
    temperature_k: np.ndarray
    relative_humidity_pct: np.ndarray
    specific_humidity_kg_kg: np.ndarray
    geopotential_height_m: np.ndarray
    u_wind_m_s: np.ndarray
    v_wind_m_s: np.ndarray
    vertical_velocity_pa_s: np.ndarray
    cloud_water_kg_kg: np.ndarray
    cloud_ice_kg_kg: np.ndarray
    run_time: datetime; valid_time: datetime
    source_label: str                       # "gfs@2026-06-23T00Z+f06"
    retrieved_at: datetime
    missing: list[str]                      # 整列缺失的变量名

@dataclass
class AtmosphericCube:             # 区域网格(bbox 裁剪后)
    lats: np.ndarray              # 1D (ny)
    lons: np.ndarray             # 1D (nx)
    levels_hpa: np.ndarray       # 1D (nz)
    temperature_k: np.ndarray    # (nz, ny, nx) ... 其余变量同形状
    run_time / valid_time / source_label / retrieved_at / missing
    def profile_at(self, lat, lon) -> AtmosphericProfile
```

- 逐层缺测用 **NaN**(numeric 友好);整变量缺失记入 `missing`。
- 每个变量数组与 `levels_hpa` 同长(profile)或 `(nz, ny, nx)` 同形(cube)。
- `profile_at` 用最近格点(1D 经纬度;经度按 0–360 与 ±180 兼容处理)。

### `predictor/gfs.py` — `GFSSource`

```python
class GFSSource:
    DEFAULT_CACHE_DIR = Path("research/data/cache/gfs")
    DEFAULT_LEVELS_HPA = (1000, 975, 950, 925, 900, 850, 800, 750, 700, 650,
                          600, 550, 500, 450, 400, 350, 300, 250, 200, 150)
    def fetch_profile(self, lat, lon, valid_time) -> AtmosphericProfile
    def fetch_cube(self, bbox, valid_time) -> AtmosphericCube   # bbox=(lat_min,lat_max,lon_min,lon_max)
```

## 默认层级与变量

- **层级(20)**:1000→150 hPa 标准层(覆盖低云至 ~13–14 km 卷云高度)。
- **变量**:`TMP(t)`、`RH(r)`、`SPFH(q)`、`HGT(gh)`、`UGRD/VGRD(u/v)`、
  `VVEL(w)`、`CLWMR(clwmr)`、`ICMR(icmr)`。对应 issue 列出的
  温度 / 湿度 / 位势高度 / 风 / 垂直速度 / 云水。

## 时间选择 / 缓存 / 降级

- **cycle 选择**:GFS 每 6h(00/06/12/18Z),约 4h 时延;取
  ≤ `valid_time − 4h` 的最近 cycle,fxx 取最近(pgrb2.0p25 逐小时 f000–120)。
- **缓存(两层,复用 HRRR 模式)**:
  1. Herbie 磁盘 GRIB 缓存(按 cycle = "版本")。
  2. 实例内存 parsed-dataset 缓存,键 `(run_dt, fxx)` → 同 cycle 重复查询不重解析、不重下载。
- **失败降级**:最近 cycle 不可用 → 回退前一个 cycle(最多 2 步);全失败抛
  `GFSUnavailable`,由调用方决定降级。

## 测试(对应验收标准)

- 纯转换函数 `_profile_from_datasets(...)` / `_cube_from_datasets(...)` 为
  staticmethod(照搬 HRRR `_snapshot_from_datasets` 模式),用小型合成
  `xarray.Dataset` 做单测,**零网络**。
- 覆盖:最近格点(含 0–360 经度)、bbox 裁剪、`cube.profile_at`、
  整变量缺失记 `missing`、逐层缺测填 NaN、cycle/fxx 选择、cycle 回退降级。
- **live smoke**:`python -m predictor.gfs_smoke --lat 31.23 --lon 121.47`(上海)
  打印廓线表;不纳入默认 pytest(另配一个 `integration`-marked 测试)。

## 验收标准映射

- [ ] 上海点位完整压力层廓线 → `fetch_profile` + smoke 命令。
- [ ] 重复请求命中缓存不重复下载 → 内存 parsed-dataset 缓存 + Herbie 磁盘缓存。
- [ ] 单元测试用本地 fixture 不依赖实时网络 → 合成 xarray 测纯转换。
- [ ] 显式 live smoke 命令但不纳入默认测试 → `predictor.gfs_smoke` + integration marker。
