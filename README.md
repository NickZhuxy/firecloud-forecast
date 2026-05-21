# Firecloud Forecast

火烧云（sunset glow / 朝霞晚霞）概率预测。两个板块：研究 + 应用。

**当前阶段：Phase 1 — Jupyter notebook 在美国本土地图上画概率热力图。**

后续：Phase 2（Web app）→ Phase 3（Desktop app）。

## 板块

- `research/` — 气象/光学原理笔记、探索 notebook、观察日志
- `predictor/` — 可复用的 Python 包：`Forecast`, `Predictor`, `ScoringRule`, `RuleBasedPredictor`, `HRRRSource`
- `apps/` — 展示层：notebook（已实现）、web 与 desktop（占位）
- `docs/superpowers/` — 设计文档与实现计划

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

### 跑 Phase 1 notebook

```bash
uv run jupyter lab apps/notebook/forecast-map.ipynb
```

顶部 cell 改 `QUERY_TIME` / `BBOX` / `GRID_RES`，依次 run all。默认 `GRID_RES=3.0` 是 MVP 折中（约 200 个 grid 点，10 分钟内跑完）；更细的 1.5 度网格需要先优化 `HRRRSource` 的 in-memory 缓存。

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
