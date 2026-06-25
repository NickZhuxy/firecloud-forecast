# 用红外亮温与温度廓线订正云顶 — 设计 (#15)

Parent epic: #5 — 引入卫星临近订正
Milestone: v0.2 · 真实云层诊断
Branch: `codex/15-cloud-top-satellite`
依据 spike #14:主源 **Himawari-9 B13(10.4 µm IR 窗)**,AWS Open Data 匿名 S3。

## 目标

用卫星实测云顶亮温订正模式诊断的云顶高度,减少 NWP 层位偏差。把不透明云在 IR
窗的亮温 `Tb` 当作云顶物理温度,沿温度廓线找到 `T == Tb` 的高度,即卫星观测云顶,
据此订正模式云顶,并对逆温、多解、薄云/半透明云、近等温层、缺测和时差给出
**置信度 + 原因**。

## 验收标准与落点

| AC | 落点 |
|---|---|
| 1 像元↔有效时刻↔位置 配准 | `satellite.py`:`nearest_slot` 取最近 10 min 时次(时间配准);satpy 解码后 pyresample 重投影到 **0.25° 中国网格**(空间配准),`BrightnessTempField.sample` 取最近格点 |
| 2 Tb 匹配廓线候选高度 | `cloud_top.retrieve_cloud_top`(已完成) |
| 3 逆温/多解/薄云/半透明 + 置信度&原因 | `cloud_top.retrieve_cloud_top` / `correct_cloud_top`(已完成) |
| 4 缺测或时差过大安全回退 | `cloud_top.colocate_and_correct`:Tb 为 None/NaN 或 `|obs−valid| > max_gap` → 保留模式云顶;`Himawari9Source` 失败抛 `SatelliteUnavailable` |
| 5 合成 + ≥1 真实样例 | 合成单元测试(已有 8 个)+ `test_satellite.py` 离线单测 + `test_satellite_integration.py`(network-gated 真实 Himawari 上海日落样例) |

## 关键约束(决定架构)

- **纯算法与 I/O 解耦**:`cloud_top.py` 维持"无卫星 I/O 的纯算法"(只接收 `Tb` 与
  廓线/时刻);所有下载/解码/重投影集中在 `satellite.py`。下游可在没有 satpy 的环境
  里只跑算法与回退逻辑。
- **零授权、不加新依赖**:Himawari-9 公共桶可经匿名 HTTPS 取(`requests` 已在依赖里),
  无需 s3fs/boto;HSD 解码用可选依赖 `satpy`(`[satellite]` extra)。
- **重投影到既有 0.25° 网格**:与 GFS `SurfaceGrid` 对齐,使"配准到模式网格"= 精确
  的最近格点,一次下载可服务整片 bbox 的多点订正。
- **AHI 全盘分 10 段**:B13 为 2 km → `R20`,分 `S0110…S1010`。默认取全部 10 段保证
  覆盖中国纬度带;段集合可配置以后优化下载量。

## 模块与数据模型

### `predictor/satellite.py`(新)— Himawari-9 IR 取数层

```python
CHINA_BBOX = (17.0, 54.0, 73.0, 136.0)   # (lat_min, lat_max, lon_min, lon_max)

class SatelliteUnavailable(RuntimeError): ...

@dataclass
class BrightnessTempField:
    lats: np.ndarray              # 1-D,降序(与网格一致)
    lons: np.ndarray             # 1-D,升序
    brightness_temp_k: np.ndarray # (ny, nx);bbox 外/缺测为 NaN
    observation_time: datetime    # 卫星标称时次(UTC)
    band: str                     # "B13"
    source_label: str             # "himawari9@2026-06-22T1100Z/B13"
    retrieved_at: datetime
    def sample(self, lat, lon) -> float: ...   # 最近格点 Tb,NaN 表示无有效像元

# 纯函数(可离线单测)
def nearest_slot(valid_time, cadence_min=10) -> datetime
def himawari_keys(slot, band="B13", resolution="R20", n_segments=10) -> list[str]
def himawari_urls(slot, ...) -> list[str]    # 匿名 HTTPS

class Himawari9Source:
    def fetch_brightness_temp(self, valid_time, bbox=CHINA_BBOX) -> BrightnessTempField
    # 选时次 → 下载段(.DAT.bz2)→ satpy ahi_hsd 读 B13 →
    # pyresample 最近邻重投影到 bbox 0.25° → BrightnessTempField;任何失败抛 SatelliteUnavailable
```

键格式(spike 实测):`AHI-L1b-FLDK/YYYY/MM/DD/HHMM/HS_H09_YYYYMMDD_HHMM_B13_FLDK_R20_Sss10.DAT.bz2`,
桶 `noaa-himawari9`(us-east-1)。

### `predictor/cloud_top.py`(扩展)— 纯配准/订正

```python
@dataclass(frozen=True)
class CloudTopConfig:
    ...                              # 既有字段
    max_time_gap_minutes: float = 30.0   # 卫星时次与模式有效时刻的最大容差

def colocate_and_correct(
    brightness_temp_k: float | None,
    observation_time: datetime | None,
    model_valid_time: datetime,
    model_top_m: float,
    profile: NormalizedProfile,
    config=DEFAULT_CLOUD_TOP_CONFIG,
) -> CloudTopCorrection:
    # Tb None/NaN          → 保留模式云顶(source="model")
    # |obs − valid| > gap  → 保留模式云顶(原因含 "time gap")
    # 否则 retrieve_cloud_top → correct_cloud_top
```

## 测试

- 离线 `test_satellite.py`:`nearest_slot` 向下取整到 10 min;`himawari_keys/urls`
  产出 spike 实测的键/URL;`BrightnessTempField.sample` 最近格点与 NaN 处理。
- 扩展 `test_cloud_top.py`:`colocate_and_correct` 的四条分支(None / NaN / 时差过大 / 正常)。
- `test_satellite_integration.py`(`@pytest.mark.integration`):匿名下载 2026-06-22
  11:00 UTC 上海日落 B13,采样得到合理 `Tb`(~190–300 K),`colocate_and_correct`
  给出合理订正云顶。

## 限制 / 后续

- HSD 解码依赖可选 `satpy`;默认取全部 10 段,下载量较大,后续可只取覆盖中国的段。
- 西部边缘像元视角大、质量降级;FY-4B(105°E)西部补充留待 #16 之后接入。
- 本故事只做云顶订正;云边界与移动趋势在 #16。
