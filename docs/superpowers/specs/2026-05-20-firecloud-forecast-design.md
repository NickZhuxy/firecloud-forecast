# Firecloud Forecast — 设计文档

**日期**: 2026-05-20
**状态**: 历史归档。文中“个人观察 → ML 训练集”路线已废弃，不代表当前计划。

## 概述

一个个人化的火烧云预测项目，把"研究"和"应用"两个板块绑成一个反馈闭环：
研究板块产出气象与大气光学知识；应用板块把这些知识转译成可执行的预测代码；
预测代码在地图上输出概率热力图供使用者决定是否值得出门拍摄；观察结果又反过来
矫正研究板块的假设。

地理范围从美国本土起步，架构上为未来扩展到全球留余地。

## 目标与非目标

### 目标
- 系统化学习火烧云形成的气象/大气光学原理。
- 构建一个**可演进**的火烧云概率预测器（先规则型，未来可插拔加入 ML）。
- 三阶段交付：
  1. **阶段一**：Jupyter notebook 在地图上画出预测概率
  2. **阶段二**：网页应用（任何浏览器访问）
  3. **阶段三**：桌面/移动原生应用
- 本设计文档仅覆盖**阶段一**的完整交付；阶段二/三只留架构占位。

### 非目标
- 不追求商业级精度。
- 不构建用户系统、账号、付费功能。
- 不在阶段一引入任何 ML（无标注数据，先用规则积累观察样本）。
- 不做 Web/Desktop UI（占位目录存在但不实现）。

## 使用场景

主要用户：作者本人。典型流程：

1. 早上想知道今天日落值不值得出门看火烧云。
2. 打开 `apps/notebook/forecast-map.ipynb`。
3. 顶部 cell 设置：日期、目标日落时间（默认今天）、关注的区域 bbox。
4. 运行所有 cell：拉气象数据 → 跑预测 → 在美国地图上画概率热力图。
5. 看完热力图决定是否出门；当晚把实际观察记录到 `research/observations/log.md`。
6. 周末复盘：哪几条规则失准，去 `research/theory/` 查资料、改 `predictor/rules.py`。

## 顶层架构

### 目录结构

```
firecloud-forecast/
├── README.md                 # 项目入口、当前阶段、怎么跑
├── pyproject.toml            # Python 项目配置（用 uv 管理）
├── .gitignore
│
├── research/                 # 板块一：研究
│   ├── README.md             # 研究索引
│   ├── theory/               # 气象/光学原理笔记 (markdown)
│   │   ├── 00-index.md
│   │   ├── cloud-physics.md
│   │   ├── atmospheric-optics.md
│   │   └── ...
│   ├── notebooks/            # 数据探索性分析 (Jupyter)
│   │   └── 01-explore-hrrr-data.ipynb
│   ├── observations/         # 作者自己的火烧云日志
│   │   └── log.md
│   └── data/                 # 原始/中间数据（gitignore 大文件）
│
├── predictor/                # 板块二的核心：可复用 Python 包
│   ├── __init__.py
│   ├── fetch.py              # 气象数据抓取 (WeatherSource 实现们)
│   ├── features.py           # 从气象数据派生火烧云相关特征
│   ├── rules.py              # 规则型评分 (ScoringRule 实现们)
│   ├── score.py              # 对外主接口 + Predictor 协议
│   └── tests/
│
├── apps/                     # 板块二的展示层
│   ├── notebook/             # 阶段一：Jupyter + 地图
│   │   └── forecast-map.ipynb
│   ├── web/                  # 阶段二：占位 (README only)
│   └── desktop/              # 阶段三：占位 (README only)
│
└── docs/
    └── superpowers/specs/    # 本设计文档及未来设计文档
```

### 数据流

