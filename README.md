# fluent-ejector-cfd —— 蒸汽引射器 CFD 技能包

> **分享版说明（请先读）**
>
> - **不含任何算例数据**：本包不含真实几何、网格、工况、企业设计点或计算结果；文中尺寸均为**虚构示例**，只用于演示参数顺序。
> - **验证范围**：只在 Windows + ANSYS Fluent 2024 R2 + pyfluent 0.43.0 上真机跑通过；其他版本未验证。
> - **适用**：二维轴对称、定常、单相可压缩（水蒸气）的引射器/喷射器——设计校核、ω 提取、背压扫描、报告。
> - **不适用**：三维、非定常、多相/相变（湿蒸汽/冷凝）、燃烧、共轭传热。拿它算这些，结论无效。
> - **与 Ansys, Inc. 无隶属关系**：非官方、无背书；不含 Ansys 任何代码/文档/界面截图，不绕过任何许可机制，使用需自备合法 Fluent 许可。详见 `DISCLAIMER.txt`。
> - **许可 MIT**（见 `LICENSE`）。转发、改写请保留本说明与免责声明。

用 **pyfluent**（Ansys 提供的开源 Python 接口，Apache-2.0 许可）驱动 Fluent 做二维轴对称蒸汽引射器仿真：
读/换网格 → 设压力进出口 → 跑背压扫描 → 离线提取引射系数 ω → 出云图与 Word 汇报。

> 这套流程来自若干真实引射器算例的完整计算过程，坑都是踩过的。
> 关键原则：**数值结论全部从 `.dat.h5` 离线算**，不看界面、不读残差窗口、不靠截图。

---

## 1. 它解决什么问题

| 场景 | 传统做法 | 用这个技能 |
|---|---|---|
| 改一个背压重算 | 打开 GUI、点 15 个提示、跑完截图看数 | 一行 TUI 设背压 + `iterate(200)`，`omega.py` 直接给 ω |
| 扫 5 个背压找临界点 | 手点 5 次、每次记数 | 一个 for 循环，最后 `--batch` 出表 |
| 换网格重算 | 重设边界条件 | `s.settings.file.replace_mesh(file_name=...)`（pyfluent 已暴露，实测存在），按区名继承全部设置 |
| 出汇报 | Excel 拼图 | python-docx + 渲染检查（要点见 SKILL.md） |
| 从设计表画轮廓 | CAD 手画 | `gen_profile_dxf.py`：9 个尺寸 → DXF + 站表 + 自检 |

---

## 2. 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Windows | 只在 Windows + ANSYS 2024 R2 验证过 |
| ANSYS | Fluent 2024 R2（`fluent.exe`） | 其他版本大概率可行，未验证 |
| Python | ≥ 3.9 | 用哪个都行，见下 |
| `pyfluent` | `ansys-fluent-core==0.43.0` | **只有驱动 Fluent 的脚本需要** |
| `numpy` `h5py` | 任意较新版本 | `omega.py` / `doctor.py` 只需要这两个 |

**两个 python 的区别**（新手最容易卡这里）：

- `connect.py` / `run_point.py` → 需要 **pyfluent**，即装了 `ansys-fluent-core` 的那个 python
- `omega.py` / `doctor.py` → 只要 **numpy + h5py**；Fluent 自带的 python 就有，DSH 运行时的 python 一般也有

> ⚠️ **两边的依赖不要互相借**。把 pyfluent 的 `--target .pylibs`（例如 `numpy 2.5.4 + cp312`）
> 塞给 Fluent 自带的 python（`cp310`）会报
> `ModuleNotFoundError: No module named 'numpy._core._multiarray_umath'`，
> 报错信息完全看不出是版本冲突。跑脚本前先 `$env:PYTHONPATH=''`（PowerShell）
> 或 `set PYTHONPATH=`（cmd），`doctor.py` 会打印 numpy 的实际位置帮你确认。

`doctor.py` 会把当前解释器、各依赖版本、`fluent.exe` 路径全打出来，**装完先跑它**。

---

## 3. 快速开始（5 步）

