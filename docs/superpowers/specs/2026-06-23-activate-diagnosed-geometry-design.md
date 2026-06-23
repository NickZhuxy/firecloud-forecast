# 在实时单点详细预报中激活诊断云层几何 — 设计 (#30)

Parent epic: #4 (integration) · Branch: `codex/30-activate-diagnosed-geometry`
来源:PR #29(#13)review 的后续。

## 目标

把 #9→#6→#10→#13 的诊断链路接入**生产单点详细预报**,让真实云底首次影响实际
评分。全国概览网格保持 Open-Meteo 快路径不变(GFS 太慢)。

## 设计

- **`predictor/rules.py`**:`score_snapshot(..., cloud_layers=None)` 透传给 `derive`。
  默认 None → 网格/`score()` 行为不变。
- **`app/server.py`**:
  - 模块级 `_gfs_source = GFSSource()`(实例内存缓存复用同 cycle 解析结果)。
  - `_diagnose_cloud_layers(lat, lon, t_score)`:GFS profile → normalize →
    diagnose_clouds;**任何异常吞掉返回 None**(网络/不可用 → 优雅回退)。
  - `_point_forecast`(仅单点详细路径)调用它,把 cloud_layers 同时传给 `derive`
    与 `score_snapshot`。全国网格(`app/overlay.py`)不触碰,保持快路径。

## 取舍

GFS(Herbie GRIB)秒级延迟,仅用于点击详情面板(用户已确认可接受);首点付下载
成本,同 cycle 后续点命中内存缓存。失败永不阻断——回退到 source/fixed 路径。

## 测试

- 诊断路径:GFS 返回高云层 → 响应 `cloud_base_source="diagnosed"`、云底=诊断值。
- 回退路径:GFS 不可用 → `fixed_estimate`,预报不报错。
- 助手降级:`_diagnose_cloud_layers` 吞掉异常返回 None。
- 现有点/网格测试 stub 掉 GFS,保持离线确定性。217 passed。
