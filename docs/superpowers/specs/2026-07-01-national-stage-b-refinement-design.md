# #59 — 全国 Stage B 候选带精修（共享 cube 的 2-D 光追）— 设计

Epic #54 / Issue #59。承接 Stage A（#59 已落地：全国 1-D sunward physics screen，见
[national_physics.py](../../../predictor/national_physics.py)）。路线依据
[智能全国化 spike #58](../../../research/theory/intelligent-nationalization-spike-58.md) §5 的两阶段方案。
Branch: `codex/59-national-field-upgrade`。

本轮交付档位：**内核 + 基准优先（PR-A 式）**。落地精修引擎 + 离线基准 + 接线（开关后），
live 全国压力 cube 取数、三级概率渲染、真实 GFS 缓存样本基准留作下一 PR。

## 目标与核心难点

把单点保真度里可负担的部分（2-D sunward 截面光追 = `score_point_with_cube` 等价逻辑）带到
全国候选格点：对 Stage A screen 打分 `>= threshold` 的格点跑精修，用精修值覆盖候选格点，
非候选格点保持 screen 值。

**难点**：单点物理每点需一个 GFS 压力 cube;候选点**散布全国、跨多个 valid hour**，不能每点取一次。
**解法**：按 `(valid_hour, tile)` 分组候选点，每组取**一次**覆盖该组候选点全部 sunward 路径的 cube，
组内共享。这与 [local_field.py](../../../predictor/local_field.py) 的共享-cube 思路同构，只是键
从「单中心」换成「valid hour × tile」。

**关键观察**：某个 valid hour 被精修的格点是日落终结线扫到的一条经向窄带（非全国散点），
天然被限制在一条经度带内;screen 候选本就稀（spike 基准约 3% 格点），故 cube 数与逐格成本可控。

## 现状约束（为何是新引擎而非改 grid_score）

- 全国路径今天**只取 GFS 地面网格**（云量/RH/能见度），从不取压力 cube;Stage A screen 也只吃地面场。
- `score_point_with_cube`（[sunward_section.py](../../../predictor/sunward_section.py)）分工：
  **cube** 提供垂直廓线 + sunward 截面（贵物理）;**snapshot** 只提供地面观测给 gate/modifier 层。
- 全国路径每格地面场已取到 → 精修 snapshot 可**直接用已选地面场合成 `WeatherSnapshot`，完全免联网**
  （比 local_field 走 Open-Meteo 还省）。

## 改动（PR-A 算法核心，可离线测）

### 1. 新增精修引擎 [national_refine.py](../../../predictor/national_refine.py)

```python
@dataclass
class RefineResult:
    refined_probability: np.ndarray   # (ny,nx)，候选=精修值 其余=screen 值
    refined_mask: np.ndarray          # (ny,nx) bool，真正跑了物理的格点
    cells_refined: int
    cubes_fetched: int
    tiles: int
    tile_deg: float
    distances_km: tuple[float, ...]
    threshold: float

def refine_field(
    cube_source,
    lats, lons,                   # 1-D ascending
    screen_probability,           # (ny,nx) Stage A 结果
    event_times,                  # (ny,nx) 每格事件时刻（sunset/sunrise UTC）
    selected_time,                # (ny,nx) int，national 已算的 valid-hour 索引
    valid_times,                  # tuple[datetime]
    surface_fields,               # dict: cloud_low/mid/high_pct, humidity_pct, visibility_m, aod
    *,
    threshold=0.50,
    tile_deg=5.0,
    distances_km=REFINE_SUNWARD_DISTANCES_KM,   # 0..800 by 50
    margin_deg=0.5,
    config=DEFAULT_CLOUD_CONFIG,
    aod_fn=None,
    max_cube_cells=6000,          # 每块 cube 水平格数上限（tiling 兜底 guard）
) -> RefineResult
```

`max_cube_cells` 默认 `6000`：一块 cube 的水平格数 = `bbox 度面积 / 0.25²`。一个 5° tile + 800 km
（~7°）向西路径 ≈ 12°×5° ≈ 60×20 = 1200 格，`6000` 留足余量又能拦住异常巨块;可调。

`surface_fields["aod"]` 可为 `None`——全国路径目前不取 AOD 场（Stage A screen 现即以 `aod=None` 调用），
故 snapshot 的 `aerosol_optical_depth` 与 `aod_fn` 本轮通常为空，`clean_air` gate 退回能见度。留待接 AOD 时启用。

算法：

1. **候选** = `screen_probability >= threshold`。每候选格点的 valid hour 复用传入的 `selected_time`
   （与 screen/overview 选的 GFS 时次**同一个**，保证一致）。
2. **分组**键 = `(selected_time[cell], floor(lat/tile_deg), floor(lon/tile_deg))`。tile 定义在**观测格**上。
3. **每组**：
   - `bbox` = 组内所有候选点 `build_sunward_path(...)` 采样点的并集 + `margin_deg`（复用
     local_field 的 `_shared_cube_bbox` 同款逻辑）;bbox 向西按路径自然外扩，相邻 tile 西侧路径区
     重叠 cube 属可接受冗余，换有界内存。
   - `bbox` 面积超 `max_cube_cells` → 抛错（明确提示调小 tile_deg / 收窄候选）。
   - `cube = cube_source.fetch_cube(bbox, valid_times[hour_idx])`。
   - 逐候选点：`snapshot ←` 由 `surface_fields` 该格合成 `WeatherSnapshot`
     （`source_label="national-refine"`，`retrieved_at=event_time`）;
     `forecast = score_point_with_cube(predictor, cube, snapshot, lat, lon, event_time,
     distances_km=distances_km, config=config, aod_fn=aod_fn)`;
     `refined_probability[cell] = forecast.probability`。
4. **非候选**格点：`refined_probability = screen_probability`（不变）。
5. `cubes_fetched == 有候选的 (hour,tile) 组数`。

**predictor 来源**：引擎内部自建 `standard_predictor(_PlaceholderSource())`——因为只调
`predictor.score_snapshot`（纯计算），从不调 `predictor.source.fetch`（snapshot 已逐格合成，不触网）。
故 `build_national_field` **不必**改成持有 predictor。

**常量**：`REFINE_SUNWARD_DISTANCES_KM = tuple(range(0, 801, 50))`（50 km 列距，spike §3 证明在合成场上
几乎贴 25 km 真值、成本约一半）。

### 2. 接线到 [national_field.py](../../../predictor/national_field.py)（开关后，零默认回归）

- `build_national_field(...)` 增参 `cube_source=None`。
- screen + `score_grid` 之后：
  ```python
  if config.refine and cube_source is not None:
      result = refine_field(cube_source, lats, lons, probability, sunsets,
                            selected_time, valid_times, selected_fields,
                            threshold=config.refine_threshold,
                            distances_km=config.refine_distances_km, ...)
      probability = result.refined_probability
      physics["refinement"] = {
          "enabled": True, "method": "selected_2d_ray_trace_50km",
          "threshold": config.refine_threshold, "tile_deg": result.tile_deg,
          "distances_km": list(result.distances_km), "status": "run",
          "cells_refined": result.cells_refined, "cubes_fetched": result.cubes_fetched,
          "tiles": result.tiles,
      }
  ```
- 默认 `national_product` **不传** `cube_source` → refine 不跑、`status:"configured_not_run"`,
  行为与现在完全一致。

## 基准升级（#59 可验收数字，离线合成场）

[nationalization_spike.py](../../../research/experiments/nationalization_spike.py) 增一档 `stage_b_refine`：
在现有 9×14 合成场上，用 `refine_field` 对 `screen>=0.50` 候选跑 50 km 精修，与 25 km 单点真值同表比
`MAE / P90 / Max / gradient_mae / F1 / FP / FN` 与 `relative_physics_cost`。预期复现 spike §3
`tiered_1d_screen_plus_full` ≈ 真值、成本约 `0.24x`。真实 GFS 缓存样本基准留作下一 PR 的 `integration` 项。

## 验收不变量（离线，合成数据）

新增 [test_national_refine.py](../../../predictor/tests/test_national_refine.py)，复用
[test_local_field.py](../../../predictor/tests/test_local_field.py) 的合成 cube / predictor 夹具：

1. **保真不变量**：候选格点精修值 == 用**同一 cube** 单独 `score_point_with_cube` 的值
   （与 local_field 同款保真断言，证明精修判据与单点一致）。
2. **分组/成本**：`cubes_fetched == (hour,tile) 组数`;非候选格点值 == screen 值不变;
   `refined_mask` 只覆盖候选。
3. **变形性质**（接 [test_metamorphic_physics.py](../../../predictor/tests/test_metamorphic_physics.py) 风格）：
   在某候选点向西 sunward 路径上加一段低云遮挡 → 其精修概率单调下降。
4. **snapshot 合成**：字段从 `surface_fields` 正确落到 `WeatherSnapshot`。
5. **guard**：tile 的 cube bbox 超 `max_cube_cells` 抛错。
6. **national_field 集成**：传 fake `cube_source` + `refine=True` → probability 变为精修场、
   metadata `status:"run"` 且计数正确;不传 → 零回归（既有 national 测试保绿）。

## 文件清单

- 新增：[national_refine.py](../../../predictor/national_refine.py)、
  [test_national_refine.py](../../../predictor/tests/test_national_refine.py)
- 改：[national_field.py](../../../predictor/national_field.py)（加 `cube_source` 参数与 refine 分支）、
  [nationalization_spike.py](../../../research/experiments/nationalization_spike.py)（加 `stage_b_refine` 档）
- 不改：[grid_score.py](../../../predictor/grid_score.py)、
  [national_product.py](../../../predictor/national_product.py)（默认产品零变化）

## 不在 PR-A（下一 PR 跟进）

- live `GFSSource()` 接进 `national_product` 默认产品、按 tile 真实取压力 cube；
- 三级概率渲染与 metadata（`model` / `screen` / `refined`）;
- 真实 GFS 缓存样本回归基准（`integration` 标记）;
- 安全带 `0.30..0.50` 候选、卫星 nowcast 修正（spike Stage C）。
