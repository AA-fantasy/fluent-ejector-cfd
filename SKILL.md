---
name: fluent-ejector-cfd
description: 用 pyfluent 驱动 Ansys Fluent 做二维轴对称蒸汽引射器（ejector/injector）CFD：从设计尺寸生成 DXF 轮廓、换网格、设压力进出口、做背压扫描、离线提取引射系数 ω、核验结果可信度、出云图与 Word 汇报。当用户要做喷射器/引射器仿真、算引射系数、扫背压找临界点、核对一维设计与 CFD 偏差、或复现某一台特定引射器的算例时使用。
---

# 蒸汽引射器 CFD（pyfluent 全流程）

本技能把「一个设计尺寸表 → 可信的 ω 与背压特性 → 可交付的 Word 报告」固化成流程。
所有 API 写法都在 Ansys 2024 R2 + pyfluent 0.43.0 + Windows 上**真机跑过**，未验证的会明确标注。

---

## 0. 这个技能解决什么

蒸汽引射器的一维设计（索科洛夫方法）给的是几何和“设计引射系数 u”，但工程上真正要回答的是：

1. **这台机器在给定背压下能不能起动？**（ω>0 起动，ω<0 说明出口倒灌、二次流被顶出去）
2. **实际引射系数是多少？**（ω = ṁ_s/ṁ_p，与设计值差多少、为什么）
3. **临界背压在哪？**（背压升到多少就失稳；设计背压离它多远 = 安全余量）
4. **结论可不可信？**（网格、收敛、守恒、边界四道校验）

---

## 1. 分工边界（谁做什么，别越界浪费时间）

| 环节 | 谁做 | 说明 |
|---|---|---|
| 设计尺寸 → DXF 轮廓 | **技能侧（脚本）** | `scripts/gen_profile_dxf.py`：9 个尺寸 → 轮廓 + 站表 JSON + 自检（截面比/L/D/半角/壅塞流量/出口流速） |
| DXF → 几何体 → 体网格 | **人（Workbench/Meshing GUI）** | 本机实测：Workbench 双击 Mesh 打不开、`RunWB2 -B -R` 恒 `DONE_EXIT=2`；自写 .msh 必失败。**别在这上面耗时间** |
| 网格 → Fluent 全流程 | **技能侧** | 换网格、设边界、迭代、扫描、提取、出图、出报告 |
| 与老师核对几何假设/设计口径 | **人** | 机器不能替 |

> 一句话：**几何 DXF 我出，网格你划（5 分钟），剩下我全包。**

### 1.1 几何：9 个设计尺寸 → DXF（一条命令）

设计表（索科洛夫方法输出）通常给 9 个尺寸：`dp dp1 d2 d3 dc le 喉嘴距 lk lce`。

```powershell
# 示例：一台虚构的引射器（尺寸只演示参数顺序，不对应任何真实设计）
python scripts\gen_profile_dxf.py --dp 12 --dp1 16.4 --d2 30 --d3 30.05 ^
    --dc 71 --le 28 --gap 42 --lk 195 --lce 268 --out demo.dxf
```

产出三件：`demo.dxf`（LINE 轮廓，单位 mm）、`demo_stations.json`（5 个关键 x 站位 + 半径，切分面/命名选择用）、`demo_profile.png`（预览）。

脚本每次都打印**几何自检**，这几项不对说明设计表本身有问题，先回头核对再划网格：

| 检查项 | 经验区间 | 判断 |
|---|---|---|
| 截面比 (d2/dp)² | 与设计值差 <2% | 大了会吸不动，小了大材小用 |
| 混合室 L/D = lk/d2 | 5~8 | <4 混合不充分，>10 摩擦损失大 |
| 喷嘴扩张半角 | 4~6° | 过大会分离 |
| 扩压段半角 | 3~6° | 过大会分离，过小则太长 |
| 总长/喉径 | 20~120 | 特别大要怀疑尺寸抄错；常见值在几十到一百出头 |

