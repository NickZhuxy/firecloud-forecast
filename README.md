# Firecloud Forecast

面向中国地区的火烧云条件预测项目。系统以公开数值预报、物理规则和人工预报经验为基础，输出可解释的**条件指数**；该数值尚未经过统计校准，不应解释为真实概率。

## 当前能力

- 中国区 Leaflet 地图与 FastAPI 后端。
- 单点预报定位当地日落前 10 分钟，并沿真实日落方位分析 0–800 km 的 8 个样点。
- gate × modifier 评分：中高云画布、低云遮挡、太阳时机、洁净空气和照明几何为必要条件；湿度、云高、云量甜区和边界置信度负责调节强度。
- 全国概览使用约 4° 的固定网格、三小时刷新和版本化缓存；它只表达大尺度趋势。

## 运行

```bash
uv sync
uv run uvicorn app.server:app --host 127.0.0.1 --port 8848
```

打开 <http://127.0.0.1:8848/>。

| API | 说明 |
|---|---|
| `GET /api/forecast?lat&lon&date` | 单点条件指数、分项、时间与几何诊断 |
| `GET /api/overlay/cn?date` | 中国区全国概览及缓存状态 |

## 测试

```bash
uv run pytest -m "not integration"  # 默认：不访问外网
uv run pytest -m integration        # 手动：真实数据源检查
```

GRIB/HRRR/GFS 开发在 macOS 上还需要系统库：

```bash
brew install eccodes geos proj
```

## 目录

- `app/` — Web API、全国叠图、前端和应用测试。
- `predictor/` — 数据源、物理特征、空间几何、评分规则和单元测试。
- `research/theory/` — 气象与大气光学依据。
- `research/paper/` — 历史 CONUS 案例论文的 LaTeX 源文件与图表。
- `AGENTS.md` — 多 Agent 协作规则；实时认领记录在本地 `.agent-progress.md`。

## 数据路线与限制

当前 Web 应用使用 Open-Meteo 天气和空气质量接口。它适合单点查询，但不适合作为高分辨率全国格点服务；下一步将接入免费 GFS 0.25° 压力层数据，诊断真实云底、云顶和厚度，再构建日落方向垂直剖面与卫星临近订正。

项目不规划依靠个人长期观察积累训练集。验证优先使用公开模式/卫星资料、离线物理情景、专业观测和同时次人工交叉检查。

## 规划

- [Agile Project](https://github.com/users/NickZhuxy/projects/2)
- [v0.2 · 真实云层诊断](https://github.com/NickZhuxy/firecloud-forecast/milestone/1)
- [#9 · GFS 0.25° 压力层数据适配器](https://github.com/NickZhuxy/firecloud-forecast/issues/9)
