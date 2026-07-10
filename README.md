# Firecloud Forecast

面向中国地区的火烧云条件预测算法与本地科研制图工具。系统使用公开数值预报、物理规则
和人工预报经验，输出可解释的**条件指数**；该数值尚未经过统计校准，不应解释为真实
概率。

项目不维护交互网页或在线 API。全国标准图可由 GitHub Actions 远端预计算并通过
GitHub Pages 静态分发；本地科研计算与公开分享仍使用同一张 SunsetWx 风格标准图。

## 当前能力

- GFS 0.25° 压力层、三档云量、2m 相对湿度、能见度与全国地面网格读取。
- 温湿廓线标准化、多层云诊断、云底/云顶/相态/置信度与照明几何。
- 沿真实日落方位的 0–800 km 三维路径和垂直剖面诊断。
- gate × modifier 可解释评分，并与标量规则保持 `1e-9` 等价。
- 中国全国场按每格日落时间选择最近的共同 GFS cycle 时次后向量化评分。
- 本地输出完整 SunsetWx 风格 PNG 与 JSON 元数据。
- 全国成品支持远端预计算、SHA-256 校验、过期检查和本地缓存回退。

## 安装

```bash
uv sync
```

GRIB/GFS 开发在 macOS 上还需要：

```bash
brew install eccodes geos proj
```

## 生成预测图（统一 `firecloud` CLI）

```bash
firecloud                              # 今天 · 全国 · 朝霞 + 晚霞
firecloud --date 2026-06-29
firecloud --event sunrise              # 只出朝霞
firecloud --source remote              # 只取远端成品，失败时绝不启动大下载
firecloud --source local               # 明确在本机下载 GFS 并完整计算
firecloud --lat 31.2 --lon 121.5       # + 局部精细产品（坐标周边跑完整单点物理）
firecloud --lat 31.2 --lon 121.5 --radius 120 --resolution 0.2
```

全国图默认使用 `--source auto`：先获取远端预计算的 PNG/JSON，远端尚未发布、已过期或
校验失败时才回退到本地完整计算。已经下载且仍在有效期内的远端成品可在短暂断网时复用。
局部精细产品没有远端版本，给出 `--lat/--lon` 后仍会在本机计算；因此
`--source remote` 目前只支持全国图。

输出按日期建文件夹，文件名带事件（朝霞/晚霞同日不再互相覆盖）；给坐标再加局部图：

```text
output/2026-06-29/national-sunrise.png
output/2026-06-29/national-sunset.png
output/2026-06-29/point-31.2_121.5-sunrise.png    # 给 --lat/--lon 时
output/2026-06-29/point-31.2_121.5-sunset.png
```

局部图在坐标周边小网格上逐格跑**完整单点物理**（FA-G5 截面光追 + 云诊断），共享一次 GFS cube、
快照按 Open-Meteo 批量取——国家级省掉的真保真，而非密插值。`--radius`（km）/`--resolution`（度）
控制范围与精度（默认 150km / 0.1°，全国域内自动控量）。

PNG 是唯一标准版式，包含模型初始化时间、逐格事件有效时段、行政边界、经纬度与
“暖色更优”色标；JSON 保存相同的数据来源、时间、算法和性能元数据（含 `solar_event`、
`event_range_utc`）。首次运行会下载 GFS GRIB 子集与 Cartopy Natural Earth 地图资料。
`output/` 是本地产物目录，不进入 Git。

## 远端预计算与静态发布

[`.github/workflows/precompute-pages.yml`](.github/workflows/precompute-pages.yml) 在每个 GFS
cycle 发布完成后定时运行，也支持从 Actions 页面手动触发。它默认计算上海日期的今天和
明天、朝霞和晚霞，并把一次完整快照部署到 GitHub Pages：

```text
products/latest/2026-07-10/sunrise.json       # 客户端入口清单
products/runs/<算法版本>/<GFS时次>/...        # 不可变 PNG/JSON 成品
```

首次启用需要在仓库 `Settings → Pages` 中把发布来源设为 **GitHub Actions**，并把工作流
合并到默认分支；定时任务只从默认分支运行。公开仓库使用标准 GitHub-hosted runner，且
Pages 流量和站点体积保持在 GitHub 限额内时，这套方案不需要另买服务器。具体配额以
[GitHub Actions 计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
和 [GitHub Pages 限额](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
为准。

需要在本地检查发布目录时，可以手动构建；这条命令会真的下载并计算 GFS 数据：

```bash
PYTHONPATH=. uv run --no-sync python -m predictor.precompute \
  --days 2 --output _site
```

客户端默认读取 `https://nickzhuxy.github.io/firecloud-forecast/`。测试其他部署时可设置
`FIRECLOUD_REMOTE_BASE_URL`，无需修改代码。

底层单事件入口仍在（同样按日期建子文件夹）：

```bash
PYTHONPATH=. uv run python -m predictor.national_product \
  --date 2026-06-29 --event sunset --output-dir products
# → products/2026-06-29/national-sunset.png + .json
```

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