给 `--p0 --T0 --k --mdot-p` 还会算**喉部壅塞理论一次流**并对比设计值（差 >5% 说明 dp 或工况抄错）；
给 `--p-out --T-out --u` 会用出口面积反算**出口流速**并与设计预期对照（该项对 `T_out` 极敏感，`T_out` 是估的就不要当结论）。没有 matplotlib 时加 `--no-png`。

> 设计表没给的三项（`dpi` 喷嘴入口直径、`dHi` 吸入室直径、`wall` 壁厚、`half` 收缩半角）
> 脚本用默认值并在输出里**显式声明**；这三项只改头部型线，不影响喉部与混合室，但报告里要写清是假设。

脚本会把 x 站位、截面比、L/D、两半角、壅塞流量、出口流速逐项打印出来，与设计表对一遍即可；
对不上先回头核设计表，别急着划网格。

DXF 只含 LINE，进 Workbench 后 `Import → 生成面` 即可；切分面位置直接用 `_stations.json` 里的 x（切在 `x_mi`、`x_mo` 最稳）。

---

## 2. 三条铁律

1. **启动 Fluent 一律走桌面会话**。DSH 沙箱里直接跑 `fluent.exe` 会 `Cannot initialize ANSYS Licensing context`（许可走命名管道被沙箱挡）。用 `pyfluent_server.bat`（双击，人在桌面）。
2. **数值一律从 `.dat.h5` 离线算**，不依赖 Fluent 的 report definition / GUI 读数。`scripts/omega.py` 直接读 h5，可复现、可回归。
3. **验证用文件，不截图**。每次判定都用 log / `.dat.h5` / `.msh` 的数值，不用肉眼。

---

## 3. 五步流程

### 3.0 自检（先跑，30 秒）

```
python scripts\doctor.py
python scripts\doctor.py --serverinfo <serverinfo.txt> --case <case.cas.h5>
```

有 ❌ 就按提示修；`--install-h5py` 可在本地目录补 h5py（不动系统环境）。

### 3.0b case 自检（拿到别人的 case / 交付前各跑一次）

两条腿：**脚本核设置** + **GUI 看现象**。

```powershell
# 1) 只读文件：网格拓扑（不连 Fluent，不需要许可证）
python scripts\case_check.py --case-only run_new\demo_coarse.cas.h5

# 2) 连上会话并读 case：把求解器/模型/边界条件逐项打印，且每项带「期望值」
python scripts\case_check.py --serverinfo serverinfo.txt ^
       --case run_new\demo_coarse.cas.h5 --data run_new\demo_coarse.dat.h5 --json check.json
```

`case_check.py` 会核这些（不一致逐条标 `[WARN]`，退出码 1）：

| 项 | 期望 |
|---|---|
| 求解器 / 时间 / 2D 空间 | pressure-based / steady / **axisymmetric** |
| 操作压力 / 重力 | 0 Pa / 关 |
| 能量方程 | on |
| 粘性模型 | k-omega + **sst** |
| 单元区 | 只有 `fluid`；出现 `solid` 就是网格被当成固体域了 |
| 边界条件 | 每个 zone 的 gauge 压力、总温、湍流强度、水力直径 |

```powershell
# 3) GUI 人工核：直接双击（会顺带自动缩放视窗）
open_case_gui.bat "run_new\demo_coarse.cas.h5" "run_new\demo_coarse.dat.h5"
```

GUI 里按 `reference\自检清单.md` 逐项打勾（A 打开与拓扑 / B 模型 / C 边界条件 /
D 网格质量 / E 试跑 1 步 / F 交付前留档）。清单里用 ☑ 标出的项，脚本已经覆盖，不用重复看。

> 交付前的最低要求：`case_check.py` 退出码 0，且 GUI 里 `Contours → Static Pressure`
> 能看出喷嘴内高压、混合室亚大气压——若全域一个颜色，先查操作压力和数据是否读对。
### 3.1 起 server（人做）