```
NOAA HRRR (GRIB2 from AWS S3, via Herbie)
        ↓
   predictor.fetch  ─ on-disk cache (research/data/cache/)
        ↓
   xarray.Dataset
        ↓
   predictor.features  ─ derived: cloud_high_pct, cloud_low_pct,
                                  solar_elevation_at_sunset, humidity, ...
        ↓
   predictor.rules.RuleBasedPredictor  ─ 组合多条 ScoringRule
        ↓
   Forecast(probability, components, explanation, inputs)
        ↓
   apps/notebook/forecast-map.ipynb  ─ cartopy 地图热力图
```

### 关键架构决策

1. **`predictor/` 是独立 Python 包**，notebook / 未来 web / 未来 desktop 都从同一个包导入。研究的演进直接体现为这个包的演进。
2. **Predictor 用 Protocol 定义**（duck typing），不强制继承。未来 `MLPredictor`、`EnsemblePredictor` 写新类即可，调用方代码完全不需改。
3. **规则组合化**：`RuleBasedPredictor` 接受一个 `list[ScoringRule]` 和一个 `combiner` 函数构造，规则本身是小类。增删规则、调权重、A/B 测试两套规则都不破坏既有代码。
4. **数据源抽象**：`fetch.py` 暴露 `WeatherSource` 协议；HRRR、GFS、Open-Meteo 都是它的实现。从美国扩展到全球时，把 `HRRRSource` 换成 `GFSSource` 即可，上层不感知。

## 板块一：研究 (`research/`)

### `theory/` —— 气象与光学笔记

Markdown 笔记，每篇围绕一个机制或现象。建议起步覆盖：
- `00-index.md` —— 索引与阅读顺序
- `cloud-physics.md` —— 云的高/中/低层分类，云量观测
- `atmospheric-optics.md` —— 瑞利散射 vs 米氏散射，长路径吸收
- `solar-geometry.md` —— 日落时太阳低角度的光学路径
- `aerosols-and-color.md` —— 气溶胶 / PM2.5 对色彩的增强与抑制
- `formation-conditions.md` —— 火烧云形成的综合条件清单

每篇笔记末尾应有"对预测规则的启示"小节，链接到 `predictor/rules.py` 中对应规则。

### `notebooks/` —— 数据探索

Jupyter notebook，主要做：
- HRRR GRIB2 数据初探（解析、变量列表、坐标系统）
- 历史日的气象数据可视化（对比"有火烧云的日子" vs "没有的日子"）
- 规则权重灵敏度分析

不写产品代码——产品代码进 `predictor/`。

### `observations/` —— 观察日志

`log.md` 单文件起步，按日期倒序追加。最小字段：

```markdown
## 2026-05-20
- 地点: Boston, MA
- 日落: 19:42 EDT
- 评级: 4/5 (强烈红橙色，云层有结构)
- 当时观察到的天气: 中云为主，低空清澈，PM2.5 中等
- 预测器给的分: 0.62 (mid_high_cloud_presence=0.8, low_cloud_obstruction=0.2, ...)
- 备注: 模型低估了，可能是因为没考虑XXX
```

将来这就是 ML 阶段的标注集。

## 板块二：预测引擎 (`predictor/`)

### `score.py` —— 对外接口

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

@dataclass
class Forecast:
    probability: float                  # 0.0–1.0
    components: dict[str, float]        # 每条规则的得分
    explanation: str                    # 人类可读
    inputs: dict = field(default_factory=dict)   # 原始气象快照，便于复现

class Predictor(Protocol):
    def score(self, lat: float, lon: float, time: datetime) -> Forecast: ...
```

### `rules.py` —— 规则与组合器

```python
from typing import Protocol, Callable
from predictor.features import Features

class ScoringRule(Protocol):
    name: str
    def evaluate(self, features: Features) -> float: ...   # 返回 0–1

class MidHighCloudPresence:
    name = "mid_high_cloud_presence"
    def evaluate(self, f: Features) -> float: ...

class LowCloudObstruction:
    name = "low_cloud_obstruction"
    def evaluate(self, f: Features) -> float: ...

class SolarAngleAtSunset:
    name = "solar_angle"
    def evaluate(self, f: Features) -> float: ...

