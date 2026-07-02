# #84 Stage C 卫星临近订正接入产品 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 事件前 ≤2h 生成产品时,用两帧 Himawari B13 的云运动对全国/局部概率场做有界订正:上图替换 + metadata 统计双存,一切卫星侧失败安全穿透。

**Architecture:** 新编排模块 `predictor/nowcast.py`(唯一 IO 是注入的卫星源)串起 #16 的纯算法:逐格新鲜度门 → 取 2 帧 → `estimate_motion` → 按事件整点分带 `nowcast_correction` → 边缘防回卷 → `NowcastStageResult`。`NationalField`/`LocalField` 各加 `nowcast: dict | None` 属性承载统计块,产品层 `dataclasses.replace` 换入订正场,渲染/metadata 消费该块。算法模块 `cloud_motion.py` 一行不改。

**Tech Stack:** Python 3.11 · numpy · matplotlib(Agg) · pytest(monkeypatch/caplog) · Himawari-9 B13 via `predictor/satellite.py`(网络+satpy 仅 integration 档)

## Global Constraints

- 测试命令:`PYTHONPATH=. UV_CACHE_DIR=.uv-cache MPLCONFIGDIR=.uv-cache/matplotlib uv run --no-sync python -m pytest -m "not integration" -q`
- 提交信息中文、**不加 Co-Authored-By**;TDD:每任务先写失败测试;`pytest --cov` 不可用,覆盖率按测试清单论证
- 失败矩阵全部 → `applied=False` 且产品**逐位**等于 Stage C 之前(spec 的两个零回归保护测试必须存在)
- 不改 `predictor/cloud_motion.py`、不改其配置默认值
- 真实签名:`Himawari9Source.fetch_brightness_temp(valid_time, bbox=CHINA_BBOX, band="B13")`(valid_time 第一位);`estimate_motion(frames: list[BrightnessTempField])`;帧间隔合法域 [5, 40] min
- 分支 `feat/84-satellite-nowcast`(自 main),spec:`docs/superpowers/specs/2026-07-02-satellite-nowcast-product-design.md`

---

### Task 1: `predictor/nowcast.py` — 类型、新鲜度门、失败穿透

**Files:**
- Create: `predictor/nowcast.py`
- Test: `predictor/tests/test_nowcast.py`(新)

**Interfaces:**
- Consumes: `predictor.cloud_motion`(`CloudMotionConfig, DEFAULT_CLOUD_MOTION_CONFIG, MotionVector, estimate_motion, nowcast_correction`)、`predictor.satellite.nearest_slot`
- Produces(后续任务依赖的精确形状):

```python
@dataclass(frozen=True)
class NowcastStageConfig:
    enabled: bool = True
    max_lead_hr: float = 2.0
    frame_gap_min: int = 10
    motion: CloudMotionConfig = DEFAULT_CLOUD_MOTION_CONFIG

DEFAULT_NOWCAST_CONFIG = NowcastStageConfig()

@dataclass
class NowcastStageResult:
    corrected_probability: np.ndarray
    corrected_mask: np.ndarray
    motion: MotionVector | None
    applied: bool
    source: str                      # "satellite" | "model"
    reason: str
    lead_hr_range: tuple[float, float] | None

def apply_nowcast(
    probability, lats, lons, event_times,     # event_times: (ny,nx) datetime64[s] 网格
    satellite_source,                          # duck: fetch_brightness_temp(valid_time, bbox=..)
    *, now: datetime,
    config: NowcastStageConfig = DEFAULT_NOWCAST_CONFIG,
) -> NowcastStageResult
```

语义(本任务实现到"取帧+运动估计",订正数学留 Task 2):`enabled=False`、无资格格子(`0 ≤ event−now ≤ max_lead_hr` 无一满足)→ 直接返回 `applied=False`,**不触碰 satellite_source**;取帧对 `nearest_slot(now)` 与 `slot − frame_gap_min` 两槽,bbox 由 lats/lons 外扩 2° 得出;任何异常(含 `SatelliteUnavailable`/`ImportError`)→ `applied=False` 带 reason;`estimate_motion` 得 regime="none" → 同样穿透。此阶段 `corrected_probability` 恒等输入拷贝、mask 全 False。