双击 `pyfluent_server.bat`。它做三件事：找 `fluent.exe` → `fluent 2ddp -g -t2 -sifile=serverinfo.txt` → 等 gRPC 起来。
窗口**别关**，`serverinfo.txt` 里是 `<LAN IP>:<port>` 与一行 key。

### 3.2 连上去

```python
import ansys.fluent.core as pf
s = pf.connect_to_fluent(server_info_file_name=SI, allow_remote_host=True, insecure_mode=True)
```

- 必须 `allow_remote_host=True`：serverinfo 写的是 `192.168.x.x:port`，不是 localhost。
- `insecure_mode=True`：0.43 的 gRPC 默认无 TLS；只在本机内网用。
- 退出：`s.exit()`（端口随之关闭，可 `netstat` 核对）。

### 3.3 读算例 / 换网格

```python
s.settings.file.read_case(file_name=r"...\big_setup.cas.h5")
s.settings.file.read_data(file_name=r"...\prev.dat.h5")      # 需要旧流场时

s.settings.file.replace_mesh(file_name=r"...\FFF.2.msh")      # 换网格，边界条件按区名自动继承
```

`replace_mesh` 是**关键技能**：把新网格塞进已配置好的 case，模型/材料/边界零改动。实测 2024 R2 + 0.43 可用（`s.file.replace_mesh` 亦可，但 0.43 会提示 `file` 已废弃）。

换网格后**必查 5 项**（`doctor.py --case` 会一起查）：

1. 单元数/节点数是否等于 Meshing 里统计值
2. 区名是否齐全：`inlet-primary`、`inlet-secondary`、`outlet-mix`、`axis`、`wall`
3. 区类型：两个压力入口、一个压力出口、一个 axis、一个 wall
4. cell zone 是否为 `fluid`（Workbench 常给成 `solid`，见第 9 节坑 1）
5. 单位：`.msh` 若是毫米，`Domain Extents` 会露馅（本机 Workbench 直接导出米制）

### 3.4 设边界条件（唯一可靠写法）

**不要**用 `s.settings.boundary_conditions...`（根级没有这个属性），也**不要**下标取字段（`pressure_outlet_child` 不支持下标）。唯一稳的是读-改-写 state：

```python
po = s.settings.setup.boundary_conditions.pressure_outlet
st = po.get_state()
st["outlet-mix"]["momentum"]["gauge_pressure"] = {"option": "value", "value": 101325.0}
po.set_state(st)                       # 写完立刻 get_state() 回读确认
```

- 单位全用 **Pa / K 绝对值**，`operating_pressure = 0`（否则会差一个大气压）。
- 入口给的是**总压**（pressure-inlet 语义）；出口给的是**静压**。
- 湍流：`turbulent_intensity` 5%、水力直径按 `4A/Peri` 自己算（2D 轴对称里就是 2 倍入口高度量级）。
- 一次跑多个背压：同一个 session 里逐点 `set_state` → `iterate` → `write_case_data`，别重启 Fluent。

### 3.5 求解

```python
s.tui.solve.monitors.residual.convergence_criteria(1e-12,1e-12,1e-12,1e-12,1e-12,1e-12)
s.tui.solve.initialize.hyb_initialization()     # 从零算才需要
s.tui.solve.iterate(800)
s.settings.file.write_case_data(file_name=r"...\bg_090.cas.h5")
```

- **必须**用 `s.tui.solve.iterate`，不要用 `s.solution.run_calculation.iterate()`——后者会先做一次 hybrid 初始化，把续算变成从头算。
- 残差判据统一压到 `1e-12`，是为了**强制跑满步数**：读入一个已收敛的场后，默认判据会在第一步就报 converged（假收敛，实测两个相差两倍的背压能算出完全相同的结果）。
- 状态判断：`s.settings.solution.monitor.residual` 或看 `.trn`；收敛后 ω 应稳定到 4~5 位有效数字。

---

## 4. 背压扫描策略（找临界背压）

**两级扫描**，别一上来就密扫：