class HumidityFactor:
    name = "humidity"
    def evaluate(self, f: Features) -> float: ...

def weighted_average(components: dict[str, float],
                     weights: dict[str, float]) -> float: ...

class RuleBasedPredictor:
    def __init__(
        self,
        rules: list[ScoringRule],
        weights: dict[str, float] | None = None,
        combiner: Callable[[dict, dict], float] = weighted_average,
        source: "WeatherSource" | None = None,
    ): ...

    def score(self, lat, lon, time) -> Forecast:
        weather = self.source.fetch(lat, lon, time)
        feats = features.derive(weather, lat, lon, time)
        components = {r.name: r.evaluate(feats) for r in self.rules}
        prob = self.combiner(components, self.weights)
        return Forecast(prob, components, self._explain(components), inputs=weather.to_dict())
```

阶段一规则集（最少 4 条）：
1. **MidHighCloudPresence** —— 高/中云覆盖在 30–70% 时得分高。
2. **LowCloudObstruction** —— 低云覆盖越高，得分越低（光被挡住）。
3. **SolarAngleAtSunset** —— 太阳低角度时大气光路径长，瑞利散射更强；这条对时间敏感。
4. **HumidityFactor** —— 适中湿度好，过湿（雨）或过干（无水汽）都减分。

### `fetch.py` —— 数据源抽象

```python
class WeatherSnapshot:
    """unified container for one (lat, lon, time) query."""
    # 字段：云分层、湿度、温度、风、气溶胶代理变量等

class WeatherSource(Protocol):
    def fetch(self, lat: float, lon: float, time: datetime) -> WeatherSnapshot: ...

class HRRRSource:
    """通过 Herbie 拉 HRRR GRIB2，按 lat/lon 邻近网格点取值。"""
    def __init__(self, cache_dir: Path): ...
    def fetch(self, lat, lon, time) -> WeatherSnapshot: ...

# 未来：
# class GFSSource:  # 全球扩展
# class OpenMeteoSource:  # 轻量备份
```

磁盘缓存：HRRR 文件按 (run_date, run_hour, forecast_hour) 索引，存到 `research/data/cache/`，重复请求直接读盘。

### `features.py` —— 派生特征

接收 `WeatherSnapshot`，输出 `Features` dataclass：

```python
@dataclass
class Features:
    cloud_low_pct: float
    cloud_mid_pct: float
    cloud_high_pct: float
    solar_elevation_deg: float  # 给定 time 时的太阳高度
    sunset_time: datetime       # 计算得到的当地日落时刻
    humidity_pct: float
    # ... 随研究增加
```

太阳几何用 `astral` 或 `pvlib` 计算。

### 测试策略 (`predictor/tests/`)

- 单元测试每条 `ScoringRule.evaluate`，喂合成 features 断言打分行为
- 单元测试 `RuleBasedPredictor.score` 用 mock `WeatherSource` (固定 snapshot)
- 一个端到端测试：用 JSON fixture 模拟一次 HRRR 查询，跑完整 pipeline，断言概率落在预期区间
- 不打实际网络，所有外部 IO 在测试里用 fixture 替代

## 板块二：展示层 (`apps/`)

### 阶段一：`apps/notebook/forecast-map.ipynb`

单 notebook，由上到下：

1. **配置 cell**：日期、日落时间 (auto)、bbox (默认 CONUS)、网格分辨率
2. **数据 cell**：构造 `HRRRSource` + `RuleBasedPredictor`
3. **网格预测 cell**：对 bbox 内 N×M 网格点并行调 `predictor.score`
4. **可视化 cell**：用 `cartopy` 画美国地图，热力图叠加，城市名标注，给定时刻的日落地形线
5. **解释 cell**：选一个高分点和一个低分点，打印 `Forecast.explanation`

### 阶段二/三 占位

`apps/web/README.md` 和 `apps/desktop/README.md` 各一行：
> 阶段 N 的应用占位，详见后续设计文档。

## 技术栈

| 用途 | 选择 |
|---|---|
| Python 版本 | 3.11+ |
| 依赖管理 | `uv` |
| GRIB2 数据访问 | `Herbie` |
| 数组/数据 | `xarray`, `pandas`, `numpy` |
| GRIB2 解析 | `cfgrib`, `eccodes` |
| 太阳几何 | `astral` 或 `pvlib` |
| 静态地图 | `matplotlib` + `cartopy` |
| 交互地图（备选） | `folium` |
| 测试 | `pytest` |
| Notebook | `jupyter`, `ipykernel` |

## Obsidian 集成

项目目录留在 `~/Desktop/Projects/firecloud-forecast/`。在 Obsidian vault 里建符号链接：

```bash
ln -s /Users/nickzhu/Desktop/Projects/firecloud-forecast \
      "/Users/nickzhu/Documents/Nick's Second Brain/Projects/firecloud-forecast"
