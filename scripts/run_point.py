# -*- coding: utf-8 -*-
"""在已配置好的算例上跑一个背压点，写出 case+data。

带 --data 时从已有结果续算（不重新初始化）；不带则只读 case。
每次都会把 6 个残差判据压到 1e-12，防止"读入已收敛场 → 一步就收敛"的假收敛。

用法:
    python run_point.py --serverinfo s.txt --case a.cas.h5 --data a.dat.h5 \
        --p 90000 --iters 800 --out bg_090.cas.h5 [--init] [--zone outlet-mix]
"""
import argparse
import warnings

warnings.filterwarnings("ignore")
import ansys.fluent.core as pf  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serverinfo", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--data", default=None)
    ap.add_argument("--p", type=float, required=True, help="出口表压 Pa（记为背压）")
    ap.add_argument("--iters", type=int, default=800)
    ap.add_argument("--init", action="store_true", help="先做 hybrid 初始化")
    ap.add_argument("--out", required=True)
    ap.add_argument("--zone", default="outlet-mix")
    a = ap.parse_args()

    s = pf.connect_to_fluent(
        server_info_file_name=a.serverinfo, allow_remote_host=True, insecure_mode=True
    )
    print("connected:", s.get_fluent_version())

    if a.data:
        s.file.read_case_data(file_name=a.case, data_file_name=a.data)
    else:
        s.file.read_case(file_name=a.case)

    po = s.settings.setup.boundary_conditions.pressure_outlet
    st = po.get_state()
    if a.zone not in st:
        raise SystemExit(f"没有压力出口区 {a.zone!r}；现有: {sorted(st)}"
                         f"（用 --zone 指定，或用 omega.py --list-zones 看面区名）")
    st[a.zone]["momentum"]["gauge_pressure"] = {"option": "value", "value": float(a.p)}
    po.set_state(st)
    print("p_out =", a.p, "Pa  (zone:", a.zone + ")")

    s.tui.solve.monitors.residual.convergence_criteria(
        1e-12, 1e-12, 1e-12, 1e-12, 1e-12, 1e-12
    )
    if a.init:
        s.tui.solve.initialize.hyb_initialization()
    s.tui.solve.iterate(a.iters)
    s.file.write_case_data(file_name=a.out)
    print("written:", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
