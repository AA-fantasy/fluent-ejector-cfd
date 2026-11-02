# -*- coding: utf-8 -*-
"""连上正在运行的 Fluent server，打印版本 / 求解器类型 / 区列表。

用法:
    python connect.py <serverinfo.txt>

环境:
    PYTHONPATH 需包含装了 ansys-fluent-core 的那个目录（本技能验证 0.43.0）

退出码:
    0 连上了; 1 连接失败; 2 参数问题（缺 serverinfo 或文件不存在）
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import ansys.fluent.core as pf  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if not args:
        print(__doc__)
        return 2
    si = args[0]
    if not os.path.isfile(si):
        print(f"serverinfo 不存在: {si}")
        print("先在桌面会话双击 pyfluent_server.bat，它会在 _work\\ 里生成 serverinfo.txt")
        return 2

    try:
        s = pf.connect_to_fluent(
            server_info_file_name=si, allow_remote_host=True, insecure_mode=True
        )
    except Exception as exc:  # noqa: BLE001
        print(f"连接失败: {type(exc).__name__}: {exc}")
        print("排查顺序:")
        print("  1) 那个黑窗口（Fluent 控制台）还开着吗？")
        print("  2) serverinfo.txt 是不是这次新生成的？（旧文件端口已失效）")
        print("  3) 端口是不是被防火墙拦了？先跑 doctor.py --serverinfo <文件>")
        return 1

    print("connected:", s.get_fluent_version())
    try:
        print("solver:", s.settings.setup.general.solver.type())
    except Exception as exc:  # noqa: BLE001  没有算例时会抛
        print("solver: <no case loaded>", type(exc).__name__)
    try:
        s.tui.define.boundary_conditions.list_zones()
    except Exception as exc:  # noqa: BLE001
        print("list-zones failed:", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