```

Obsidian 看到这个文件夹下所有 markdown 均可享 wikilinks、graph view 等能力；
`.ipynb` / `.py` 在 Obsidian 中显示为非 markdown 项，不影响。

## 工作流（飞轮）

```
读资料 / 观察一次火烧云
    ↓
research/theory/ 新增/更新一篇笔记
    ↓
predictor/rules.py 新增 ScoringRule 或调权重
    ↓
predictor/tests/ 加单测
    ↓
apps/notebook/forecast-map.ipynb 重跑，看地图是否更合理
    ↓
对照 research/observations/log.md 实际观察
    ↓
回到第一步
```

研究是因，代码是果，地图是验证场，观察是地基。

## 阶段一交付物清单

- [ ] `pyproject.toml` + `uv` 锁文件，环境可一键复现
- [ ] `.gitignore` 屏蔽 `research/data/cache/` 等大文件目录
- [ ] `predictor/` 包：`score.py`、`rules.py`、`fetch.py`、`features.py` 全部实现到可调用
- [ ] 4 条初始 `ScoringRule` 实现 + 各自单测
- [ ] `HRRRSource` 能从 AWS 拉一次 HRRR 文件并提取所需变量
- [ ] `RuleBasedPredictor.score()` 端到端跑通
- [ ] `apps/notebook/forecast-map.ipynb` 在美国地图上画出概率热力图
- [ ] `research/theory/` 5–10 篇核心原理笔记
- [ ] `research/observations/log.md` 模板就位
- [ ] `README.md` 含环境搭建步骤和示例命令
- [ ] Obsidian 软链接建立
- [ ] 测试套件全部通过

## 风险与不确定性

1. **HRRR 接入复杂度**：GRIB2 + Herbie 学习曲线陡，可能首周大量时间花在搞通数据管道。缓解：早期就写 `research/notebooks/01-explore-hrrr-data.ipynb` 把这部分啃下来。
2. **初始权重纯靠猜**：4 条规则的相对权重在阶段一只能凭直觉给。缓解：等观察日志积累后做事后回归调权。
3. **HRRR 没有气溶胶变量**：火烧云的色彩很依赖气溶胶，但 HRRR 不直接给。可能需要 MERRA-2 或 OpenAQ 补数据，或先在规则里用湿度/能见度做代理。
4. **观察数据自采集慢**：ML 阶段至少需要几个月的连续观察。这是项目固有节奏，无法加速。

## 阶段二/三 展望（仅占位，未来另起设计）

- **阶段二（Web）**：FastAPI 包装 `predictor.score()`，前端 React + Mapbox/Leaflet 渲染热力图。一次 deploy 在 Vercel/Fly.io。
- **阶段三（Desktop）**：Tauri（Rust + Web 前端）包装阶段二的前端，本地缓存 HRRR 数据，离线可用。
- **ML 扩展**：`MLPredictor` 类实现 `Predictor` 协议，训练数据来源 `research/observations/log.md` + 对应历史气象快照。
- **全球扩展**：`GFSSource` 实现 `WeatherSource`；UI 层加区域选择。
