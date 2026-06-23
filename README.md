# Firecloud Forecast

火烧云（sunset glow / 朝霞晚霞）条件预测。两个板块：研究 + 应用。

**当前阶段：Phase 2 — 中国区交互式地图 Web 应用。** 首页显示全国条件指数叠图；点击任意地点，可查看该地当晚日落的评分拆解。

## 板块

- `research/` — 气象/光学原理笔记、论文（`research/paper/`）、《人工火烧云预报速成》、说明与探索 notebook
- `predictor/` — 可复用的 Python 包：`Forecast`, `Predictor`, `ScoringRule`, `RuleBasedPredictor`, `standard_predictor`，数据源 `HRRRSource` / `OpenMeteoSource`，几何 `geometry`
- `app/` — Web 应用：FastAPI 后端（`app/server.py`）+ Leaflet 前端（`app/static/index.html`）
- `apps/` — Phase 1 notebook（CONUS 热力图）
- `docs/superpowers/` — 设计文档与实现计划

## 运行 Web 应用

数据源用 [Open-Meteo](https://open-meteo.com/)（免费、无需 API key、全球、秒级），所以 Web 应用**不需要** HRRR 那套系统依赖。

```bash
uv sync
uv run uvicorn app.server:app --port 8848
```

然后浏览器打开 <http://127.0.0.1:8848/>，点击地图任意位置即可。日期默认今天，可改。

工作原理：全国约 190 点的固定网格批量获取 Open-Meteo 小时预报 → 每个坐标分别定位自己的日落前 10 分钟 → 用 `standard_predictor`（gate × modifier，论文 §6.2）打分 → 插值生成裁切到中国国界的趋势概览。全国图每 3 小时缓存刷新，缓存过期时先返回旧图、在后台生成新图。点击点位会沿真实日落方位取 0–800 km 的剖面，分析云边界距离、下层云遮挡、550 nm AOD 和云层高度风，再返回精细拆解与几何信息。更高分辨率的全国图需要后续接入真正的 GFS/ICON 格点数据源，不能继续把点查询 API 当栅格服务使用。

API：

| 端点 | 说明 |
|---|---|
| `GET /api/overlay/cn?date` | 中国区全国条件指数叠图；可能返回 `ready` / `stale` / `building` 状态 |
| `GET /api/forecast?lat&lon&date` | 单点：当晚日落的条件指数 + 拆解 + 几何 |

## 快速开始

### 系统依赖（macOS）

```bash
brew install eccodes geos proj
```

### Python 环境

```bash
uv sync
```

### 跑测试

```bash
uv run pytest -m "not integration"        # 单元测试
uv run pytest -m integration              # 真实 HRRR 网络测试（手动跑）
```

### 跑 Phase 1 notebook（HRRR / CONUS，需上面的 brew 依赖）

```bash
uv run jupyter lab apps/notebook/forecast-map.ipynb
```

顶部 cell 改 `QUERY_TIME` / `BBOX` / `GRID_RES`，依次 run all。默认 `GRID_RES=3.0` 是 MVP 折中（约 200 个 grid 点，10 分钟内跑完）；更细的 1.5 度网格需要先优化 `HRRRSource` 的 in-memory 缓存。

> 注：Web 应用（上文）用 Open-Meteo，不需要 brew 依赖；只有 HRRR notebook 和 `pytest -m integration` 才需要 `eccodes/geos/proj`。

## 已知限制（Phase 2）

- API 为兼容现有调用仍使用字段名 `probability`，产品界面将它称为“条件指数”，不解释为统计概率。
- AOD 缺失时，洁净空气规则会退回地面能见度；几何计算不会把能见度直接当作整层气溶胶，以免雾和近地湿度造成过度修正。
- 规则权重与阈值来自文献和《人工火烧云预报速成》的定性区间；不规划依靠个人观察日志训练或校准模型。
- 日落方向剖面仍是 8 个离散样点，能判断主要云边界，但无法可靠恢复边界的二维朝向和公里级云洞。
- 数据源是单点/网格预报，未做时间序列（"今晚几点最旺"曲线）——可作为下一步。

## Obsidian 集成

项目目录通过软链接接入 Obsidian vault：

```bash
ln -s /Users/nickzhu/Desktop/Projects/firecloud-forecast \
      "/Users/nickzhu/Documents/Nick's Second Brain/Projects/firecloud-forecast"
```

Markdown 笔记享有 wikilinks / graph view 等能力；`.ipynb` / `.py` 在 Obsidian 中不被解析但可见。

## 设计文档

- 阶段一设计：[docs/superpowers/specs/2026-05-20-firecloud-forecast-design.md](docs/superpowers/specs/2026-05-20-firecloud-forecast-design.md)
- 阶段一实现计划：[docs/superpowers/plans/2026-05-20-firecloud-forecast-phase1.md](docs/superpowers/plans/2026-05-20-firecloud-forecast-phase1.md)
