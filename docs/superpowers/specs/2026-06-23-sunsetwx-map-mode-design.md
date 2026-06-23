# 地图显示模式改为 SunsetWx 风格 — 设计 (#40)

Branch: `codex/40-sunsetwx-map-mode`

## 目标(来自 issue #40 + sunsetwx.com 参考)

参考 SunsetWx 的地图形式:类似的颜色、图像、标题格式,把美国地图换成中国地图;
保持地图**可拖动、可缩放**;并**移除具体点位分析功能**(现在做这个不成熟)。

## 决策

- 配色:对照 sunsetwx.com 实测,采用 **turbo 质量色阶**(深蓝=低 → 青/绿/黄/橙 →
  红=高),"颜色越暖 = 火烧云条件越好"。
- 交互:SunsetWx 是静态图;我们保留 **Leaflet 交互地图**(拖动/缩放),叠加层为
  仅含数据场的透明 PNG(随底图对齐),把 SunsetWx 的标题/图例做成 **HTML chrome**
  ——若把标题/坐标轴烘焙进 PNG 会破坏缩放对齐。
- 移除点位分析:**前端 UI + 后端接口都删**(用户决定)。

## 改动

- **`app/overlay.py`**:配色从 pink/purple 自定义 cmap 改为 `turbo`(masked 透明),
  去掉粉色等值线(SunsetWx 是平滑无线条场);`CACHE_SCHEMA_VERSION` v2→v3 使旧
  缓存失效重绘。
- **`app/static/index.html`**:移除点位详情面板/点击/marker/`updatePoint`/
  `renderPanel`/提示及相关 CSS/JS;改为干净的浅色 SunsetWx 风格——标题卡
  (标题 + Valid 行 + "颜色越暖=更好")+ turbo 渐变图例(差→好);保留 Leaflet
  拖动/缩放、日期选择、刷新状态。叠加层 opacity 0.85 让底图边界透出做地理定位。
- **`app/server.py`**:删除 `/api/forecast` 路由、`_point_forecast`、GFS 点位诊断
  (`_diagnose_cloud_layers/_diagnose_cloud_cover`)、点位缓存、`_astral_sunset` 及
  相关 import;保留 `/api/overlay/cn`、`/api/overlay/image`、`/api/health`、`/`。
- **tests**:`test_server.py` 改为概览 + 移除验证(`/api/forecast` → 404);
  `test_overlay.py` 缓存键 v2→v3。

## 验收(issue #40)

- [x] SunsetWx 风格颜色/图像/标题格式(turbo + 标题卡 + 暖色=更好图例)
- [x] 美国地图 → 中国地图(已为中国 bbox,turbo 渲染目视确认)
- [x] 可拖动、可缩放(Leaflet 保留)
- [x] 移除点位分析(前端 + 后端)

## 测试

`uv run pytest -m "not integration"` → **258 passed, 3 deselected**;已本地渲染
turbo 叠加层目视确认。