```powershell
# 1) 装依赖（用你打算驱动 Fluent 的那个 python）
pip install -r requirements.txt

# 2) 自检：哪项 ❌ 就按提示修
python scripts\doctor.py
python scripts\doctor.py --serverinfo _work\serverinfo.txt --case run_new\demo_coarse.cas.h5   # 传了 --serverinfo 会自动测端口

# 3) 确认能自动找到 fluent.exe（找不到就 set FLUENT_EXE=<全路径>）
pyfluent_server.bat --check
#   期望输出: FOUND=D:\ANSYS\2024 R2\v242\fluent\ntbin\win64\fluent.exe

# 4) 双击 pyfluent_server.bat —— Fluent 起来后在 _work\ 里写 serverinfo.txt，窗口别关

# 5) 连上去（需要 pyfluent 那个 python + PYTHONPATH 指向它）
python scripts\connect.py                      # 只验证连通，打印 Fluent 版本
python scripts\run_point.py --help             # 看参数
```

`pyfluent_server.bat` 的自动查找顺序：`D:\ANSYS` → `C:\Program Files\ANSYS Inc` →
`C:\ANSYS Inc` → `E:\ANSYS`，在每个根目录下按 `*\<版本>\v2xx\fluent\ntbin\win64\fluent.exe`
找，同版本取最后一个（即最新）。核数默认 `-t2`，要改就编辑 bat 里的 `-t2`。

**注意**：Fluent 必须在**桌面会话**里启动（双击 bat）。在沙箱/服务里直接跑 `fluent.exe`
一定报 `Cannot initialize ANSYS Licensing context` —— 许可证要靠桌面会话拿。

---

## 4. 目录结构

```
fluent-ejector-cfd/
├── SKILL.md              技能主文件：何时用、三条铁律、五步流程、坑表、验收清单
├── README.md             本文件
├── reference/
│   └── pitfalls.md       每个坑的错误原文 + 根因 + 唯一正确写法（含 4 条已证伪路线）
├── scripts/
│   ├── gen_profile_dxf.py 设计尺寸 → 2D 轮廓 DXF + 站表 + 几何/工况自检
│   ├── doctor.py         环境自检（可不依赖 pyfluent 单独跑）
│   ├── connect.py        连 Fluent，打印版本；用于验证 server 是否活着
│   ├── run_point.py      读 case → 设背压 → 迭代 → 写 case/data
│   ├── omega.py          从 .dat.h5 离线算 mp / ms / ω / Tout / Ma / p0
│   └── case_check.py     case 自检：网格拓扑 / 求解设置 / 边界条件逐项对照
├── open_case_gui.bat     用 Fluent GUI 打开指定 case（人工核查用）
├── pyfluent_server.bat   起 Fluent server（改路径后双击）
└── requirements.txt
```

`scripts/omega.py`、`scripts/doctor.py`、`scripts/case_check.py --case-only` 可用任意带 numpy+h5py 的 python 运行，**不需要装 pyfluent**。

---

## 5. 脚本用法

### doctor.py —— 自检

```powershell
python scripts\doctor.py
python scripts\doctor.py --serverinfo _work\serverinfo.txt --case demo_coarse.cas.h5
```

检查：python 版本、numpy、h5py、pyfluent、`fluent.exe` 路径；传 `--serverinfo` 还会解析格式并**实测端口连通性**；传 `--case` 会真的用 h5py 打开并列出面区。
输出 ✅/⚠/❌ 与修复建议；有 ❌ 时退出码为 1。

### gen_profile_dxf.py —— 设计尺寸 → DXF 轮廓

```powershell
python scripts\gen_profile_dxf.py --dp 12 --dp1 16.4 --d2 30 --d3 30.05 --dc 71 ^
    --le 28 --gap 42 --lk 195 --lce 268 --out demo.dxf
```

除 PNG 预览（需要 matplotlib，可用 `--no-png` 跳过）外**零依赖**。输出 `demo.dxf`、`demo_stations.json`（5 个关键 x 站位）、`demo_profile.png`。
同时打印截面比、混合室 L/D、两个半角、总长/喉径；给 `--p0 --T0 --k --mdot-p` 还会算
喉部壅塞理论流量，给 `--p-out --T-out --u` 会反算出口流速，可和设计预期自己对照（**出口流速对 T_out 很敏感**，T_out 若是估的就别当结论用）。

