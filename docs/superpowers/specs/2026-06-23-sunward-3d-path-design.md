# 日落方位 800 km 三维采样路径 — 设计 (#12)

Parent epic: #2 · Branch: `codex/12-sunward-3d-path`

## 目标

把 PDF 中"沿实际日落方向查看至少 800 km 剖面"的人工流程,转成确定、可测试的
地理采样路径,作为 #18 垂直剖面采样的基础。

## 设计(扩展 `predictor/spatial.py`,纯几何、可注入、零网络)

- `haversine_km` — 球面大圆距离(测试基准)。
- `grid_index(lat, lon, res=0.25)` — GFS 0.25° 全球格点最近索引(lat 90→-90,
  lon 0→360);负经度归一到 0–360,360 列回绕到 0,保证反子午线缝隙连续。
- `solar_azimuth(lat, lon, time)` — 真实太阳方位角(astral,0–360°)。
- `even_distances(max_km=800, count)` — 0–max 均匀采样距离(可配置)。
- `SunwardSample`:`distance_km, lat, lon, grid_lat_idx, grid_lon_idx,
  elevation_m, in_domain`。
- `SunwardPath`:`observer, azimuth_deg, target_time, samples`。
- `build_sunward_path(lat, lon, time, *, azimuth_deg=None, distances_km=...,
  elevation_fn=None, domain=None, res_deg=0.25)`:沿大圆生成各采样点;方位角默认
  用真实太阳方位;地面高程由**注入的 `elevation_fn`** 提供(几何层不绑定数据源,
  保持可测试;海陆由 provider 的高程区分);`domain` 外的点 `in_domain=False`
  且跳过高程查询。

## 验收标准映射

- [x] 输入观测点/日期/时刻,使用真实太阳方位角(`solar_azimuth`)
- [x] 沿大圆生成 0–800 km 可配置采样点(`build_sunward_path` + `even_distances`)
- [x] 输出每点经纬度、距离、地面高程、网格索引(`SunwardSample`)
- [x] 跨经度边界(seam 回绕)、海陆(provider 高程)、超出数据域(`in_domain`)
- [x] 地理距离与方位误差测试(haversine ↔ 标注距离 < 1 km;初始方位 ↔ 方位角)
