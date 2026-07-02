# Stage C:卫星临近订正接入全国/局部产品 — 设计 (#84)

Parent epic: #54。前置:#16 交付的纯算法 `predictor/cloud_motion.py`(零生产消费者)、
#15 的 `predictor/satellite.py`(Himawari-9 B13 亮温帧,0.25° 网格)、#59 两段式全国场
(PR #81/#83 已合入 main)。用户已拍板:**上图替换 + metadata 双存统计;默认开、
`--no-satellite` 关;全国 + 局部产品都接**。

## 目标与物理边界

日落(或日出)前 ≤2 小时生成产品时,用最近两帧卫星图估计云边界移动,把概率场向平流后的
位置做**有界、按置信度加权**的微调。这是临近预报(nowcast)——只在事件临近时物理上有效:

- **逐格新鲜度门**:格子有资格 ⟺ `0 ≤ 事件时刻 − now ≤ max_lead_hr(2.0)`。提前半天跑图
  ⇒ 零资格 ⇒ **连卫星帧都不拉**,产品与 Stage C 之前逐位一致。
- 订正幅度受 `CloudMotionConfig.max_displacement_deg`(2.0°)与置信度(平流 0.8 / 对流 0.4)
  双重约束——是"纠偏",不是外推(#16 既定语义,本 story 不改动算法模块任何一行)。

## 架构:一个编排单元,两个产品共用

```
generate_product / generate_local_product
        │  构建 field(现状不变)
        ▼
predictor/nowcast.py::apply_nowcast(probability, lats, lons, event_times,
                                    satellite_source, *, now, config)
        │  ① 新鲜度门(零资格→原样返回,不触网)
        │  ② fetch 2 帧 B13(nearest_slot(now) 及其前一 10-min 槽)
        │  ③ estimate_motion → MotionVector(regime/confidence)
        │  ④ 按日落整点分带调 nowcast_correction(带内 lead=该整点−now,≤3 次)
        │     订正值只写回 带∩资格 格子;边缘防回卷(见下)
        ▼
NowcastStageResult → 产品层 dataclasses.replace 换入订正场渲染 + metadata "nowcast" 块
```

### `predictor/nowcast.py`(新,编排;唯一 IO 是注入的 satellite_source)

```python
@dataclass(frozen=True)
class NowcastStageConfig:
    enabled: bool = True
    max_lead_hr: float = 2.0                 # 与 CloudMotionConfig.max_lead_hr 一致
    frame_gap_min: int = 10                  # Himawari 全圆盘节奏
    motion: CloudMotionConfig = DEFAULT_CLOUD_MOTION_CONFIG

@dataclass
class NowcastStageResult:
    corrected_probability: np.ndarray        # 全网格;未订正处 == 输入
    corrected_mask: np.ndarray               # bool,实际被微调的格子
    motion: MotionVector | None
    applied: bool
    source: str                              # "satellite" | "model"
    reason: str
    lead_hr_range: tuple[float, float] | None  # 资格格子的 lead 区间
```

关键行为:

- **资格判定**:`event_times`(ny,nx 的 datetime64 网格,调用方用与管线相同的纯函数
  `sunset_utc_grid` 重算)对 `now` 求 lead;无资格 → `applied=False,
  reason="no cells within nowcast window"`,**不构造 satellite_source 调用**。
- **取帧**:`satellite_source.fetch_brightness_temp(bbox, valid_time=slot)`,两槽 =
  `nearest_slot(now)` 与 `slot − frame_gap_min`。`SatelliteUnavailable` / `ImportError`
  (satpy 未装)/ 任意异常 → `applied=False` 带原因穿透,**产品不失败**。
- **分带订正**:资格格子按其所属日落整点(与 refine 相同的 `selected_time` 语义)成带;
  每带一次 `nowcast_correction(field, lats, lons, motion, lead=band_hour − now)`,
  仅 `带∩资格` 格子取订正值。regime="none" 或 confidence≤0 时模块自身已回退。
- **网格无关性**:运动矢量来自卫星 0.25° 网格(deg/hr),订正在**模式自身网格**上平流
  (`nowcast_correction` 用模式 lats/lons 折算像素位移)——local 的 0.1° 网格天然兼容。
  模块内 `dlat` 注释假设降序,数学上对升序自适应;**用测试钉死升序纬度的方向正确性**。
- **边缘防回卷**:`np.roll` 会把对侧边缘绕入。编排层按实际应用的 `displacement_deg`
  折算行列偏移,把回卷进来的条带(≤8 格 @2°)还原为模式值并从 `corrected_mask` 剔除。

### 产品接线

- `generate_product(..., satellite: bool = True)`:field 构建后
  `apply_nowcast(field.probability, field.lats, field.lons, sunsets, sat_source, now=datetime.now(utc))`;
  `applied` → `replace(field, probability=result.corrected_probability)` 进渲染,并在
  `field.physics["nowcast"]` 记块(见 metadata)。`satellite=False` 或 apply 未生效 → 现状。
  卫星源默认 `Himawari9Source()`,可注入(测试用假源)。
- `generate_local_product` 同构接线(local 网格 + local 事件时刻)。
- CLI:`--no-satellite` → 两类产品都传 `satellite=False`。帮助文案注明触发条件
  (事件前 ≤2h 生成时才拉帧)。

## 呈现与 metadata(上图替换 + 双存统计)

- **PNG**:订正格子直接用订正值渲染;caption 追加
  `· N cells satellite-nudged ({regime}, conf {confidence:.1f})`。不加新标记点(保持图面
  干净;refine 点已占用视觉通道)。
- **metadata**:沿用"存统计不存网格"惯例,新增顶层 `"nowcast"` 块:
  `applied / source / reason / regime / confidence / displacement_deg / cells_corrected /
  mean_abs_delta / lead_hr_range / physics_probability_range`(订正前 range;订正后即顶层
  `probability_range`)。未生效时块仍在(`applied=false` + reason),可观测。

## 失败矩阵(全部 → applied=False,产品与 Stage C 前逐位一致)

| 情形 | 挡在哪 |
|---|---|
| 零资格格子(提前跑图) | 门①,不触网 |
| 卫星缺测 / S3 不可达 | 取帧 try/except → reason |
| satpy/pyresample 未装 | 同上(ImportError) |
| 帧不足 2 / 帧间隔越界 | `estimate_motion` → regime="none" |
| 快速发展对流 | regime="convective" → 低置信(0.4)仍生效,幅度自然减半 |
| regime="none" / conf≤0 | `nowcast_correction` 自身回退 source="model" |

## 测试策略

- **离线合成为主**(默认套件):假卫星源返回构造帧(已知整数平移的云掩膜)→ 断言订正
  方向与幅度、`corrected_mask` 范围、分带 lead 正确;升序纬度方向钉死;边缘防回卷;
  每条失败矩阵路径;**两个零回归保护测试**(窗口外产品逐位不变 / `satellite=False` 逐位
  不变)。产品层用 monkeypatch 假源,断言 replace 与 metadata 块。
- **integration 档**:真实 Himawari 取帧 + satpy 解码(依赖缺失 skip),只验证端到端
  可跑与 metadata 块成形,不断言数值。
- 覆盖率按测试清单论证(`pytest --cov` 环境不可用)。

## 不做(YAGNI)

- 不改 `cloud_motion.py` 任何算法(阈值/置信度沿用 #16)。
- 不做多于 2 帧的轨迹拟合、不做逐格独立 lead 的连续平流(分带近似,带宽 1h)。
- 不动云底/垂直结构(被动卫星边界,epic #5 既定)。
- sunrise 自动获益(事件时刻网格本就按 solar_event 生成),不单独设计。