### omega.py —— 离线提取引射系数

```powershell
# 单点
python scripts\omega.py 101kPa.cas.h5 101kPa.dat.h5 101kPa

# 多点出表（stage,case,data）
python scripts\omega.py --batch "90,c090.cas.h5,c090.dat.h5" "95,c095.cas.h5,c095.dat.h5"

# 区名对不上时先看有哪些面区
python scripts\omega.py --list-zones c090.cas.h5
```

| 可选参数 | 作用 |
|---|---|
| `--in-p / --in-s / --out` | 改一次流入口 / 二次流入口 / 混合出口的区名 |
| `--gamma / --R` | 改比热比与气体常数（默认 1.13 / 461.5，蒸汽） |

输出列：`mp[kg/s]  ms[kg/s]  omega  Tout[K]  MaOut  p0out[Pa]`。
判读：ω>0 起动；ω≈0 是临界背压；ω<0 出口倒灌（未起动）。

### run_point.py —— 设背压并迭代

```powershell
python scripts\run_point.py --case c090.cas.h5 --data c090.dat.h5 ^
    --p 95000 --iter 200 --out c095.cas.h5
```

关键点（都写进 pitfalls.md 了）：

- 边界条件走 `s.settings.setup.boundary_conditions`，**读-改-写 state** 是唯一可靠写法
- 迭代必须走 `s.tui.solve.iterate(n)`；`s.solution.run_calculation.iterate()` 会**先重新初始化**
- 换背压续算前，把残差判据统一设成 `1e-12`，否则会出现"一步收敛"的假象

---

### case_check.py —— case 自检（只读，不改设置）

```powershell
# 只看网格拓扑（不连 Fluent，不需要许可证）
python scripts\case_check.py --case-only run_new\demo_coarse.cas.h5

# 连上会话 + 读 case：逐项打印求解设置与边界条件，每项带期望值
python scripts\case_check.py --serverinfo serverinfo.txt ^
       --case run_new\demo_coarse.cas.h5 --data run_new\demo_coarse.dat.h5 ^
       --json check.json
```

核的项：求解器/时间/2D 空间、操作压力、重力、能量方程、粘性模型（k-ω SST）、
单元区是否为 fluid、每个入口出口的 gauge 压力/总温/湍流强度/水力直径。
不一致打 `[WARN]`，退出码 1；读取失败打 `[FAIL]`。

> 它**不会**关闭 Fluent 会话。UI 里的人工项见 `reference\自检清单.md`；
> 想直接在 GUI 里看，用 `open_case_gui.bat "xx.cas.h5" "xx.dat.h5"`。

---
## 6. 已知边界（别指望它全能）

- ✅ 验证过：Windows + ANSYS 2024 R2 + **2D 轴对称** + 单机 + Workbench 导出的 `.msh`
- ⚠️ 未验证：3D、其他 ANSYS 版本、ICEM/CGNS 网格、Linux、并行大规模算例
- ⚠️ 出图（云图/曲线）与 Word 汇报的实现**没有随包提供**，只在 SKILL.md 里给了要点与踩坑
  （`.dat.h5` 里字段名、`extend="max"`、`set_aspect("auto")`、docx 表格宽度等）
- ⚠️ 自写 Fluent ASCII `.msh` 这条路**已验证走不通**（必报 `Cell ... is missing face`），别重试

---

## 7. 出问题先看哪里

1. `python scripts\doctor.py` 的 ❌ 项
2. `reference/pitfalls.md` —— 按错误原文搜，每条都有根因和正确写法
3. `SKILL.md` 的"常见坑"表

---

## 8. 出处与许可

内部经验整理（两台蒸汽引射器的建模、诊断、网格无关性、报告生成），无第三方代码。
`pyfluent` 与 ANSYS Fluent 的使用遵循 ANSYS 的许可协议；本包只调用其公开 Python API。
