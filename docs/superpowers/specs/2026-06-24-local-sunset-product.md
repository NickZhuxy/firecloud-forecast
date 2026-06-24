# 本地 SunsetWx 成品图与 Web 层移除 — 设计（#45）

Depends on: #43 · Branch: `codex/45-local-sunset-product`

## 决策

项目当前只维护预测算法和一个权威的本地科研图产物。不再维护 Leaflet 前端、FastAPI
路由、请求触发的后台线程、在线缓存状态机、图片服务或上传逻辑。自己分析与公开分享
使用同一张 SunsetWx 风格完整 PNG；社交平台上传由用户手工完成。

## 架构

```text
GFS/缓存 → build_national_field → NationalField
                               → national_product CLI
                               → PNG + metadata.json
```

### `predictor/national_product.py`

- `MapContext` 保存中国边界、周边国界和省级线。生产环境用 Cartopy Natural Earth
  110m admin-0 面做稳定国境裁剪，并用 10m 省级几何画内部边界；测试直接注入合成
  Shapely 几何，不触发网络。
- `plot_sunsetwx_product` 是纯展示函数：只消费 `NationalField`、日期和地图几何，不抓取
  天气。白底完整科研图包含产品标题、GFS 0.25°、初始化时间、逐格日落有效时间范围、
  经纬度、行政边界、turbo 连续色阶和“暖色更优”说明。
- `save_product` 原子写入 `firecloud-cn-YYYYMMDD.png` 和同名 JSON。JSON 记录 schema、
  源模型、valid times、日落范围、算法/数据量/运行性能、概率范围与图片文件名。
- `generate_product` 才负责连接 `GFSSource`、中国 bbox、国境 mask、全国场构建和保存。
- CLI：`python -m predictor.national_product --date YYYY-MM-DD --output-dir products`。
  日期必填以保证可复现；不提供上传选项。

### 删除范围

- 删除 `app/static/index.html`、`app/server.py`、`app/overlay.py`、`app/timing.py` 及
  `app/tests/`。
- 删除 FastAPI/Uvicorn 依赖；pytest 只收集 `predictor/tests`。
- `products/` 加入 `.gitignore`；README 改为算法库 + 本地制图工作流。
- 已合并历史 spec 保留原文，作为当时架构的决策记录；当前入口文档不再宣传 Web。

## 验收标准

- [x] 仓库没有受版本控制的 `app/` Web 实现，也没有 FastAPI/Uvicorn 依赖。
- [x] 合成 `NationalField` 可离线生成包含标题、地图、色标的非透明 PNG 和完整 JSON。
- [x] CLI `--help` 可用，参数解析不触发数据下载。
- [x] 全国场生产路径复用 #43 的逐格日落、共同 GFS cycle 和国境 mask。
- [x] README 与 theory index 只描述算法和本地产品。
- [x] 离线全套通过；使用生产 Natural Earth 地图与合成全国场手动生成并目视检查成品。

## 非目标

- 自动上传、CDN、社交平台 API。
- 另一套“公众版”配色或版式。
- 真实卫星底图/云纹（留给 epic #5）。