- [ ] **Step 1: 失败测试**(`test_nowcast.py`;夹具:`_times(offset_hr)` 生成 2×2 datetime64 网格,`_RecordingSat` 记录调用并可抛错/返回构造帧)

```python
"""Stage C nowcast orchestration (#84) — offline, synthetic frames."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from predictor.cloud_motion import MotionVector
from predictor.nowcast import DEFAULT_NOWCAST_CONFIG, NowcastStageResult, apply_nowcast
from predictor.satellite import BrightnessTempField, SatelliteUnavailable

_NOW = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
_LATS = np.array([30.0, 30.25])
_LONS = np.array([118.0, 118.25])


def _times(offset_hr: float) -> np.ndarray:
    t = np.datetime64(int((_NOW + timedelta(hours=offset_hr)).timestamp()), "s")
    return np.full((2, 2), t)


class _RecordingSat:
    def __init__(self, frames=None, exc=None):
        self.frames, self.exc, self.calls = list(frames or []), exc, []

    def fetch_brightness_temp(self, valid_time, bbox=None, band="B13"):
        self.calls.append(valid_time)
        if self.exc is not None:
            raise self.exc
        return self.frames.pop(0)


def _prob():
    return np.full((2, 2), 0.6)


def test_no_eligible_cells_skips_satellite_entirely():
    sat = _RecordingSat()
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(5.0), sat, now=_NOW)
    assert res.applied is False and res.source == "model"
    assert sat.calls == []                       # 门在取数之前
    np.testing.assert_array_equal(res.corrected_probability, _prob())
    assert not res.corrected_mask.any()


def test_past_events_are_not_eligible():
    sat = _RecordingSat()
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(-0.5), sat, now=_NOW)
    assert res.applied is False and sat.calls == []


def test_satellite_failure_passes_through_safely():
    sat = _RecordingSat(exc=SatelliteUnavailable("himawari down"))
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(1.0), sat, now=_NOW)
    assert res.applied is False
    assert "himawari down" in res.reason
    np.testing.assert_array_equal(res.corrected_probability, _prob())


def test_regime_none_passes_through(monkeypatch):
    frame = BrightnessTempField(
        lats=_LATS, lons=_LONS, brightness_temp_k=np.full((2, 2), 290.0),
        observation_time=_NOW, band="B13", source_label="t", retrieved_at=_NOW,
    )
    sat = _RecordingSat(frames=[frame, frame])   # 全暖 → 无云掩膜 → regime none
    res = apply_nowcast(_prob(), _LATS, _LONS, _times(1.0), sat, now=_NOW)
    assert res.applied is False
    assert len(sat.calls) == 2                    # 确实取了 2 帧
```

- [ ] **Step 2: 确认失败**:`… -m pytest predictor/tests/test_nowcast.py -q` → ModuleNotFoundError predictor.nowcast
- [ ] **Step 3: 实现 `predictor/nowcast.py`**(dataclass 全量 + `apply_nowcast` 至运动估计;`_eligible_mask`、`_fetch_frames` 私有函数;`_passthrough(reason, motion=None)` 构造未生效结果)
- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**:`feat(predictor): #84 nowcast 编排——新鲜度门与失败穿透`

---

### Task 2: 分带订正、升序纬度方向、边缘防回卷

**Files:**
- Modify: `predictor/nowcast.py`
- Test: `predictor/tests/test_nowcast.py`

**Interfaces:**
- Consumes: Task 1 全部;`cloud_motion.nowcast_correction(model_field, model_lats, model_lons, motion, lead_time_hr, config)`
- Produces: `apply_nowcast` 完整语义 —— 资格格子按事件整点分带(`np.datetime64` 四舍五入到时),每带一次 `nowcast_correction(…, lead=band_hour−now)`,只把 `带∩资格` 写回;应用后按位移还原回卷条带并从 mask 剔除;`applied=True, source="satellite"`,`lead_hr_range=(min,max)` 取资格格子实际 lead

