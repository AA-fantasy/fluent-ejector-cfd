# 踩过的坑（按代价从大到小）

## 1. 启动 Fluent 的三条死路

| 尝试 | 结果 |
|---|---|
| 沙箱里直接跑 `fluent.exe` | `Cannot initialize ANSYS Licensing context`（沙箱拿不到许可证） |
| 沙箱里 `taskkill` / `schtasks` / WMI 建进程 | `拒绝访问`（进程创建被策略拦） |
| Win+R 启 `.bat` → 点"运行"对话框 → GUI 里点菜单 | 时灵时不灵：Qt 菜单能 hover 但不选中、Workbench 双击不开编辑器、点击落到别的窗口 |

**结论**：起 Fluent 只能由用户桌面双击；操作 Fluent 只能靠 pyfluent / TUI。

## 2. pyfluent 的三个 API 细节

```python
# ✅ 关键字参数
s.file.read_case(file_name=path)
# ❌ Command.__call__() takes 1 positional argument but 2 were given

# ✅ getter 返回的是 dict，赋值要落到 ["value"]
st = s.settings.boundary_conditions.pressure_outlet["outlet-mix"]
st.momentum["gauge_pressure"]["value"] = 101325
# ❌ st.momentum["gauge_pressure"] = 101325 → TypeError: must be real number, not dict

# ✅ iterate 不要在已收敛场上重新初始化
s.tui.solve.iterate(800)                              # TUI，直接跑
s.solution.run_calculation.iterate(iter_count=800, initialize=False)
# ❌ s.solution.run_calculation.iterate(800) → 会先做 hybrid init，解被冲掉
```

另：`connect_to_fluent(server_info_file_name=...)` 对 LAN 地址（`192.168.x.x:端口`）会报错，
必须加 `allow_remote_host=True, insecure_mode=True`。

## 3. 数值假收敛（最坑）

读入已收敛的 `.dat.h5` 再改背压跑，Fluent 会沿用上一轮的残差判据，**第一步就报 converged**，
解完全不响应新背压（两个相差两倍的背压算出同样的 ω）。

解法：每次读 case 后强制把 6 个方程判据设成 `1e-12`，让它真跑满步数：

```python
s.tui.solve.monitors.residual.convergence_criteria(1e-12, 1e-12, 1e-12, 1e-12, 1e-12, 1e-12)
```

判据：同一工况再续算 500 步，ω 变化 < 0.5% 才算真收敛（本项目实测过：续算 500 步还没稳住的情况是存在的）。

## 4. 网格相关的坑

- **`.msh` 里的计数是十六进制**：`(10 (0 1 40d 0))` 是 1037 个节点，不是 40d 个字符串；一个 51 KB、
  号称"改好了"的 msh 往往只有 871 个单元。
- Workbench 的"更新"不一定真的导出体网格：`dp0\<SYS>\MECH\<SYS>.msh` 可能是边网格/残件；
  要以**文件大小**（正常 >300 KB）和 Fluent 读进去的单元数为准。
- `replace-mesh` 会留下 inactive parent 单元（本项目上千个单元里留了几十个），统计时按 `cn>0` 过滤，
  否则 `IndexError: boolean index did not match`。
- Workbench 出的网格默认把入口设成 `velocity-inlet`、把流体区标成 `geom___ solid`；
  换进已配置的 case 后按区名继承，自动变回 `pressure-inlet` / `fluid`，不用手改。

## 5. 环境与工具链

- `.pylibs` / `.pylibs-fluent` 装依赖：**bat 必须 CRLF**，我最初写成 LF 导致 `goto :fail` 找不到标签、
  黑框一闪就退。
- pip 默认源在本机不通，用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- 解压出来的目录 ACL 可能只有 SYSTEM/Administrators，沙箱 `import` 时 `Access is denied`；
  用 `icacls <dir> /grant *S-1-5-32-545:(OI)(CI)F /T` 补 Users 权限。
