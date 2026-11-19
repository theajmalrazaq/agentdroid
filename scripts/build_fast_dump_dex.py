#!/usr/bin/env python3
"""Build a self-contained non-blocking Android UI dump DEX (`agentdroid-fast-dump.dex`).

Runs persistently via `app_process` (`CLASSPATH=/system/framework/uiautomator.jar:...`)
using `UiAutomation.connect(FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES=1)` and
`AccessibilityNodeInfoDumper.dumpWindowsToFile(...)` WITHOUT `waitForIdle()`, eliminating
the 3-20s `adb shell uiautomator dump` stall while keeping ArtemisAccessibilityService active.

Protocol (UTF-8 newline-delimited over loopback 127.0.0.1:18890):
    <token>\\tping  -> OK pong\\n
    <token>\\tdump  -> OK <byte_len>\\n<raw_xml_bytes>
"""

from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_input_daemon_dex import Asm, MethodDef, compile_dex  # noqa: E402

OUT_DEX = REPO_ROOT / "packages" / "agentdroid-fast-dump" / "agentdroid-fast-dump.dex"


def build_fast_dump_dex() -> bytes:
    CLS = "Lcom/agentdroid/FastDump;"
    OBJ = "Ljava/lang/Object;"
    STR = "Ljava/lang/String;"
    HT = "Landroid/os/HandlerThread;"
    LOOP = "Landroid/os/Looper;"
    UAC = "Landroid/app/UiAutomationConnection;"
    IUAC = "Landroid/app/IUiAutomationConnection;"
    UA = "Landroid/app/UiAutomation;"
    ASI = "Landroid/accessibilityservice/AccessibilityServiceInfo;"
    DMG = "Landroid/hardware/display/DisplayManagerGlobal;"
    SA = "Landroid/util/SparseArray;"
    DUMPER = "Lcom/android/uiautomator/core/AccessibilityNodeInfoDumper;"
    FILE = "Ljava/io/File;"
    FR = "Ljava/io/FileReader;"
    FIS = "Ljava/io/FileInputStream;"
    IS = "Ljava/io/InputStream;"
    OS = "Ljava/io/OutputStream;"
    ISR = "Ljava/io/InputStreamReader;"
    BR = "Ljava/io/BufferedReader;"
    SOCK = "Ljava/net/Socket;"
    SSOCK = "Ljava/net/ServerSocket;"
    INET = "Ljava/net/InetAddress;"
    SYS = "Ljava/lang/System;"
    PS = "Ljava/io/PrintStream;"
    SB = "Ljava/lang/StringBuilder;"

    fields = [
        ("sToken", STR, 0x0008),
        ("sUiAuto", UA, 0x0008),
        ("sDmg", DMG, 0x0008),
        ("sOutFile", FILE, 0x0008),
    ]

    # 1. handleClient(Socket sock)
    def emit_handle_client(a: Asm) -> None:
        # ins=1 (v15=sock), regs=16, outs=4
        # v14=br, v13=os, v12=line, v11=parts, v10=cmd
        a.label("try_setup_start")
        a.const4(0, 1)
        a.invoke_virtual([15, 0], SOCK, "setTcpNoDelay", "V", ["Z"])
        a.invoke_virtual([15], SOCK, "getInputStream", IS, [])
        a.move_res_obj(0)
        a.new_inst(1, ISR)
        a.const_str(2, "UTF-8")
        a.invoke_direct([1, 0, 2], ISR, "<init>", "V", [IS, STR])
        a.new_inst(14, BR)
        a.invoke_direct([14, 1], BR, "<init>", "V", ["Ljava/io/Reader;"])
        a.invoke_virtual([15], SOCK, "getOutputStream", OS, [])
        a.move_res_obj(13)

        a.invoke_virtual([14], BR, "readLine", STR, [])
        a.move_res_obj(12)
        a.label("try_setup_end")
        a.if_eqz(12, "close_sock")

        a.label("try_start")

        a.const_str(0, "\t")
        a.const4(1, -1)
        a.invoke_virtual([12, 0, 1], STR, "split", f"[{STR}", [STR, "I"])
        a.move_res_obj(11)
        a.array_len(0, 11)
        a.const4(1, 2)
        a.if_lt(0, 1, "auth_fail")
        a.sget_obj(0, CLS, "sToken", STR)
        a.const4(1, 0)
        a.aget_obj(1, 11, 1)
        a.invoke_virtual([0, 1], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_nez(0, "auth_ok")

        a.label("auth_fail")
        a.const_str(0, "ERR auth\n")
        a.goto("write_str")

        a.label("auth_ok")
        a.const4(0, 1)
        a.aget_obj(10, 11, 0)

        a.const_str(0, "ping")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "not_ping")
        a.const_str(0, "OK pong\n")
        a.goto("write_str")

        a.label("not_ping")
        a.const_str(0, "dump")
        a.invoke_virtual([0, 10], STR, "equals", "Z", [OBJ])
        a.move_res(0)
        a.if_eqz(0, "unknown_cmd")

        # sUiAuto.getWindowsOnAllDisplays() -> AccessibilityNodeInfoDumper.dumpWindowsToFile
        a.sget_obj(0, CLS, "sUiAuto", UA)
        a.invoke_virtual([0], UA, "getWindowsOnAllDisplays", SA, [])
        a.move_res_obj(0)
        a.sget_obj(1, CLS, "sOutFile", FILE)
        a.sget_obj(2, CLS, "sDmg", DMG)
        a.invoke_static([0, 1, 2], DUMPER, "dumpWindowsToFile", "V", [SA, FILE, DMG])

        # Write "OK <len>\n"
        a.sget_obj(0, CLS, "sOutFile", FILE)
        a.invoke_virtual([0], FILE, "length", "J", [])
        a.move_res_wide(2)  # v2:3 = length
        a.new_inst(4, SB)
        a.invoke_direct([4], SB, "<init>", "V", [])
        a.const_str(5, "OK ")
        a.invoke_virtual([4, 5], SB, "append", SB, [STR])
        a.invoke_virtual([4, 2, 3], SB, "append", SB, ["J"])
        a.const_str(5, "\n")
        a.invoke_virtual([4, 5], SB, "append", SB, [STR])
        a.invoke_virtual([4], SB, "toString", STR, [])
        a.move_res_obj(4)
        a.const_str(5, "UTF-8")
        a.invoke_virtual([4, 5], STR, "getBytes", "[B", [STR])
        a.move_res_obj(4)
        a.invoke_virtual([13, 4], OS, "write", "V", ["[B"])

        # Stream file bytes in 8192-byte buffer
        a.new_inst(4, FIS)
        a.invoke_direct([4, 0], FIS, "<init>", "V", [FILE])  # v4 = FileInputStream
        a.const16(5, 8192)
        a.new_array(6, 5, "[B")  # v6 = byte[8192]
        a.label("copy_loop")
        a.invoke_virtual([4, 6], FIS, "read", "I", ["[B"])
        a.move_res(7)
        a.if_ltz(7, "copy_done")
        a.const4(8, 0)
        a.invoke_virtual([13, 6, 8, 7], OS, "write", "V", ["[B", "I", "I"])
        a.goto("copy_loop")

        a.label("copy_done")
        a.invoke_virtual([4], FIS, "close", "V", [])
        a.invoke_virtual([13], OS, "flush", "V", [])
        a.goto("close_sock")

        a.label("unknown_cmd")
        a.const_str(0, "ERR unknown_cmd\n")

        a.label("write_str")
        a.const_str(1, "UTF-8")
        a.invoke_virtual([0, 1], STR, "getBytes", "[B", [STR])
        a.move_res_obj(0)
        a.invoke_virtual([13, 0], OS, "write", "V", ["[B"])
        a.invoke_virtual([13], OS, "flush", "V", [])

        a.label("try_end")
        a.goto("close_sock")

        a.label("catch_any")
        a.move_exc(0)
        a.new_inst(1, SB)
        a.invoke_direct([1], SB, "<init>", "V", [])
        a.const_str(2, "ERR ")
        a.invoke_virtual([1, 2], SB, "append", SB, [STR])
        a.invoke_virtual([0], "Ljava/lang/Throwable;", "toString", STR, [])
        a.move_res_obj(0)
        a.invoke_virtual([1, 0], SB, "append", SB, [STR])
        a.const_str(2, "\n")
        a.invoke_virtual([1, 2], SB, "append", SB, [STR])
        a.invoke_virtual([1], SB, "toString", STR, [])
        a.move_res_obj(0)
        a.const_str(1, "UTF-8")
        a.invoke_virtual([0, 1], STR, "getBytes", "[B", [STR])
        a.move_res_obj(0)
        a.label("err_w_start")
        a.invoke_virtual([13, 0], OS, "write", "V", ["[B"])
        a.invoke_virtual([13], OS, "flush", "V", [])
        a.label("err_w_end")

        a.label("close_sock")
        a.label("cls_start")
        a.invoke_virtual([15], SOCK, "close", "V", [])
        a.label("cls_end")
        a.ret_void()
        a.label("catch_cls")
        a.move_exc(0)
        a.ret_void()

        a.try_catch("try_setup_start", "try_setup_end", [(None, "catch_cls")])
        a.try_catch("try_start", "try_end", [(None, "catch_any")])
        a.try_catch("err_w_start", "err_w_end", [(None, "catch_cls")])
        a.try_catch("cls_start", "cls_end", [(None, "catch_cls")])

    # 2. main(String[] args)
    def emit_main(a: Asm) -> None:
        # ins=1 (v8=args), regs=9, outs=4
        a.const4(5, 0)
        a.aget_obj(0, 8, 5)
        a.invoke_static([0], "Ljava/lang/Integer;", "parseInt", "I", [STR])
        a.move_res(0)  # v0 = port

        a.const4(5, 1)
        a.aget_obj(1, 8, 5)  # v1 = tokenPath

        # Read token
        a.new_inst(2, FR)
        a.invoke_direct([2, 1], FR, "<init>", "V", [STR])
        a.new_inst(3, BR)
        a.invoke_direct([3, 2], BR, "<init>", "V", ["Ljava/io/Reader;"])
        a.invoke_virtual([3], BR, "readLine", STR, [])
        a.move_res_obj(4)
        a.invoke_virtual([3], BR, "close", "V", [])
        a.invoke_virtual([4], STR, "trim", STR, [])
        a.move_res_obj(4)
        a.sput_obj(4, CLS, "sToken", STR)

        # HandlerThread + UiAutomation.connect(1 = FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
        a.new_inst(2, HT)
        a.const_str(3, "agentdroid-fastdump")
        a.invoke_direct([2, 3], HT, "<init>", "V", [STR])
        a.invoke_virtual([2], HT, "start", "V", [])
        a.invoke_virtual([2], HT, "getLooper", LOOP, [])
        a.move_res_obj(3)  # v3 = Looper
        a.new_inst(4, UAC)
        a.invoke_direct([4], UAC, "<init>", "V", [])  # v4 = UiAutomationConnection
        a.new_inst(5, UA)
        a.invoke_direct([5, 3, 4], UA, "<init>", "V", [LOOP, IUAC])
        a.const4(6, 1)
        a.invoke_virtual([5, 6], UA, "connect", "V", ["I"])
        a.invoke_virtual([5], UA, "getServiceInfo", ASI, [])
        a.move_res_obj(6)
        a.if_eqz(6, "skip_flags")
        a.iget(7, 6, ASI, "flags", "I")
        a.or_int_lit8(7, 7, 64)
        a.iput(7, 6, ASI, "flags", "I")
        a.invoke_virtual([5, 6], UA, "setServiceInfo", "V", [ASI])
        a.label("skip_flags")
        a.sput_obj(5, CLS, "sUiAuto", UA)

        a.invoke_static([], DMG, "getInstance", DMG, [])
        a.move_res_obj(4)
        a.sput_obj(4, CLS, "sDmg", DMG)

        a.new_inst(4, FILE)
        a.const_str(5, "/data/local/tmp/.agentdroid_fast_ui.xml")
        a.invoke_direct([4, 5], FILE, "<init>", "V", [STR])
        a.sput_obj(4, CLS, "sOutFile", FILE)

        # ServerSocket(port, 50, InetAddress.getByName("127.0.0.1"))
        a.const_str(4, "127.0.0.1")
        a.invoke_static([4], INET, "getByName", INET, [STR])
        a.move_res_obj(4)
        a.new_inst(2, SSOCK)
        a.const16(5, 50)
        a.invoke_direct([2, 0, 5, 4], SSOCK, "<init>", "V", ["I", "I", INET])

        a.sget_obj(4, SYS, "out", PS)
        a.const_str(5, "READY")
        a.invoke_virtual([4, 5], PS, "println", "V", [STR])

        a.label("accept_loop")
        a.invoke_virtual([2], SSOCK, "accept", SOCK, [])
        a.move_res_obj(3)
        a.invoke_static([3], CLS, "handleClient", "V", [SOCK])
        a.goto("accept_loop")

    methods = [
        MethodDef(CLS, "handleClient", "V", [SOCK], 0x000A, 16, 1, 4, False, emit_handle_client),
        MethodDef(CLS, "main", "V", [f"[{STR}"], 0x0009, 9, 1, 4, False, emit_main),
    ]

    return compile_dex(CLS, OBJ, [], fields, methods)


def main() -> None:
    dex_bytes = build_fast_dump_dex()
    OUT_DEX.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEX.write_bytes(dex_bytes)
    print(f"Wrote {OUT_DEX} ({len(dex_bytes)} bytes)")


if __name__ == "__main__":
    main()