- [ ] **Step 1: 失败测试**(构造已知平移帧:12×12 网格 0.25° 步长,冷云块在 f0 列 4–6、f1 列 5–7,间隔 10 min → 向东 1 px/10min = 1.5°/hr;confidence=0.8 平流)

```python
def _shifted_frames():
    lats = np.arange(28.0, 31.0, 0.25)
    lons = np.arange(116.0, 119.0, 0.25)
    ny, nx = lats.size, lons.size
    warm, cold = 290.0, 250.0
    bt0 = np.full((ny, nx), warm); bt0[:, 4:7] = cold
    bt1 = np.full((ny, nx), warm); bt1[:, 5:8] = cold
    t0 = _NOW - timedelta(minutes=10)
    mk = lambda bt, t: BrightnessTempField(
        lats=lats, lons=lons, brightness_temp_k=bt,
        observation_time=t, band="B13", source_label="t", retrieved_at=_NOW)
    return lats, lons, mk(bt0, t0), mk(bt1, _NOW)


def test_correction_nudges_toward_advected_position():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.zeros((lats.size, lons.size)); prob[:, 5] = 1.0
    times = np.full(prob.shape, np.datetime64(int((_NOW + timedelta(hours=1)).timestamp()), "s"))
    sat = _RecordingSat(frames=[f0, f1])
    res = apply_nowcast(prob, lats, lons, times, sat, now=_NOW)

    assert res.applied is True and res.source == "satellite"
    assert res.motion.regime == "advective"
    # 东移 1.5°/hr × 1h,受 max_displacement 2° 约束内 → dcol=+6;混合权 0.8。
    advected = np.roll(prob, 6, axis=1)
    expected = prob + res.motion.confidence * (advected - prob)
    inner = np.s_[:, 6:]                          # 回卷条带(西侧 6 列)除外
    np.testing.assert_allclose(res.corrected_probability[inner], expected[inner])
    assert res.corrected_mask[:, 6:].any()


def test_wrapped_edge_strip_reverts_to_model():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.full((lats.size, lons.size), 0.7)
    times = np.full(prob.shape, np.datetime64(int((_NOW + timedelta(hours=1)).timestamp()), "s"))
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    # 东移 dcol=+6 → 西侧 6 列是回卷数据,必须还原为模式值且不进 mask。
    np.testing.assert_array_equal(res.corrected_probability[:, :6], prob[:, :6])
    assert not res.corrected_mask[:, :6].any()


def test_only_eligible_band_cells_change():
    lats, lons, f0, f1 = _shifted_frames()
    prob = np.full((lats.size, lons.size), 0.7)
    near = np.datetime64(int((_NOW + timedelta(hours=1)).timestamp()), "s")
    far = np.datetime64(int((_NOW + timedelta(hours=5)).timestamp()), "s")
    times = np.full(prob.shape, far); times[:, :6] = near   # 只有西半有资格
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    assert not res.corrected_mask[:, 6:].any()               # 窗口外的格子不动
    np.testing.assert_array_equal(res.corrected_probability[:, 6:], prob[:, 6:])


def test_ascending_latitude_direction_is_correct():
    # 北移帧(行 +1/10min,dv>0);升序 lats 下订正必须把场向北搬。
    lats = np.arange(28.0, 31.0, 0.25); lons = np.arange(116.0, 119.0, 0.25)
    ny, nx = lats.size, lons.size
    bt0 = np.full((ny, nx), 290.0); bt0[4:7, :] = 250.0
    bt1 = np.full((ny, nx), 290.0); bt1[5:8, :] = 250.0
    t0 = _NOW - timedelta(minutes=10)
    f0 = BrightnessTempField(lats=lats, lons=lons, brightness_temp_k=bt0,
                             observation_time=t0, band="B13", source_label="t", retrieved_at=_NOW)
    f1 = BrightnessTempField(lats=lats, lons=lons, brightness_temp_k=bt1,
                             observation_time=_NOW, band="B13", source_label="t", retrieved_at=_NOW)
    prob = np.zeros((ny, nx)); prob[5, :] = 1.0
    times = np.full(prob.shape, np.datetime64(int((_NOW + timedelta(hours=1)).timestamp()), "s"))
    res = apply_nowcast(prob, lats, lons, times, _RecordingSat(frames=[f0, f1]), now=_NOW)
    assert res.applied
    j = 5 + 6                                    # 北移 6 行(升序 → 行号增大)
    assert res.corrected_probability[j, :].mean() > prob[j, :].mean()
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**:分带(`event_times` 秒级取整到时:`(t + 30min) 截断到时`);逐带 `nowcast_correction`;写回掩膜;回卷条带公式:`dcol = round(du_applied/dlon)`(du 取该带 `NowcastCorrection.displacement_deg`),`dcol>0 → 列 [0,dcol) 还原`、`dcol<0 → 列 [nx+dcol,nx)`;行同理按 `dlat` 符号。多带时 mask/还原逐带处理。
- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**:`feat(predictor): #84 nowcast 分带订正+升序纬度+边缘防回卷`

