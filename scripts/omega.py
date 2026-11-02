# -*- coding: utf-8 -*-
"""从 case+data 离线算引射系数 ω 与主要性能量（不需要连 Fluent、不依赖外部脚本）。

只依赖 numpy + h5py，直接读 Fluent 的 .cas.h5 / .dat.h5：
  mp = 一次流(负号取正)、ms = 二次流、ω = ms/mp、出口加权平均 T/p/V、出口 Ma 与滞止压 p0

用法:
    python omega.py case.cas.h5 case.dat.h5            # 单个
    python omega.py case.cas.h5 case.dat.h5 101kPa     # 带标签
    python omega.py --batch "90,c1.cas.h5,c1.dat.h5" "95,c2.cas.h5,c2.dat.h5"
    python omega.py --list-zones case.cas.h5           # 看区名（判断 inlet/outlet 叫什么）
可选:
    --in-p 名称1,名称2 | --in-s 名称     一次流 / 二次流区名（默认 inlet-primary / inlet-secondary）
    --out 名称                            出口区名（默认 outlet-mix）
    --R 461.53 --gamma 1.13               蒸汽物性（默认值适用于水蒸气）

判读: ω>0 起动；ω≈0 对应临界背压；ω<0 说明出口倒灌（未起动）。
"""
from __future__ import annotations

import argparse
import sys

import h5py
import numpy as np

R_DEF, GAM_DEF = 461.53, 1.13


# ---------------------------------------------------------------- 读取
def load(cas, dat=None):
    with h5py.File(cas, "r") as c:
        cg = c["meshes/1/nodes/coords"]
        co = cg[sorted(cg.keys())[0]][()]
        nn = c["meshes/1/faces/nodes/1/nnodes"][()]
        fn = c["meshes/1/faces/nodes/1/nodes"][()]
        c0 = c["meshes/1/faces/c0/1"][()]
        zt = c["meshes/1/faces/zoneTopology"]
        names = [s for s in zt["name"][()][0].decode("utf-8", "replace").split(";") if s]
        mn = np.atleast_1d(zt["minId"][()])
        mx = np.atleast_1d(zt["maxId"][()])
    if dat is None:
        return dict(co=co, nn=nn, fn=fn, c0=c0, names=names, mn=mn, mx=mx)
    with h5py.File(dat, "r") as d:
        g = d["results/1/phase-1/cells"]
        out = dict(
            rho=g["SV_DENSITY/1"][()],
            U=g["SV_U/1"][()],
            V=g["SV_V/1"][()],
            P=g["SV_P/1"][()],
            T=g["SV_T/1"][()],
        )
    out.update(dict(co=co, nn=nn, fn=fn, c0=c0, names=names, mn=mn, mx=mx))
    return out


def face_geometry(m):
    """返回每个面的两端点、中心、长度、中点半径。"""
    co, nn, fn = m["co"], m["nn"], m["fn"]
    off = np.concatenate([[0], np.cumsum(nn)])
    i0 = fn[off[:-1]]
    i1 = fn[np.maximum(off[1:] - 1, 0)]
    p0 = co[i0 - 1]
    p1 = co[i1 - 1]
    cen = 0.5 * (p0 + p1)
    L = np.hypot(p1[:, 0] - p0[:, 0], p1[:, 1] - p0[:, 1])
    rc = 0.5 * (p0[:, 1] + p1[:, 1])
    return p0, p1, cen, L, rc


def cell_centers(m):
    _, _, cen, _, _ = face_geometry(m)
    c0 = m["c0"]
    ncell = max(int(c0.max()), 1)
    cs = np.zeros((ncell, 2))
    cn = np.zeros(ncell)
    ok = (c0 >= 1) & (c0 <= ncell)
    np.add.at(cs, c0[ok] - 1, cen[ok])
    np.add.at(cn, c0[ok] - 1, 1.0)
    return cs / np.maximum(cn, 1)[:, None]


def zone_fluxes(m, rho, U, V):
    """按面区计算质量流量（2πr 轴对称），返回 {区名: (流量, 面索引, 单元索引, 面积)}。"""
    p0, p1, cen, L, rc = face_geometry(m)
    cc = cell_centers(m)
    c0, mn, mx, names = m["c0"], m["mn"], m["mx"], m["names"]
    nc = len(rho)
    res = {}
    for k in range(len(mn)):
        name = names[k] if k < len(names) else "?"
        a, b = int(mn[k]), int(mx[k])
        if b - a + 1 > 5000:          # 适配网格留下的 inactive parent 区，跳过
            continue
        idx = np.arange(a - 1, b)
        idx = idx[c0[idx] <= nc]
        if not len(idx):
            continue
        nx_ = (p1[idx, 1] - p0[idx, 1]) / np.maximum(L[idx], 1e-30)
        nr_ = -(p1[idx, 0] - p0[idx, 0]) / np.maximum(L[idx], 1e-30)
        out = cen[idx] - cc[c0[idx] - 1]
        flip = (nx_ * out[:, 0] + nr_ * out[:, 1]) < 0
        nx_[flip] *= -1
        nr_[flip] *= -1
        cid = c0[idx] - 1
        area = 2.0 * np.pi * rc[idx] * L[idx]
        res[name] = (float((rho[cid] * (U[cid] * nx_ + V[cid] * nr_) * area).sum()),
                     idx, cid, area)
    return res


