#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""case 自检：把「这份 case 到底设成了什么」逐项打印并与期望值对照（只读，不改设置）。

用法
----
1) 连已有会话，只读设置：
       python scripts\\case_check.py --serverinfo ...\\serverinfo.txt
2) 连上去并先读 case（data 可选）：
       python scripts\\case_check.py --serverinfo ...\\serverinfo.txt ^
              --case demo_coarse.cas.h5 --data demo_coarse.dat.h5 --json check.json
3) 不连 Fluent，只看网格拓扑（读不到求解设置）：
       python scripts\\case_check.py --case-only demo_coarse.cas.h5

退出码：0 全部符合；1 有与期望不符；2 连接/读取失败。
本脚本**不会**关闭 Fluent 会话（不调用 exit）。
"""
import argparse
import os
import sys

OK, WARN, BAD = "[OK]  ", "[WARN]", "[FAIL]"


class Report:
    def __init__(self):
        self.n_warn = 0
        self.n_bad = 0

    def item(self, name, got, expect=None):
        ok = True if expect is None else str(got) == str(expect)
        print(f"{OK if ok else WARN} {name:<26} = {got!r}" + (f"   期望 {expect!r}" if expect is not None else ""))
        if not ok:
            self.n_warn += 1
        return ok

    def fail(self, name, err):
        self.n_bad += 1
        print(f"{BAD} {name:<26} {type(err).__name__}: {err}")


def num(v):
    try:
        return f"{float(v):.6g}"
    except Exception:
        return v


def check_live(s, a, rep):
    dump = {}

    print("=" * 70)
    print(" 1. 网格")
    print("=" * 70)
    try:
        mstate = s.settings.mesh.get_state()
        dump["mesh"] = mstate
        dump["mesh_state_keys"] = list(mstate)[:8] if isinstance(mstate, dict) else None
    except Exception as e:
        rep.fail("mesh.get_state", e)

    print()
    print("=" * 70)
    print(" 2. 求解设置")
    print("=" * 70)
    try:
        g = s.settings.setup.general.get_state()
        sol = g.get("solver", {})
        op = g.get("operating_conditions", {})
        dump["general"] = g
        rep.item("求解器 type", sol.get("type"), "pressure-based")
        rep.item("时间 time", sol.get("time"), "steady")
        rep.item("2D 空间", sol.get("two_dim_space"), "axisymmetric")
        rep.item("速度公式", sol.get("velocity_formulation"))
        rep.item("操作压力 Pa", num(op.get("operating_pressure")), "0")
        rep.item("重力", op.get("gravity", {}).get("enable"), False)
    except Exception as e:
        rep.fail("general.get_state", e)

    try:
        md = s.settings.setup.models.get_state()
        dump["models"] = md
        rep.item("能量方程", md.get("energy", {}).get("enabled"), True)
        rep.item("粘性模型", md.get("viscous", {}).get("model"), "k-omega")
        rep.item("k-omega 子模型", md.get("viscous", {}).get("k_omega_model"), "sst")
        rep.item("壁面 omega 处理", md.get("viscous", {}).get("near_wall_treatment", {}).get("wall_omega_treatment"))
        rep.item("多相模型", md.get("multiphase", {}).get("models"))
    except Exception as e:
        rep.fail("models.get_state", e)

    print()
    print("=" * 70)
    print(" 3. 边界条件（gauge 压力；绝对 = gauge + 操作压力）")
    print("=" * 70)
    bc = s.settings.setup.boundary_conditions
    for kind in ("pressure_inlet", "pressure_outlet", "velocity_inlet", "wall", "axis"):
        obj = getattr(bc, kind, None)
        if obj is None:
            continue
        try:
            st = obj.get_state()
        except Exception as e:
            # 该类型下没有 zone 时会报 "the object is not active"，属正常
            if "not active" not in str(e):
                rep.fail(f"{kind}.get_state", e)
            continue
        if not st:
            continue
        for zname, z in st.items():
            mom = z.get("momentum", {})
            _pkey = "gauge_total_pressure" if kind == "pressure_inlet" else "gauge_pressure"
            gp = mom.get(_pkey, {}) or {}
            _lab = "总压" if kind == "pressure_inlet" else "静压"
            if kind in ("pressure_inlet", "pressure_outlet"):
                print(f"  - {zname}  ({kind})   {_lab} = {num(gp.get('value'))} Pa")
            else:
                print(f"  - {zname}  ({kind})")
            dump[f"{kind}:{zname}"] = {"p": gp.get("value")}
            if kind in ("pressure_inlet", "pressure_outlet"):
                _tk = "total_temperature" if kind == "pressure_inlet" else "backflow_total_temperature"
                t0 = (z.get("thermal") or {}).get(_tk, {}) or {}
                if t0.get("value") is not None:
                    rep.item(f"    {zname} " + ("总温" if kind == "pressure_inlet" else "回流总温") + " / K", num(t0.get("value")))
                turb = z.get("turbulence") or {}
                for k in ("turbulent_intensity", "hydraulic_diameter"):
                    if isinstance(turb.get(k), dict) and turb[k].get("value") is not None:
                        rep.item(f"    {k}", num(turb[k]["value"]))

    print()
    print("=" * 70)
    print(" 4. 单元区（应为 fluid；出现 solid 说明网格没被识别成流体域）")
    print("=" * 70)
    try:
        cz = s.settings.setup.cell_zone_conditions.get_state()
        dump["cell_zones"] = list(cz.keys())
        for kind, zones in cz.items():
            print(f"  - {kind}: {list(zones.keys())}")
            for zn, zv in zones.items():
                mat = (zv.get("general") or {}).get("material")
                rep.item(f"    {zn} 材料", mat)
    except Exception as e:
        rep.fail("cell_zone_conditions", e)

    if a.json:
        import json
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n设置已存：{a.json}")

    print()
    print("-" * 70)
    print(f"结论：{rep.n_warn} 项与期望不符，{rep.n_bad} 项读取失败")
    print("-" * 70)
    return 0 if (rep.n_warn == 0 and rep.n_bad == 0) else 1


def check_file(path, rep):
    try:
        import h5py
        import numpy as np
    except Exception as e:
        print(f"{BAD} 需要 h5py/numpy: {e}")
        return 2
    if not os.path.isfile(path):
        print(f"文件不存在：{path}")
        return 2
    print(f"文件：{path}")
    try:
        with h5py.File(path, "r") as f:
            zt = f["meshes/1/faces/zoneTopology"]
            names = [s for s in zt["name"][()][0].decode("utf-8", "replace").split(";") if s]
            mn = np.atleast_1d(zt["minId"][()])
            mx = np.atleast_1d(zt["maxId"][()])
            cg = f["meshes/1/nodes/coords"]
            co = cg[sorted(cg.keys())[0]][()]
            nn = co.shape[0]
            c0 = f["meshes/1/faces/c0/1"][()]
        print(f"{OK} 节点 {nn}，面 {len(c0)}，单元约 {int(np.max(c0))}")
        print(f"{OK} 面区 {len(names)} 个：")
        for nm, aa, bb in zip(names, mn, mx):
            print(f"       {nm:<22} 面 {int(bb - aa)}")
    except Exception as e:
        rep.fail("h5 结构", e)
        return 1
    print("注：--case-only 只看拓扑；求解设置要连 Fluent（--serverinfo）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Fluent case 自检（只读，不改设置）")
    ap.add_argument("--serverinfo")
    ap.add_argument("--case")
    ap.add_argument("--data")
    ap.add_argument("--case-only")
    ap.add_argument("--json")
    a = ap.parse_args()

    rep = Report()
    if a.case_only:
        return check_file(a.case_only, rep)
    if not a.serverinfo or not os.path.isfile(a.serverinfo):
        print("需要 --serverinfo（或用 --case-only 只读文件）")
        return 2

    try:
        import ansys.fluent.core as pf
    except Exception as e:
        print(f"{BAD} 导入 ansys-fluent-core 失败: {e}")
        print("      用带 pyfluent 的 python，或 pip install ansys-fluent-core==0.43.0")
        return 2

    try:
        try:
            s = pf.connect_to_fluent(server_info_file_name=a.serverinfo,
                                     allow_remote_host=True, insecure_mode=True)
        except TypeError:
            s = pf.connect_to_fluent(server_info_file_name=a.serverinfo)
    except Exception as e:
        print(f"{BAD} 连接失败: {e}")
        print("      检查：pyfluent_server.bat 是否还开着；serverinfo 里的 IP:端口 是否本机")
        return 2

    print(f"已连接：{s.get_fluent_version()}")
    if a.case:
        print(f"读入 case：{a.case}")
        print(f"[注意] 会替换当前会话里已加载的 case：{a.case}")
        s.settings.file.read_case(file_name=a.case)
        if a.data:
            print(f"读入 data：{a.data}")
            s.settings.file.read_data(file_name=a.data)
    print()
    return check_live(s, a, rep)


if __name__ == "__main__":
    sys.exit(main())