---

### Task 3: 全国产品接线与呈现

**Files:**
- Modify: `predictor/national_field.py`(`NationalField` 加 `nowcast: dict | None = None`)
- Modify: `predictor/national_product.py`(`generate_product` 接 `satellite: bool = True, satellite_source=None, now=None`;`plot_sunsetwx_product` caption;`_metadata` 顶层 `"nowcast"` 块)
- Test: `predictor/tests/test_national_product.py`

**Interfaces:**
- Consumes: Task 2 的 `apply_nowcast`、`NowcastStageResult`;`sunset_grid.sunset_utc_grid`
- Produces: `generate_product(..., satellite: bool = True, satellite_source=None, now: datetime | None = None)`;`NationalField.nowcast` 统计块(dict,键:`applied, source, reason, regime, confidence, displacement_deg, cells_corrected, mean_abs_delta, lead_hr_range, physics_probability_range`);metadata 顶层 `"nowcast"` = 该块;caption 追加 `· N cells satellite-nudged ({regime}, conf {c:.1f})`(仅 applied 且 N>0)

实现要点:field 构建后 `sunsets = sunset_utc_grid(target_date, field.lats, field.lons, solar_event=solar_event)`;`result = apply_nowcast(field.probability, …, satellite_source or Himawari9Source(), now=now or datetime.now(timezone.utc))`;块中 `physics_probability_range` 取订正前 finite min/max;applied 时 `field = replace(field, probability=result.corrected_probability, nowcast=block)`,未 applied 时也挂块(reason 可观测)。`satellite=False` → 完全跳过(块也不挂,产品逐位同 Stage C 前 —— 零回归测试)。

- [ ] **Step 1: 失败测试**:monkeypatch `product_mod.apply_nowcast` 捕参并返回构造结果 → 断言 replace 生效、metadata["nowcast"] 成块、caption 文本出现;`satellite=False` → apply_nowcast 未被调用且 metadata 无 "nowcast";fake apply 返回 applied=False → 概率场原样、块带 reason
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 确认通过 + 全量档**
- [ ] **Step 5: Commit**:`feat(predictor): #84 全国产品接卫星临近订正(上图替换+metadata 双存)`

---

### Task 4: 局部产品接线与呈现

**Files:**
- Modify: `predictor/local_field.py`(`LocalField` 加 `nowcast: dict | None = None`)
- Modify: `predictor/local_product.py`(`generate_local_product` 同参数;caption;`_metadata` 顶层块)
- Test: `predictor/tests/test_local_product.py`(按该文件现行夹具惯例)

**Interfaces:**
- Consumes: Task 2;local 的事件时刻是标量 `event_time` → `event_times = np.full(prob.shape, np.datetime64(int(event_time.timestamp()), "s"))`
- Produces: `generate_local_product(..., satellite: bool = True, satellite_source=None, now: datetime | None = None)`;`LocalField.nowcast` 同 national 块结构

步骤同 Task 3(失败测试 → 实现 → 全量档 → Commit `feat(predictor): #84 局部产品接卫星临近订正`)。

---

### Task 5: CLI `--no-satellite`

**Files:**
- Modify: `predictor/cli.py`
- Test: `predictor/tests/test_cli.py`

