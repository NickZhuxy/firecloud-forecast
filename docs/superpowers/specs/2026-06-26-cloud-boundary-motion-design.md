# 融合卫星云边界与移动趋势进行 1–2 小时订正 — 设计 (#16)

Parent epic: #5 — 引入卫星临近订正
Branch: `codex/16-cloud-boundary-motion`
依据 #15:复用 `predictor/satellite.py` 的 `BrightnessTempField`(Himawari B13 IR 窗,
0.25° 网格)作为连续帧输入。

## 目标

日落前 1–2 小时,用**连续**卫星图像估计云边界的移动矢量,对模式云场做**有限幅度**的
位置/概率订正;对快速发展对流与普通层云用不同置信度;卫星缺测/帧不足时安全退回纯模式。

## 验收标准与落点

| AC | 落点 |
|---|---|
| 1 从连续图像提取云边界与位移矢量 | `cloud_mask`(IR 窗阈值取冷云)+ `estimate_motion`(对相邻帧云掩膜做有界整数位移的归一化互相关,峰值→像素位移→deg/hr) |
| 2 对模式云场做有限幅度位置/概率订正 | `nowcast_correction`:位移按 `max_displacement_deg` 截断,平流模式场,再按置信度做线性混合(有限幅度) |
| 3 对流 vs 层云不同置信度 | `estimate_motion` 的 regime:相邻帧冷云区平均降温超过 `convective_bt_drop_k` → `"convective"`(纯平流不可靠)→ 低置信;否则 `"advective"` → 高置信 |
| 4 输出原始模式/观测订正量/最终结果 | `NowcastCorrection`:`model_field`、`displacement_deg`+`regime`+`confidence`、`corrected_field` |
| 5 帧不足不强行外推 | `estimate_motion` < 2 帧或帧间隔越界 → regime `"none"`、置信 0;`nowcast_correction` 据此保留模式场(`source="model"`) |

## 关键约束

- **纯算法、无 I/O**:`cloud_motion.py` 只接收 `BrightnessTempField` 帧与一个 2-D 模式云场
  (概率/云量,带 lats/lons),所有下载/解码仍在 `satellite.py`(`Himawari9Source` 可拉多
  时次帧)。下游可在无 satpy 环境只跑算法与回退。
- **同网格**:互相关要求两帧 lats/lons 一致(都是 0.25° 中国网格)。
- **有界**:位移搜索范围有界、最终位移按 `max_displacement_deg` 截断 —— 临近订正只做小幅
  纠偏,不做大范围外推。
- **被动卫星不给云底**(epic #5 边界):本故事只订正云边界水平位置与移动,不碰云底。

## 模块与数据模型

### `predictor/cloud_motion.py`(新)

```python
@dataclass(frozen=True)
class CloudMotionConfig:
    cloud_bt_threshold_k: float = 273.0   # 低于此亮温记为云
    min_frame_gap_min: float = 5.0
    max_frame_gap_min: float = 40.0       # 帧间隔越界 → 运动不可靠
    max_search_px: int = 6                # 互相关搜索半径(像素)
    max_displacement_deg: float = 2.0     # 订正位移上限(有限幅度)
    max_lead_hr: float = 2.0
    convective_bt_drop_k: float = 8.0     # 相邻帧平均降温 → 发展性对流
    advective_confidence: float = 0.8
    convective_confidence: float = 0.4
    min_overlap_frac: float = 0.1         # 互相关重叠太低 → 置信压低

@dataclass
class MotionVector:
    du_deg_per_hr: float; dv_deg_per_hr: float   # 东向 / 北向 deg/hr
    speed_deg_per_hr: float
    regime: str            # "advective" | "convective" | "none"
    confidence: float      # 0–1
    reason: str; n_frames: int

@dataclass
class NowcastCorrection:
    model_field: np.ndarray; corrected_field: np.ndarray
    displacement_deg: tuple[float, float]   # 实际施加(已截断)
    confidence: float; regime: str
    source: str            # "satellite" | "model"
    reason: str

def cloud_mask(frame, config=...) -> np.ndarray
def estimate_motion(frames: list[BrightnessTempField], config=...) -> MotionVector
def nowcast_correction(model_field, model_lats, model_lons, motion, lead_time_hr, config=...) -> NowcastCorrection
```

互相关:对两帧云掩膜在 `[-max_search_px, max_search_px]²` 内找使重叠 `Σ roll(m0,s)·m1`
最大的整数位移 `s=(dy,dx)`;`Δlon=dx·dlon`、`Δlat=dy·dlat`,除以帧间小时数得 deg/hr。

订正:`disp = (du,dv)·lead`,模长截断到 `max_displacement_deg`;把模式场按 `disp` 平流
(网格像素 roll/插值),`corrected = model + confidence·(advected − model)`(置信越低改动越小,
且结果保持在模式场原值域内)。

## 测试(离线 + 形变/性质)

- `estimate_motion`:植入云团按已知像素平移 → du/dv 方向与量级正确;同帧 → 近零运动、高
  置信;单帧/间隔越界 → regime `"none"`、置信 0;相邻帧强降温 → `"convective"` 且置信低于
  `"advective"`。
- `nowcast_correction`:零运动 → `corrected==model`;超大运动被 `max_displacement_deg` 截断;
  regime none → 保留模式场、`source=="model"`。
- 形变/性质:lead 越长位移越大(单调,直到上限);置信越高 `corrected` 越接近平流场;模式场
  ∈[0,1] 时 `corrected` 仍 ∈[0,1];对流 regime 置信 < 层云 regime(同位移)。

## 限制 / 后续

- 仅 IR 窗单波段做掩膜;可见光多波段融合留待后续。
- 整数像素互相关精度到一个 0.25° 格;亚像素/光流可后续增强。
- 缺测/单源退回模式;FY-4B 西部补充见 epic #5 后续。
