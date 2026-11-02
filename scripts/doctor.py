# -*- coding: utf-8 -*-
"""环境自检：装完先跑这个，能提前发现 90% 的“跑不起来”。

检查项
  1. Python 版本（>=3.9）
  2. numpy / h5py
  3. ansys-fluent-core（pyfluent）能否 import、版本是否 >=0.30
  4. 能否找到 fluent.exe（先看环境变量 FLUENT_EXE，再扫常见安装路径）
  5. --serverinfo 能否解析、端口是否在监听
  6. --case 能否被 h5py 打开并列出区名

用法:
    python doctor.py
    python doctor.py --serverinfo serverinfo.txt
    python doctor.py --serverinfo serverinfo.txt --case run_new\\demo_coarse.cas.h5
退出码: 0 全过；1 有 ❌ 项；2 参数错误
"""
from __future__ import annotations

import argparse
import glob
import os
import socket
import sys

OK, WARN, BAD = "✅", "⚠️ ", "❌"


class Report:
    def __init__(self):
        self.bad = 0
        self.warn = 0

    def ok(self, msg, hint=""):
        print(f"{OK} {msg}" + (f"   → {hint}" if hint else ""))

    def warn(self, msg, hint=""):
        self.warn += 1
        print(f"{WARN}{msg}" + (f"   → {hint}" if hint else ""))

    def fail(self, msg, hint=""):
        self.bad += 1
        print(f"{BAD} {msg}" + (f"   → {hint}" if hint else ""))


def find_fluent(rep: Report) -> str | None:
    env = os.environ.get("FLUENT_EXE", "").strip('"')
    if env and os.path.isfile(env):
        rep.ok(f"fluent.exe（FLUENT_EXE）: {env}")
        return env
    pats = [
        r"D:\ANSYS\*\v*\fluent\ntbin\win64\fluent.exe",
        r"C:\ANSYS\*\v*\fluent\ntbin\win64\fluent.exe",
        r"C:\Program Files\ANSYS Inc\v*\fluent\ntbin\win64\fluent.exe",
        r"D:\Program Files\ANSYS Inc\v*\fluent\ntbin\win64\fluent.exe",
        r"D:\Program Files\ANSYS *\v*\fluent\ntbin\win64\fluent.exe",
    ]
    hits = []
    for p in pats:
        hits += glob.glob(p)
    if hits:
        rep.ok(f"fluent.exe: {hits[-1]}", "多个版本时取最后一个，可用 FLUENT_EXE 指定")
        return hits[-1]
    rep.fail("找不到 fluent.exe", "设环境变量 FLUENT_EXE 指向 ...\\fluent\\ntbin\\win64\\fluent.exe")
    return None


def check_serverinfo(path, rep: Report):
    if not os.path.isfile(path):
        rep.fail(f"serverinfo 不存在: {path}", "先在桌面会话双击 pyfluent_server.bat 生成")
        return
    txt = open(path, "r", encoding="utf-8", errors="replace").read().strip().splitlines()
    if len(txt) < 2:
        rep.fail(f"serverinfo 内容不完整（{len(txt)} 行）", "需要 2 行：地址:端口 + password")
        return
    addr = txt[0].strip()
    host, _, port = addr.replace("localhost", "127.0.0.1").rpartition(":")
    try:
        port = int(port)
    except ValueError:
        rep.fail(f"第 1 行不是 地址:端口 格式: {addr!r}")
        return
    rep.ok(f"serverinfo 解析: {host}:{port}")
    try:
        with socket.create_connection((host, port), timeout=3):
            rep.ok(f"端口 {port} 在监听")
    except OSError as exc:
        rep.fail(f"连不上 {host}:{port}（{exc}）", "Fluent 控制台是否还开着？可能已经退出")


