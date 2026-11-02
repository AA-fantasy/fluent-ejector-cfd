# -*- coding: utf-8 -*-
"""从一维设计尺寸生成 2D 轴对称引射器轮廓（半剖，mm）→ DXF + 可选预览图。

输入的 9 个关键尺寸（索科洛夫方法输出）：
  dp    喷嘴临界（喉部）直径
  dp1   喷嘴出口直径
  d2    混合室入口（第二喉道）直径
  d3    混合室出口直径
  dc    扩压器出口直径
  le    喷嘴扩张段长度
  gap   喉嘴距（喷嘴出口 → 混合室入口）
  lk    圆柱混合室长度
  lce   扩压段长度

设计表通常不写、需要假设的三个量（本脚本带默认值并在输出里声明）：
  dpi   喷嘴入口直径      （默认 2.0*dp，误差只影响收缩段长度）
  dHi   吸入室直径        （默认 1.7*dpi）
  wall  喷嘴壁厚          （默认 12 mm）
  half  收缩段半角        （默认 30°，喷嘴收缩段与吸入室收缩段共用）

用法：
  # 示例尺寸为一台虚构的引射器，仅演示参数顺序（不是任何真实设计）
  python gen_profile_dxf.py --dp 12 --dp1 16.4 --d2 30 --d3 30.05 --dc 71 \
      --le 28 --gap 42 --lk 195 --lce 268 --out demo.dxf

  # 带工况校核（壅塞流量、出口流速）
  python gen_profile_dxf.py ... --p0 300000 --T0 400 --k 1.13 --mw 18.015 \
      --mdot-p 0.05 --u 0.6 --p-out 100000 --T-out 380

输出：
  <out>.dxf        轮廓（LINE 线段，单位 mm）
  <out>_stations.json  5 个关键 x 站位 + 半径，供后续切分/命名使用
  <out>_profile.png    预览图（需要 matplotlib，缺了自动跳过）
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

R_GAS = 8314.0  # J/(kmol·K)


def write_dxf(path: str, poly: list[tuple[float, float]]) -> None:
    """写最小可用 DXF：只有 LINE 实体，单位 mm。"""

    def g(f, code, value):
        f.write("%s\n%s\n" % (code, value))

    with open(path, "w", encoding="ascii", newline="") as f:
        g(f, 0, "SECTION"); g(f, 2, "HEADER")
        g(f, 9, "$INSUNITS"); g(f, 70, 4)  # 4 = mm
        g(f, 0, "ENDSEC")
        g(f, 0, "SECTION"); g(f, 2, "TABLES")
        g(f, 0, "TABLE"); g(f, 2, "LTYPE"); g(f, 70, 1)
        g(f, 0, "LTYPE"); g(f, 2, "CONTINUOUS"); g(f, 70, 64)
        g(f, 3, "Solid line"); g(f, 72, 65); g(f, 73, 0); g(f, 40, 0.0)
        g(f, 0, "ENDTAB"); g(f, 0, "ENDSEC")
        g(f, 0, "SECTION"); g(f, 2, "ENTITIES")
        for a, b in zip(poly[:-1], poly[1:]):
            g(f, 0, "LINE"); g(f, 8, "0")
            g(f, 10, "%.6f" % a[0]); g(f, 20, "%.6f" % a[1]); g(f, 30, "0.0")
            g(f, 11, "%.6f" % b[0]); g(f, 21, "%.6f" % b[1]); g(f, 31, "0.0")
        g(f, 0, "ENDSEC"); g(f, 0, "EOF")


def build(a) -> dict:
    dp, dp1, d2 = a.dp, a.dp1, a.d2
    d3 = a.d3 if a.d3 else d2
    dc, le, gap, lk, lce = a.dc, a.le, a.gap, a.lk, a.lce
    dpi = a.dpi if a.dpi else 2.0 * dp
    dHi = a.dHi if a.dHi else 1.7 * dpi
    wall, half = a.wall, a.half

    r_in, r_th, r_ex = dpi / 2.0, dp / 2.0, dp1 / 2.0
    r_mix, r_out, r_ch = d2 / 2.0, dc / 2.0, dHi / 2.0
    t = math.tan(math.radians(half))

    x_th = (r_in - r_th) / t          # 喉部
    x_ex = x_th + le                  # 喷嘴出口
    x_mi = x_ex + gap                 # 混合室入口（第二喉道）
    x_mo = x_mi + lk                  # 混合室出口
    x_ou = x_mo + lce                 # 扩压器出口
    x_ch = x_mi - (r_ch - r_mix) / t  # 吸入室收缩起点

    r_wi, r_wt, r_we = r_in + wall, r_th + wall, r_ex + wall

    poly = [
        (0.0, 0.0), (x_ou, 0.0), (x_ou, r_out), (x_mo, r_mix), (x_mi, r_mix),
        (x_ch, r_ch), (0.0, r_ch), (0.0, r_wi), (x_th, r_wt), (x_ex, r_we),
        (x_ex, r_ex), (x_th, r_th), (0.0, r_in), (0.0, 0.0),
    ]
    return dict(
        poly=poly, x_th=x_th, x_ex=x_ex, x_mi=x_mi, x_mo=x_mo, x_ou=x_ou, x_ch=x_ch,
        r_th=r_th, r_ex=r_ex, r_mix=r_mix, r_out=r_out, r_ch=r_ch,
        r_wt=r_wt, r_we=r_we, r_wi=r_wi, dpi_used=dpi, dHi_used=dHi,
    )


def report(a, s: dict) -> None:
    print("=" * 74)
    print("几何站表（mm）")
    print("-" * 74)
    print("  x: 喉部 %.3f | 喷嘴出口 %.3f | 混合室入口 %.3f | 混合室出口 %.3f | 出口 %.3f"
          % (s["x_th"], s["x_ex"], s["x_mi"], s["x_mo"], s["x_ou"]))
    print("  r: 喉部 %.3f | 喷口 %.3f | 混合室 %.3f | 扩压出口 %.3f | 吸入室 %.3f"
          % (s["r_th"], s["r_ex"], s["r_mix"], s["r_out"], s["r_ch"]))
    print("  总长 %.2f mm | 吸入室收缩起点 x=%.2f | 喷嘴外壁 r: %.2f→%.2f→%.2f"
          % (s["x_ou"], s["x_ch"], s["r_wi"], s["r_wt"], s["r_we"]))
    if not a.dpi:
        print("  ⚠ 未给 dpi，已假设 dpi = 2.0*dp = %.2f" % s["dpi_used"])
    if not a.dHi:
        print("  ⚠ 未给 dHi，已假设 dHi = 1.7*dpi = %.2f" % s["dHi_used"])

    ar = (a.d2 / a.dp) ** 2
    ld = a.lk / a.d2
    ang_d = math.degrees(math.atan((s["r_out"] - s["r_mix"]) / a.lce))
    ang_n = math.degrees(math.atan((s["r_ex"] - s["r_th"]) / a.le))
    print("-" * 74)
    print("几何自检")
    print("  截面比 (d2/dp)^2 = %.3f   （设计值对照，偏差 >2%% 要复核）" % ar)
    print("  混合室 L/D       = %.2f    （经验 5~8 较稳）" % ld)
    print("  喷嘴扩张半角     = %.2f°  （经验 4~6°）" % ang_n)
    print("  扩压段半角       = %.2f°  （经验 3~6°）" % ang_d)
    print("  总长/喉径        = %.1f" % (s["x_ou"] / a.dp))

    if a.p0 and a.T0 and a.k and a.mdot_p:
        k, mw = a.k, a.mw
        crit = (2.0 / (k + 1.0)) ** ((k + 1.0) / (2.0 * (k - 1.0)))
        at = math.pi * s["r_th"] ** 2 * 1e-6  # mm² → m²
        mdot = at * a.p0 / math.sqrt(a.T0) * math.sqrt(k / (R_GAS / mw)) * crit
        print("-" * 74)
        print("工况自检")
        print("  喉部壅塞理论一次流 = %.4f kg/s" % mdot)
        print("  给定一次流         = %.4f kg/s  （差 %+.1f%%）"
              % (a.mdot_p, (a.mdot_p - mdot) / mdot * 100.0))
        if a.u and a.p_out and a.T_out:
            rho = a.p_out / ((R_GAS / mw) * a.T_out)
            m_out = a.mdot_p * (1.0 + a.u)
            area = math.pi * s["r_out"] ** 2 * 1e-6
            print("  出口密度 %.4f kg/m³ | 面积 %.5f m² | 出口流速 %.2f m/s"
                  % (rho, area, m_out / (rho * area)))
    print("=" * 74)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="生成 2D 轴对称引射器轮廓 DXF（单位 mm）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--dp", type=float, required=True, help="喷嘴喉部直径")
    p.add_argument("--dp1", type=float, required=True, help="喷嘴出口直径")
    p.add_argument("--d2", type=float, required=True, help="混合室入口直径")
    p.add_argument("--d3", type=float, default=None, help="混合室出口直径（默认=d2）")
    p.add_argument("--dc", type=float, required=True, help="扩压器出口直径")
    p.add_argument("--le", type=float, required=True, help="喷嘴扩张段长度")
    p.add_argument("--gap", type=float, required=True, help="喉嘴距")
    p.add_argument("--lk", type=float, required=True, help="圆柱混合室长度")
    p.add_argument("--lce", type=float, required=True, help="扩压段长度")
    p.add_argument("--dpi", type=float, default=None, help="喷嘴入口直径（缺省 2*dp）")
    p.add_argument("--dHi", type=float, default=None, help="吸入室直径（缺省 1.7*dpi）")
    p.add_argument("--wall", type=float, default=12.0, help="喷嘴壁厚")
    p.add_argument("--half", type=float, default=30.0, help="收缩段半角（度）")
    p.add_argument("--out", default="profile.dxf", help="输出 DXF 路径")
    p.add_argument("--no-png", action="store_true", help="不画预览图")
    # 工况校核（可选）
    p.add_argument("--p0", type=float, help="工作蒸汽总压 Pa")
    p.add_argument("--T0", type=float, help="工作蒸汽总温 K")
    p.add_argument("--k", type=float, help="工作蒸汽比热比")
    p.add_argument("--mw", type=float, default=18.015, help="分子量")
    p.add_argument("--mdot-p", type=float, default=None, help="设计一次流 kg/s")
    p.add_argument("--u", type=float, default=None, help="设计引射系数")
    p.add_argument("--p-out", type=float, default=None, help="出口静压 Pa")
    p.add_argument("--T-out", type=float, default=None, help="出口静温 K")
    a = p.parse_args(argv)

    s = build(a)
    report(a, s)

    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_dxf(out, s["poly"])
    print("dxf -> %s" % out)

    stations = {k: round(float(s[k]), 4) for k in
                ("x_th", "x_ex", "x_mi", "x_mo", "x_ou", "x_ch",
                 "r_th", "r_ex", "r_mix", "r_out", "r_ch")}
    jp = os.path.splitext(out)[0] + "_stations.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump({"units": "mm", "design": vars(a), "stations": stations}, f,
                  ensure_ascii=False, indent=2)
    print("stations -> %s" % jp)

    if not a.no_png:
        try:
            os.environ.setdefault("MPLCONFIGDIR",
                                  os.path.join(os.path.dirname(out), ".mpl"))
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            xs = [q[0] for q in s["poly"]]
            ys = [q[1] for q in s["poly"]]
            fig, ax = plt.subplots(figsize=(12, 3.2), dpi=150)
            ax.plot(xs, ys, "-", lw=1.2, color="#1f3b73")
            ax.plot(xs, [-v for v in ys], "-", lw=1.2, color="#1f3b73")
            ax.set_aspect("equal")
            ax.grid(alpha=0.3, ls=":")
            ax.set_xlabel("x / mm"); ax.set_ylabel("r / mm"); ax.set_title("")
            fig.tight_layout()
            png = os.path.splitext(out)[0] + "_profile.png"
            fig.savefig(png)
            print("png -> %s" % png)
        except Exception as exc:  # 预览图不是必需品
            print("预览图跳过：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