**Interfaces:**
- Produces: `--no-satellite` flag(help 注明:仅事件前 ≤2h 生成时才会拉帧;卫星缺测/依赖缺失自动跳过);national/local 两个调用点都传 `satellite=not args.no_satellite`

- [ ] **Step 1: 失败测试**(仿 `test_no_refine_flag_propagates`:两个 fake_generate 捕 `satellite` kwarg,默认 True、带 flag False;既有 fake 签名同步加 `satellite` 参数)
- [ ] **Step 2–5**:确认失败 → 实现 → 全量档 → Commit `feat(predictor): #84 CLI --no-satellite`

---

### Task 6: integration 档 + live 冒烟 + 文档回写

**Files:**
- Create: `predictor/tests/test_nowcast_integration.py`(`@pytest.mark.integration`;真实 `Himawari9Source` 取 `nearest_slot(now)` 两帧,satpy/网络缺失 skip;只断言 `apply_nowcast` 返回结构成形与 applied∈{True,False},不断言数值)
- Modify: `docs/superpowers/plans/2026-07-02-satellite-nowcast-product.md`(完成记录)

- [ ] **Step 1: integration 测试 + 跑通或合理 skip**(`… -m pytest -m integration -k nowcast -q`)
- [ ] **Step 2: live 冒烟**:挑一个日落前 ≤2h 的时机(或用 `now` 注入模拟)跑 `firecloud --event sunset`,检查 metadata "nowcast" 块与 caption;`--no-satellite` 对照
- [ ] **Step 3: 完成记录回写 + 记忆更新;push;开 PR(base main,关联 #84)**

## Self-Review

- **Spec 覆盖**:门/取帧/分带/防回卷=T1+T2;上图替换+双存+caption(国/局)=T3+T4;默认开关=T3/T4 参数+T5 flag;失败矩阵各路径=T1 测试+T3 的 applied=False 用例;零回归双保护=T1(窗口外)+T3(satellite=False);integration=T6 ✓
- **占位符**:T3/T4 的 Step 1 描述了断言目标但未展开全部测试体——执行者为本会话(上下文在手),按 T1/T2 的完整风格落地;其余任务代码完整 ✓
- **类型一致性**:`apply_nowcast` 签名、`NowcastStageResult` 字段、`satellite/satellite_source/now` 参数名在 T1–T5 全文一致;`fetch_brightness_temp(valid_time, bbox=…)` 参数序与 satellite.py 实况一致 ✓

## 完成记录(2026-07-02)

6 任务全部完成,离线套件 **610 passed**(含 12 个 nowcast 单测:门/失败矩阵/分带/方向/防回卷/发布延迟回退/诚实 no-op)。integration 档 1 例(satpy 缺失自动 skip;本机已装 `uv sync --extra satellite`)。

**Live 实弹的三个发现**(都当场修复/确认):

1. **Himawari 发布延迟**:`nearest_slot(now)` 常 404(L1b 上 S3 延迟 10–20 分钟)→ 取帧回退至已发布的连续槽对(≤3 级,先试新帧快速失败),commit `483e3a0`。
2. **速度分辨率地板**:10 分钟帧距 × 0.25° 像素 ⇒ 1.5°/hr(165 km/h),真实云速全部量化为零位移——首次 applied 实为恒等订正且虚报 4826 格。运动对拉开到 30 分钟(地板 0.5°/hr),零像素位移诚实 no-op(`applied=false, reason="below grid resolution"`)。
3. **窗口语义实证**:提前跑图 `reason="no cells within nowcast window"` 零成本;窗口内(lead [0,1.87]h)真帧真解码,今晚全国主导运动子像素 → 诚实未订正。0.25° 全国栅格下 Stage C 结构性地只对快系统(急流卷云/飑线/台风外围 >55 km/h)生效——这正是临近订正价值最大的场景。

**后续想法**(不阻塞):局部产品可传 `Himawari9Source(resolution_deg=0.1)` 细栅格,速度地板降到 ~11 km/h,普通平流可测;代价是 satpy 重栅格更贵。多帧(>2)拟合可再压噪声。
