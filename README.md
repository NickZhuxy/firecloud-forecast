# Firecloud Forecast

面向中国地区的火烧云条件预测算法与本地科研制图工具。系统使用公开数值预报、物理规则
和人工预报经验，输出可解释的**条件指数**；该数值尚未经过统计校准，不应解释为真实
概率。

项目不再维护网页、在线 API 或上传流程。自己分析与公开分享使用同一张本地生成的
SunsetWx 风格标准图。

## 当前能力

- GFS 0.25° 压力层、三档云量、2m 相对湿度、能见度与全国地面网格读取。
- 温湿廓线标准化、多层云诊断、云底/云顶/相态/置信度与照明几何。
- 沿真实日落方位的 0–800 km 三维路径和垂直剖面诊断。
- gate × modifier 可解释评分，并与标量规则保持 `1e-9` 等价。
- 中国全国场按每格日落时间选择最近的共同 GFS cycle 时次后向量化评分。
- 本地输出完整 SunsetWx 风格 PNG 与 JSON 元数据。

## 安装

```bash
uv sync
```

GRIB/GFS 开发在 macOS 上还需要：

```bash
brew install eccodes geos proj
```

## 生成本地全国预测图

```bash
PYTHONPATH=. uv run python -m predictor.national_product \
  --date 2026-06-24 \
  --output-dir products
```

输出：

```text
products/firecloud-cn-20260624.png
products/firecloud-cn-20260624.json
```

PNG 是唯一标准版式，包含模型初始化时间、逐格日落有效时段、行政边界、经纬度与
“暖色更优”色标；JSON 保存相同的数据来源、时间、算法和性能元数据。首次运行会下载
GFS GRIB 子集与 Cartopy Natural Earth 地图资料。`products/` 是本地产物目录，不进入 Git。

## 其他本地诊断

真实 GFS 单点廓线 smoke：

```bash
PYTHONPATH=. uv run python -m predictor.gfs_smoke --lat 31.23 --lon 121.47
```

代码中还提供 sounding 与日落方向垂直剖面绘图函数，供算法复核和与 Windy/人工分析
并排比较。

## 测试

```bash
PYTHONPATH=. uv run --no-sync pytest -m "not integration"  # 默认，不访问外网
PYTHONPATH=. uv run --no-sync pytest -m integration        # 手动，真实 GFS
```

## 目录

- `predictor/` — 数据源、标准化、云层诊断、几何、评分、全国场和本地制图。
- `predictor/tests/` — 合成场、规则等价、回归与真实数据分层测试。
- `research/theory/` — 气象与大气光学依据。
- `research/paper/` — 历史 CONUS 案例论文的 LaTeX 源文件与图表。
- `docs/superpowers/specs/` — 已交付功能的设计与验收记录。
- `AGENTS.md` — 多 Agent 协作规则；实时认领记录在本地 `.agent-progress.md`。

## 数据路线与限制

全国产品当前基于免费 GFS 0.25°，空间分辨率约 25 km。它是模式预测场，不是真实卫星
云图；FY-4/Himawari 红外亮温和云边界融合属于后续卫星订正路线。

项目不规划依靠个人长期观察积累训练集。验证优先使用公开模式/卫星资料、离线物理
情景、专业观测和同时次人工交叉检查。

## 规划

- [Agile Project](https://github.com/users/NickZhuxy/projects/2)
- [v0.2 · 真实云层诊断](https://github.com/NickZhuxy/firecloud-forecast/milestone/1)