1. **粗扫**：从设计背压往上每 20~25 kPa 一点，先看 ω 在哪儿过零。每点 200~400 步。
2. **细扫**：在过零点两侧各补 2~3 点，步长 5 kPa，每点 200 步（从相邻收敛解续算）。

典型形态：ω 先是一段几乎不动的平台，过某个点后几 kPa 内就掉到零附近——临界背压就落在这段"悬崖"里，
所以要**细扫**而不是加密粗扫。**临界背压这个数字比 ω 本身更有工程价值**，报告里一定要给。

注意：壅塞段内（ω 平台区）多算几个点会得到**完全相同**的值——这是物理正确的（二次流已达上限），不是程序 bug。

---

## 5. 提取 ω（离线，可复现）

```
python scripts\omega.py <case.cas.h5> <case.dat.h5> 101kPa
python scripts\omega.py --batch "100,a.cas.h5,a.dat.h5" "101,b.cas.h5,b.dat.h5"
python scripts\omega.py --list-zones <case.cas.h5>
```

输出：`mp`、`ms`、`ω=ms/mp`、出口均温、出口 Ma、出口总压。
原理：直接读 `dat.h5` 的 `SV_T`/`SV_P`/`SV_U`…，按区面积分——**不依赖 Fluent**，任何带 `numpy+h5py` 的 Python 都能跑。

判定口径：
- `ω > 0` 起动；`ω < 0` 未起动（倒灌），此时 `ms` 是负的。
- `ω` 与设计值差 +10~25% 属正常（一维方法偏保守），差 3 倍以上要先怀疑设置（单位、operating pressure、入口类型、区类型）。

---

## 6. 结果可信度：四条硬校验（每条都要跑）

| # | 校验 | 通过标准 | 怎么算 |
|---|---|---|---|
| 1 | 质量守恒 | 一次流 `mp` 与喉部壅塞理论差 **< 5%** | 理论：`ṁ = A_t·p₀/√T₀·√(k/R)·(2/(k+1))^((k+1)/(2(k-1)))` |
| 2 | 真收敛 | 续算 500 步后 ω 变化 **< 0.5%** | 另存一份，再 `iterate(500)`，两次 `omega.py` 对比 |
| 3 | 边界自洽 | 出口静压 ≈ 设定背压（±2%） | `omega.py` 的 `p0out` 与 `p_out` 比 |
| 4 | 网格无关性 | 两套网格 ω 差 **< 5%**；临界背压差 **< 3%** | 粗/细网格各扫一遍 |

任一条不过，**先说没过**，不要硬写结论。四条全过，报告的措辞才能用“可信”。

---

## 7. 偏差归因（写报告的口径，别硬解释）

与一维设计值差 +10~25% 时，按这个顺序归因并写清楚：

1. **一维经验损失系数**：索科洛夫方法把混合损失折成系数，CFD 是绝热、无粗糙度、无进口畸变 ⇒ CFD 通常**偏高**。这是主因，写“方法差异”，不写“老师算错了”。
2. **网格无膨胀层**（若有）：y⁺≈50，SST 自动壁面处理可用，但 ω 可能偏高 2~5%。写进“已知偏差”。
3. **2D 轴对称**：忽略周向不均匀与进口涡，对这类轴对称喷射器是标准做法，但要声明。
4. **几何假设**：设计表没给全时（喷嘴收缩半角、吸入室收缩半角、壁厚），明确列出假设值，请老师核对。

反面示例（不要这么写）：“CFD 结果更准确，一维设计偏保守 21%”——把方法差异说成对方错误，容易被质疑。

---

## 8. 出图与报告

- 云图：`scripts/` 不含绘图，用工作区 `plot_big.py` 的模式（h5py 读场量 → `tricontourf`）；长流道务必**两幅图**（全长 + 头部放大），否则细节全糊。
- 曲线：ω–背压，标出设计点、临界背压竖线、ω=0 水平线。
- 报告骨架（python-docx）：`1 结论摘要 / 2 计算对象（几何表+轮廓图+边界表+数值设置）/ 3 计算结果（设计点对照表、背压特性表、ω 曲线、流场云图）/ 4 结论与建议 / 5 数据文件`。
- 排版经验：A4、正文宋体小四、图宽 12~15 cm、表头灰底加粗、表格 `cantSplit`、图与图注 `keep_with_next`；生成后用 LibreOffice 渲染逐页看有没有空白页/断表。

