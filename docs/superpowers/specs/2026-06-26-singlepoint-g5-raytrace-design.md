# 单点物理拟真增强 — FA-G5：抛物线 ↔ 大气截面光线追踪 — 设计 (#57 P1 keystone)

Parent epic: #54 · Story #57「单点物理拟真增强」P1。依据 `research/theory/single-point-fidelity-audit.md` 的 FA-G5（基石项）。
权威目标模型：手册 §1.2.1-2（抛物线坐标）、§4.1.2 通用光追法、翻车清单"杂云挡光路 / 上游气溶胶"。
Branch: `codex/57-g5-raytrace`（stacked on P0 `codex/57-...`）。

## 问题（审计 FA-G5）

当前 `SunwardIlluminationGate`（`rules.py:203`）只比**标量**：`boundary_km` vs `max_penetration_km`。
它**不检查**代表阳光的抛物线沿途是否穿过**杂云**或**重气溶胶**区——而这正是手册操作法的核心
（§4.1.2："保证抛物线不穿过不透光的大气区域，比如有云的区域或者气溶胶消光严重的区域"）。
`cross_section.py` 已装配了 距离×高度 的 RH/温度场 + **每列诊断云层** `cloud_layers`，但没有任何代码在它上面追踪光线。

## 物理（手册 §1.2.1-2，已在 P0 验证同套坐标）

到达**观察者头顶云底** `h_cb` 的掠射光线，在平坦抛物坐标里是一条抛物线，顶点（与等效地表相切处）
在朝太阳方向距离 `l_v = √(2R·h_eff)` 处；以观察者为 `l=0`、朝太阳为 `+l`：

```
h_ray(l) = (l − l_v)² / (2R)        # 观察者侧 0≤l≤l_v：从 h_cb 降到 0（掠地）
l_v = √(2R · h_eff)                 # 顶点（用气溶胶等效云底 h_eff）
```

含义：光线在观察者处高 `h_cb`，朝太阳方向逐渐压低，在 `l_v` 处掠过（等效）地表。所以**离观察者较远
（接近 l_v）处的低云最能挡光**，而观察者头顶附近的高云就是画布本身、不算遮挡。这条光线扫过的
顶点位置随时间平移（=地球自转，P0 的火烧云三角同源）。

## 设计决定（请 Nick 过目，重点是 1 与 4）

1. **纯函数、消费已有 `SunwardCrossSection`**（不碰网络/IO），与 `cloud_motion.py` 同范式。
   逐列用**诊断云层** `cloud_layers[i]`（含 base/top/phase/confidence）判遮挡——比用 masked RH 网格更干净，
   且复用 P0/`illumination._layer_opacity` 的不透明度模型。**落点：新模块 `predictor/ray_path.py`**
   （`cross_section.py` 保持纯装配；`ray_path` 依赖 `cross_section` + `geometry` + `illumination`，无循环）。
2. **遮挡判据**：列 `i`（距观察者 `d_i`）处光线高度 `h_ray(d_i)`；若该列存在诊断云层 `[base,top]` 满足
   `base ≤ h_ray(d_i) ≤ top` 且 `_layer_opacity(layer) ≥ opacity_threshold`（默认 0.5）→ 该列挡光。
   气溶胶：若 `h_ray(d_i)` 低于该列等效地表高度（由列 AOD 经 P0 `equivalent_*` 反推）→ 挡光（FA-A2 接入点，
   本 PR 先留参数位、用全程 AOD 占位，**FA-A2 再做逐列积分**）。
3. **观察者头顶画布不自遮挡**：跳过 `l` 很小（如 `< 一个采样间隔`）的列，避免把画布自身判成遮挡。
4. **本 PR 范围（keystone 第一刀）**：交付**纯光追算法 + 其数据模型**，TDD 用合成 `SunwardCrossSection`：
   - `ray_height_m(distance_km, vertex_km)` — 抛物线高度；
   - `trace_ray_clearance(cross_section, observer_cloud_base_eff_m, ...) -> RayClearance`
     （`clear: bool`、首个遮挡 `blocked_at_km/height_m/layer`、扫描的列数）；
   - （可选，同 PR 若顺）`clear_vertex_interval(...)` 扫描顶点位置区间 → 接 P0 三角给"无遮挡时长"。
   **暂不改** `SunwardIlluminationGate` 的通过/不通过语义——把"截面光追"接进评分（当 detail 路径有 cross-section 时
   升级、overview 标量回退）作为**紧随的第二刀**（同 issue #57，独立小 PR），保持本 PR 聚焦、可独立审。
5. **`v`/速度**：本项不涉及时长速度模型；与 FA-G4 解耦。

## 测试（TDD：先红后绿；离线、合成 `SunwardCrossSection`）

- `ray_height_m`：顶点处 =0；观察者处 `(0−l_v)²/2R = h_eff`；对称性；远离顶点升高。
- `trace_ray_clearance`：
  - 晴空截面（无云层）→ `clear=True`；
  - 在光线**会经过的低空位置**（≈ `l_v` 附近、低高度）植入一层不透明云 → `clear=False`、`blocked_at_km` 命中该列；
  - 同样的云放在**观察者头顶高空**（画布高度、近 `l=0`）→ 不算遮挡（`clear=True`，验证决定 3）；
  - 半透明薄云（opacity < 阈值）→ 不挡（验证判据 2 的阈值）；
  - **metamorphic**：沿光路不透明云层越多/越厚，`clear` 只会从 True→False，不会反向。
- 边界：空截面/全 mask → 安全（`clear=True` 或显式 None，不崩）。
- **回归**：全量 `pytest -m "not integration"` 全绿；P0 的 geometry 测试、grid 1e-9、metamorphic 不受影响（本 PR 是纯新增模块）。

## 限制 / 后续（P1 续）

- 本 PR 不接评分；**第二刀**把 `trace_ray_clearance` 接进 `SunwardIlluminationGate`（有 cross-section 时），并用
  `clear_vertex_interval` 给"无遮挡持续时间"，替/补 P0 的纯三角时长。
- 逐列气溶胶等效地表（**FA-A2**）在本 PR 只留参数位；路径积分消光单独做。
- 整数列采样精度到 `SunwardCrossSection` 的距离网格；如需更细，加密 `even_distances`。
- 仍单层日落方位、单截面（手册典型云况）；地形遮挡 FA-G6 另做。
