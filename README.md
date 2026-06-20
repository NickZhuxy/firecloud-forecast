# Firecloud Forecast

火烧云（sunset glow / 朝霞晚霞）概率预测。两个板块：研究 + 应用。

**当前阶段：Phase 2 — 交互式地图 Web 应用。** 在地图上点任意地点，即出该地当晚日落的火烧云概率 + 周边热力图 + 评分拆解。

## 板块

- `research/` — 气象/光学原理笔记、论文（`research/paper/`）、面向非专业读者的说明（`research/explainer.html`）、探索 notebook、观察日志
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

工作原理：选定地点 → 解析该地当晚日落 → 在日落前约 10 分钟、用 `standard_predictor`（gate × modifier，论文 §6.2）对一个网格批量打分（Open-Meteo 多坐标单次请求）→ 地图叠加 magma 概率热力图 + 右侧面板给出概率、必要/增强拆解、几何（持续时长、最大穿透距离）。

API：

| 端点 | 说明 |
|---|---|
| `GET /api/forecast?lat&lon&date` | 单点：当晚日落的火烧云概率 + 拆解 + 几何 |
| `GET /api/forecast/grid?lat&lon&date&radius_deg&step_deg` | 周边网格概率（一次批量请求） |

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

- 几何模块的"等效云底"修正较激进：能见度低于约 196 km 即削减云底高度，加上云底按"最低有云层"估计，所以**持续时长/穿透距离只在干净的中高云天空才显示**，有低云或雾霾时常为空。概率打分不受此影响（规则不依赖几何）。
- 规则权重与阈值仍是文献+直觉的取值，尚未用观察数据拟合校准。
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