---

## 9. 常见坑（详见 `reference/pitfalls.md`）

1. **`Flow boundary zone (...) is adjacent to a solid zone (geom___)`**：Meshing 把流体区导出成 solid cell zone。修法：Fluent GUI `Domain → Zones → Type` 或 TUI `/define/boundary-conditions/zone-type`，**先问区名、再问 cell-type**，顺序反了报 `Invalid zone.`
2. **假收敛**：读入已收敛场后默认判据一步即收敛 ⇒ 残差统一 `1e-12`。
3. **`iterate()` 会重新初始化** ⇒ 用 `s.tui.solve.iterate(N)`。
4. **边界条件 API**：`s.settings.boundary_conditions` 不存在；`..._child` 不支持下标 ⇒ 只用 `setup.boundary_conditions` + `get_state/set_state`。
5. **两个 Python 别混用**：Fluent 自带 python(3.10, 有 numpy/h5py) 跑 `omega.py` 最省事；DSH runtime python(3.12) 跑 `connect.py`/`run_point.py`（需 `PYTHONPATH` 指向 `ansys-fluent-core`）。把 3.12 的 `.pylibs` 塞进 3.10 的 `PYTHONPATH` 会 `No module named 'numpy._core._multiarray_umath'`。
6. **`/adapt` 不存在**（2024 R2 两种写法都 `invalid command`）⇒ 不能靠 Fluent 自适应加密网格。
7. **别把 python 输出接 `Select-Object -First N`**：管道提前关闭会让进程 `Broken pipe` 被杀。

---

## 10. 可复现三件套（每个交付点都要留）

```
<点>.cas.h5        # 网格 + 模型 + 边界（含所有设置）
<点>.dat.h5        # 流场（ω 完全由它算出来）
<点>_meta.txt      # 迭代步数、残差、p_in/p_out/T、网格单元数、生成脚本版本
```

别人（或半年后的自己）拿 `.dat.h5` 跑一条命令就能复现同一个 ω —— 这条做到了，结论才叫“可复核”。

---

## 11. 验收清单（每次收尾自查）

- [ ] `doctor.py` 全绿
- [ ] 单元数与 Meshing 统计一致；5 个区名/类型正确；cell zone 是 fluid
- [ ] 质量守恒 < 5%
- [ ] 续算 500 步 ω 变化 < 0.5%
- [ ] 出口静压 ≈ 设定背压（±2%）
- [ ] 两套网格 ω 差 < 5%（至少一次）
- [ ] 报告里写清：几何假设、网格（含无膨胀层）、2D 轴对称、偏差归因
- [ ] 三件套齐全

---

## 附录 A：几条结论级的规律（不含任何算例数值）

分享版刻意不写真实几何、网格量和工况——换一台机器这些数字全变，规律不变：

1. **壅塞段 ω 是平台**：二次流已达上限，背压在小范围内变，ω 几乎不动；多算几个点得到同值，是物理正确，不是假收敛。
2. **临界背压离设计背压越近越危险**：设计点只剩 3%~5% 富余时，制造偏差、表面粗糙度就足以让它不起动。
   所以报告里必须给临界背压和"到设计点的富余量"，不能只给设计点 ω。
3. **二维轴对称 + 无膨胀层足以判断"起没起动"**，但不足以把 ω 精确到 ±2%；要报精度就得加膨胀层并做网格无关性。
4. **设计值与 CFD 差个几成是常见的**，多来自一维方法的效率假设（喷嘴/混合/扩压各段的损失系数）和真实三维效应；
   先怀疑一维口径，再怀疑网格。
5. **二次流很弱（吸入压比接近 1）的机器最脆**：一维设计很乐观，二维算出来往往直接不起动。
