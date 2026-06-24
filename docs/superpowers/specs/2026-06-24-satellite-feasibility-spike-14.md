# Spike #14 — FY-4 / Himawari 免费数据自动化可用性评估

Epic #5 · 时间盒 1–2 天 · 不建设生产管线 · 2026-06-24

## 结论(建议)

- **采用 Himawari-9(AWS Open Data)为主源**:零授权、可匿名自动下载、10 分钟全盘、
  存档回溯到 2015,对**上海 / 华东华中覆盖极佳**。当前产品(及诊断重点上海)首选。
- **FY-4B(NSMC)为备用 / 西部补充**:卫星位于 **105°E**,对**全中国(含西部)覆盖更均匀**,
  但需 NSMC 免费注册(自动化前须先确认可脚本化的 token/API 路径)。
- **不放弃任何一个**:Himawari 立即可用;FY-4B 待确认免授权自动化路径后接入西部。

两者都提供我们需要的变量:**红外窗区亮温**(云顶,#15)与**可见光/近红外**(云边界与移动,#16)。

## 一、官方数据入口、授权、变量

### Himawari-9(JMA;NOAA 在 AWS 上免费分发)
- 入口:AWS Open Data 注册表 `noaa-himawari9`(us-east-1),**匿名 / 无需授权**(非 RequesterPays)。
  官方 Open Data 接口(S3),非网页抓取。
- 仪器 AHI:16 通道(0.46–13.3 µm)。与我们相关:**B13 ≈10.4 µm**(IR 窗,云顶亮温)、
  B07 ≈3.9 µm、可见 **B03 ≈0.64 µm**、近红外 B05/B06。
- 格式:HSD 二进制 `HS_H09_YYYYMMDD_HHMM_Bxx_FLDK_Rrr_Sssnn.DAT.bz2`,全盘每波段分 **10 段(S01–S10)**。
  读取:`satpy` 的 `ahi_hsd` reader(本仓库当前未装 satpy)。
- 子卫星点 140.7°E。
- 授权/署名:NOAA/JMA 要求署名,不得暗示背书;修改数据不得声称为原始数据。

### FY-4B(CMA / NSMC)
- 入口:NSMC 风云卫星数据中心 `https://satellite.nsmc.org.cn` / `http://data.nsmc.org.cn`,
  **免费但需注册账号**;通过门户 / 订单 / DCPC 服务获取(GTS 也分发部分产品)。
- 仪器 AGRI:15 通道(0.45–13.6 µm),含 **IR 窗 ≈10.8 µm**(云顶)与可见光(云边界)。
- 格式:HDF5(AGRI L1)。读取:`satpy` 的 `agri_l1` / `agri_fy4b_l1` reader。
- 子卫星点 **105°E**(2024-02 由 133°E 西移,接替 FY-4A)。

## 二、覆盖 / 频率 / 延迟 / 下载量 对比

| 维度 | Himawari-9 (AWS) | FY-4B (NSMC) |
|---|---|---|
| 子卫星点 | 140.7°E | 105°E |
| 华东(~120°E,上海) | 极佳(视角小) | 佳 |
| 华中(~105°E) | 良(视角中) | **极佳(近星下点)** |
| 华西(~75–90°E) | 视角大、质量降级但在全盘内 | **良(覆盖更均匀)** |
| 全盘频率 | **10 min** | 15 min(+ 每日 165 次中国区域扫描) |
| 授权 | **无(匿名 S3)** | 免费注册 |
| 延迟 | 近实时(分钟级,AWS) | 近实时,但注册/订单环节有摩擦 |
| 存档 | **2015 至今** | 视产品而定 |
| 单时次下载量 | 每波段 10 段 × ~3–5MB(压缩);单 IR 波段全盘 ~40MB(解压);裁中国区可大幅减小 | HDF5 全盘单文件量级相当;中国区域产品更小 |
| 自动化难度 | **低(无授权,脚本直取)** | 中(需账号 + 确认可脚本化接口) |

## 三、上海日落样例 + 可读取验证(已实测)

- 上海(31.23°N,121.47°E)日落约 19:00 CST = **11:00 UTC**。
- 匿名列举确认存在:
  `s3://noaa-himawari9/AHI-L1b-FLDK/2026/06/22/1100/HS_H09_20260622_1100_B13_FLDK_R20_S0510.DAT.bz2`
- 匿名 `curl` 下载该 IR 段(3.2MB 压缩 → 6.05MB 解压),解析 HSD 基本信息块:
  `block# = 1`,卫星名字段 = **"Himawari-9"** → 文件结构有效、可读。
- 即:Himawari-9 **可零授权、确定性地自动下载并解析**到上海日落时刻的红外数据。
- FY-4B 同时次样例未实测(需先注册账号;留待采纳决定后做)。

## 四、对下游的意义 / 下一步

- #15 云顶订正:用 B13/AGRI IR 窗亮温反演云顶温度 → 经温度廓线换算云顶高度,订正 GFS 诊断云顶。
- #16 云边界融合:用可见光 + IR 的连续帧做云边界与 1–2h 移动趋势临近订正。
- 接入前置:把 `satpy`(+ 对应 reader 依赖)加入 dev/可选依赖;实现"按时刻匿名取 Himawari 全盘 →
  裁中国 bbox → 重投影到我们的 0.25° 网格"的读取层(对标现有 GFS 适配器风格)。
- FY-4B:先用注册账号验证一条可脚本化(token/REST)的免授权下载路径,再决定西部补充。

## 五、限制 / 风险

- HSD 解码依赖 `satpy`(当前未装);全盘体积较大,需按段/按区裁剪控制下载量。
- Himawari 西部中国视角大,边缘像元几何/辐射质量下降。
- FY-4B 自动化取决于 NSMC 接口是否可无人值守脚本化(本 spike 未验证)。

## 来源

- AWS Open Data — JMA Himawari-8/9:https://registry.opendata.aws/noaa-himawari/
- open-data-registry noaa-himawari.yaml:https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-himawari.yaml
- NSMC 风云卫星数据中心:https://satellite.nsmc.org.cn / http://data.nsmc.org.cn
- FY-4 — eoPortal:https://www.eoportal.org/satellite-missions/fy-4
- WMO OSCAR FY-4B(105°E):https://space.oscar.wmo.int/satellites/view/fy_4b
- FY-4B 接替 FY-4A、西移 105°E:https://english.www.gov.cn/news/202403/06/content_WS65e85145c6d0868f4e8e4c37.html
- satpy AGRI FY-4B reader(Geo2Grid 文档):https://www.ssec.wisc.edu/software/geo2grid/readers/agri_fy4b_l1.html