def evaluate(cas, dat, label="case", in_p=("inlet-primary",), in_s=("inlet-secondary",),
             out="outlet-mix", R=R_DEF, gam=GAM_DEF):
    m = load(cas, dat)
    res = zone_fluxes(m, m["rho"], m["U"], m["V"])
    missing = [z for z in list(in_p) + list(in_s) + [out] if z not in res]
    if missing:
        raise KeyError(f"区名不存在: {missing}；可用区名: {sorted(res)}")
    mp = -sum(res[z][0] for z in in_p)
    ms = -sum(res[z][0] for z in in_s)
    _, idx, cid, area = res[out]
    om = ms / mp if abs(mp) > 0 else float("nan")
    if len(idx):
        Vo = np.hypot(m["U"][cid], m["V"][cid])
        To = float(np.average(m["T"][cid], weights=area))
        po = float(np.average(m["P"][cid], weights=area))
        Vw = float(np.average(Vo, weights=area))
        Mo = Vw / np.sqrt(gam * R * To)
        p0o = po * (1 + 0.5 * (gam - 1) * Mo ** 2) ** (gam / (gam - 1))
    else:
        To = Mo = p0o = float("nan")
    return dict(label=label, mp=mp, ms=ms, omega=om, Tout=To, Ma=Mo, p0=p0o)


HEAD = "{:<12}{:>13}{:>13}{:>9}{:>9}{:>8}{:>11}"


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="<cas.h5> <dat.h5> [label]")
    ap.add_argument("--batch", nargs="*", default=None, help='"label,cas,dat" ...')
    ap.add_argument("--list-zones", metavar="CAS", default=None)
    ap.add_argument("--in-p", default="inlet-primary")
    ap.add_argument("--in-s", default="inlet-secondary")
    ap.add_argument("--out", default="outlet-mix")
    ap.add_argument("--R", type=float, default=R_DEF)
    ap.add_argument("--gamma", type=float, default=GAM_DEF)
    a = ap.parse_args()

    if a.list_zones:
        m = load(a.list_zones)
        _, _, _, L, rc = face_geometry(m)
        print("{:<24}{:>10}{:>10}".format("zone", "faces", "span[mm]"))
        for k in range(len(m["mn"])):
            lo, hi = int(m["mn"][k]) - 1, int(m["mx"][k])
            nm = m["names"][k] if k < len(m["names"]) else "?"
            if hi - lo > 5000:
                continue
            print("{:<24}{:>10}{:>10.1f}".format(nm, hi - lo, 1e3 * L[lo:hi].sum()))
        return 0

    items = list(a.batch) if a.batch else []
    if not items and len(a.files) >= 2:
        label = a.files[2] if len(a.files) > 2 else "case"
        items = [f"{label},{a.files[0]},{a.files[1]}"]
    if not items:
        ap.print_help()
        return 2

    ip = tuple(x.strip() for x in a.in_p.split(",") if x.strip())
    isx = tuple(x.strip() for x in a.in_s.split(",") if x.strip())
    print(HEAD.format("stage", "mp[kg/s]", "ms[kg/s]", "omega", "Tout[K]", "MaOut", "p0out[Pa]"))
    rc = 0
    for it in items:
        parts = it.split(",")
        if len(parts) != 3:
            print("bad item (need label,cas,dat):", it)
            rc = 2
            continue
        label, cas, dat = (p.strip() for p in parts)
        try:
            r = evaluate(cas, dat, label, ip, isx, a.out, a.R, a.gamma)
        except Exception as exc:                      # noqa: BLE001
            print(f"{label:<12} 失败: {type(exc).__name__}: {exc}")
            rc = 1
            continue
        print("{:<12}{:>13.5e}{:>13.5e}{:>9.4f}{:>9.1f}{:>8.3f}{:>11.0f}".format(
            r["label"], r["mp"], r["ms"], r["omega"], r["Tout"], r["Ma"], r["p0"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
