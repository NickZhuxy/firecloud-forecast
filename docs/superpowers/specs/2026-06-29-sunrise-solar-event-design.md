# #60 — sunrise 泛化（solar_event 参数化）— 设计

Epic #55「本地产品与终端体验」的**地基**（#61/#62/#63 都依赖）。一条代码路径、复用同一套
规则/权重，不复制 sunset 逻辑。Branch（PR-1）: `codex/60-sunrise-point`（off main）。
依据：exhaustive 站点 catalog（85 个有效站点）+ 工作流综合设计。

## 核心洞察：只有四样真正不同，其余全自动

物理左右对称（朝霞↔晚霞镜像）。真正翻转的只有四样，集中在新 `predictor/solar_event.py`：
`astral_key`（事件时刻）、`daily_field`（Open-Meteo daily=）、`fallback_solar_hour`（极区退化
6/18）、`label_en/zh`。**方位与 GFS 时次不是字段**——它们由事件**时刻**自动决定：
`solar_azimuth(lat,lon,time)` 在日出时刻返回 ~90°（东）、日落 ~270°（西）；GFS 选时次只跟事件
时刻网格走。所以**点路径无需方向参数**。

## 镜像不变量（验收）

日出/日落方位关于观察者子午线互为镜像（`sunrise_az = 360 − sunset_az`）。故把场景关于子午线
反射（`lon' = 2·lon_obs − lon`）并在**另一个事件**打分，必须复现原分。
`test_sunrise_mirror.py`：方位东/西、采样路径子午线镜像、**整分镜像**（西侧不透明低云在日落光路
否决；镜像后东侧低云在日出光路否决；两者分数 1e-9 相等）。

## 分阶段 PR

- **PR-1（本 PR，点路径 + seam）**：`solar_event.py`（`SolarEvent`/`SolarEventSpec`/`spec_for`）；
  `features.compute_event_time`（`compute_sunset` 退化为其 sunset 包装）；`OpenMeteoSource(solar_event=…)`
  事件绑定（`_params` 用 `daily_field`、`_nearest_event` 读对应字段、`_snapshot_*`/`fetch*` 串入；
  事件时刻落入既有 `sunset_time` 槽）。镜像验收测试。**不改** spatial/sunward_section/rules（时刻驱动）。
- **PR-2（国家级场）**：`sunset_grid._sunset_timestamp` astral key + fallback hour + cache key；
  `sunset_utc_grid`/`build_national_field` 加 `solar_event`。T3 国家级 sunset 默认字节不变 + 日出 smoke。
- **PR-3（产品渲染 + 文件名 + 标签）**：`national_product` 文件名加事件 token、caption/label、
  `_metadata` `solar_event` 键。**含 fork F3（见下）。**
- **PR-4（可选纯改名）**：`SolarAngleAtSunset`、`sunset_speed_km_min` 等去 sunset 味；无行为。

## 默认字节不变

所有新参数默认 `solar_event="sunset"`：`_params` daily 仍 "sunset"、`_nearest_event` 仍读 sunset、
事件时刻仍 sunset。国家级 grid_score 1e-9 metamorphic 安全（`g_solar=1`、逐格按各自事件时刻）。
504 passed（`-m "not integration"`）；solar_event 100% / fetch 96% / features 95%。

## 设计 fork（owner）

- **F1（已定）**：`OpenMeteoSource` 用**构造属性** `solar_event`（最低 churn；点路径打分入口
  `score_point_with_sunward_section` 无需新参——方位/时次跟事件时刻走）。国家级路径用显式 `solar_event` 形参。
- **F2（已定，延后）**：`sunset_time`/`sunset_range_utc` 等**当事件通用槽**保留旧名（避免序列化/测试 churn），
  纯改名留 PR-4。
- **F3（待 owner，PR-3 时问）**：国家级默认产物文件名加事件 token（`firecloud-cn-{date}` →
  `firecloud-cn-sunset-{date}`）会改**已发布产物名**，触及 #63；到 PR-3 渲染时停下确认。

## 已知小限制（PR-1）

`derive` 的 astral 回退仍走 `compute_sunset`（仅当 snapshot 无事件时刻时触发；Open-Meteo 总会给，
故点路径正常不触发）。日出且无事件时刻的源属边缘情形——如需，后续把 `solar_event` 串入
`derive`/`score_snapshot`/`score_point_with_sunward_section`。