def check_case(path, rep: Report):
    if not path:
        return
    if not os.path.isfile(path):
        rep.fail(f"case 不存在: {path}")
        return
    try:
        import h5py
        with h5py.File(path, "r") as f:
            zt = f["meshes/1/faces/zoneTopology"]
            names = [s for s in zt["name"][()][0].decode("utf-8", "replace").split(";") if s]
        rep.ok(f"case 可读: {os.path.basename(path)}，面区 {len(names)} 个: {', '.join(names[:8])}"
               + (" …" if len(names) > 8 else ""))
    except Exception as exc:                       # noqa: BLE001
        rep.fail(f"case 读不了: {type(exc).__name__}: {exc}", "确认是 .cas.h5（不是 .msh/.cas 旧格式）")


def main() -> int:
    ap = argparse.ArgumentParser(description="环境自检")
    ap.add_argument("--serverinfo", default=None)
    ap.add_argument("--case", default=None)
    ap.add_argument("--skip-fluent", action="store_true", help="只检查 python 侧（不找 fluent.exe）")
    a = ap.parse_args()

    rep = Report()
    print("=" * 68)
    print(" fluent-ejector-cfd 环境自检")
    print("=" * 68)

    v = sys.version_info
    if v >= (3, 9):
        rep.ok(f"Python {v.major}.{v.minor}.{v.micro}: {sys.executable}")
    else:
        rep.fail(f"Python {v.major}.{v.minor} 太旧", "需要 3.9+")

    for mod in ("numpy", "h5py"):
        try:
            m = __import__(mod)
            where = os.path.dirname(getattr(m, "__file__", "") or "")
            rep.ok(f"{mod} {getattr(m, '__version__', '?')}"
                   + (f"   ({where})" if mod == "numpy" else ""))
        except Exception as exc:                   # noqa: BLE001
            txt = f"{type(exc).__name__}: {exc}"
            if "_multiarray_umath" in txt or "PLEASE READ THIS FOR ADVICE" in txt:
                # 典型症状：PYTHONPATH 指向了另一个 CPython 版本的 site-packages
                tag = f"cp{v.major}{v.minor}"
                rep.fail(f"{mod} 导入失败：numpy C 扩展与当前解释器（{tag}）不匹配",
                         "清空 PYTHONPATH 再跑（PowerShell: $env:PYTHONPATH=''）；"
                         "别把 pyfluent 的 .pylibs 目录塞给 Fluent 自带的 python，反之亦然")
            else:
                hint = f"pip install {mod}"
                if mod == "h5py":
                    hint += "；或改用 Fluent 自带 python 跑 omega.py（它自带 h5py+numpy）"
                rep.fail(f"缺 {mod}（{type(exc).__name__}）", hint)

    try:
        import ansys.fluent.core as pf
        ver = getattr(pf, "__version__", "?")
        rep.ok(f"ansys-fluent-core {ver}")
        try:
            major, minor = (int(x) for x in str(ver).split(".")[:2])
            if (major, minor) < (0, 30):
                rep.warn("pyfluent 版本偏旧（Fluent 自带 python 里通常就是这个开发版）",
                         "本技能按 0.43 验证；这个解释器只适合跑 omega.py/doctor.py，"
                         "驱动 Fluent 请用装了 ansys-fluent-core==0.43.0 的 python")
        except Exception:                          # noqa: BLE001
            pass
    except Exception as exc:                       # noqa: BLE001
        rep.fail(f"import ansys.fluent.core 失败: {type(exc).__name__}: {exc}",
                 "pip install ansys-fluent-core==0.43.0；若报 Access denied 检查目录权限")

    if not a.skip_fluent:
        exe = find_fluent(rep)
        if exe and "v242" not in exe:
            rep.warn("Fluent 版本不是 2024 R2", "本技能在 2024 R2 验证，其他版本 TUI 可能不同")

    if a.serverinfo:
        check_serverinfo(a.serverinfo, rep)
    check_case(a.case, rep)

    print("-" * 68)
    if rep.bad:
        print(f"{BAD} {rep.bad} 项未通过，{rep.warn} 项提醒 —— 按上面的 → 提示修")
        return 1
    print(f"{OK} 全部通过" + (f"（{rep.warn} 项提醒不影响运行）" if rep.warn else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