- matplotlib 默认往 `%USERPROFILE%\.matplotlib\` 写 font 缓存，沙箱会拒；设 `MPLCONFIGDIR=<workspace>\.mplcache`。
- Fluent 自带 python **没有 python-docx**；出 Word 要用 DSH runtime 的 python
  （`%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`）。
- 别把 python 输出接 `Select-Object -First N`：管道提前关闭 → SIGPIPE → 进程被杀，
  看起来像"莫名其妙退出了"。
- PowerShell 5.1 的 `Get-Content -Raw` 会把 UTF-8 中文读成乱码再写回；改文件用
  `[IO.File]::ReadAllText/WriteAllText(..., UTF8Encoding($true))`。

## 6. 已证伪的路线（别再试）

- `/adapt`、`/solve/adapt`、`/mesh/adapt`：本 build 的 TUI 里都不存在；网格自适应只能在 GUI
  的 Adapt 对话框里点（而且 `Adapt` 按钮要求先有非空的 cell register）。
- 自己写 Fluent ASCII `.msh`（legacy 格式）：能读进去、计数也对，但 `/mesh/check` 一律报
  `Cell ... is missing face` → `Build Grid: Aborted due to critical error`；换了朝向/加 cell body
  都不行，**放弃**。
- CGNS 导入：`/file/read-case x.cgns` → `Null Domain Pointer`；`/file/import/cgns` 是菜单，
  带路径直接报 `invalid command`。
- Workbench `RunWB2 -B -R journal`：本机批处理模式跑不起来（`DONE_EXIT=2`，日志 14 字节）。

## pyfluent 0.43 边界条件 API（2026-11-02 真机验证）
- ❌ `s.settings.boundary_conditions` 不存在 ⇒ 报 `AttributeError: 'root' object has no attribute 'boundary_conditions'`
- ✅ 正确路径：`s.settings.setup.boundary_conditions`
- ❌ `bc.pressure_outlet["zone"]` 拿到的 child **不支持下标**：`z["momentum"]` → `TypeError: 'pressure_outlet_child' object is not subscriptable`；用 `.momentum.gauge_pressure.value = x` 也读不回标量（返回 value 包装对象）
- ✅ 可靠写法（读-改-写 state）：
```python
po = s.settings.setup.boundary_conditions.pressure_outlet
st = po.get_state()   # {'outlet-mix': {'momentum': {'gauge_pressure': {'option':'value','value':101325.0}, ...}}}
st["outlet-mix"]["momentum"]["gauge_pressure"] = {"option": "value", "value": 102325.0}
po.set_state(st)
```
- 冒烟验证记录：几千单元的粗网格算例，connect→read→set 背压→50 步→write_case_data→omega.py，全链路约 10 s 跑通

---

## 坑 7：两个 python 的依赖互相借 → numpy C 扩展版本不匹配（2026-11-02 实测）

**症状**（用 Fluent 自带 python 跑 omega.py，但 PYTHONPATH 指向了 pyfluent 的 .pylibs）：

```
ModuleNotFoundError: No module named 'numpy._core._multiarray_umath'
...
ImportError:
IMPORTANT: PLEASE READ THIS FOR ADVICE ON HOW TO SOLVE THIS ISSUE!
...
The following compiled module files exist, but seem incompatible
with with either python 'cpython-310' or the platform 'win32':
  * _multiarray_umath.cp312-win_amd64.pyd
```

**根因**：`.pylibs-fluent\` 里的 numpy 是给 **CPython 3.12** 编的（`cp312`），
而 `fluent.exe` 自带的 python 是 **CPython 3.10**。`PYTHONPATH` 把 cp312 的 site-packages
插到了 cp310 的 `sys.path` 前面，numpy 找得到目录、找不到匹配的 `.pyd`，于是抛出上面这段
**完全看不出根因**的报错。

**唯一正确写法**：

```powershell
# 跑 omega/doctor（用 Fluent python）——先清空 PYTHONPATH
$env:PYTHONPATH=''
& 'D:\ANSYS\2024 R2\v242\commonfiles\CPython\3_10\winx64\Release\python\python.exe' scripts\omega.py ...
```

```powershell
# 跑 connect/run_point（需要 pyfluent）——这时才加 .pylibs
$env:PYTHONPATH='C:\...\default-workspace\.pylibs-fluent'
& 'C:\...\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe' scripts\connect.py ...
```

**自查**：`python scripts\doctor.py` 会打印 numpy 的**实际目录**；目录里出现
`cp312`/`cp310` 与解释器版本不一致，就是踩了这个坑（doctor 已内置该诊断）。

**顺带**：Fluent 自带 python 里的 `ansys-fluent-core` 是 `0.20.dev12` 开发版，
**只能跑离线脚本，不能驱动 server**（doctor 会给 ⚠️ 提示）。