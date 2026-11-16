#!/usr/bin/env python3
"""
AgentDroid Live Infrastructure & Perception Micro-Benchmark Suite.

Measures empirical latencies, APK install times, OS container cold restarts,
IPC vs ADB input roundtrips, atomic snapshots, and perception payload sizes
directly against a live local Redroid/Android instance.

Usage:
    python3 benchmarks/benchmark_agentdroid.py [--serial 127.0.0.1:5555] [--cold-starts 3]
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agentdroid.adb import AdbDevice, probe_adbd_tcp
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient

CACHE_DIR = Path.home() / ".cache" / "agentdroid" / "apks"
FOSSIFY_APK = CACHE_DIR / "org.fossify.math_10.apk"
MARKOR_APK = CACHE_DIR / "net.gsantner.markor_164.apk"
RESULTS_PATH = PROJECT_ROOT / "benchmarks" / "results" / "benchmark_agentdroid_results.json"


def summarize(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    n = len(ordered)
    p90_idx = min(n - 1, max(0, math.ceil(0.9 * n) - 1))
    return {
        "n": n,
        "median_ms": round(statistics.median(ordered), 2),
        "mean_ms": round(statistics.mean(ordered), 2),
        "min_ms": round(ordered[0], 2),
        "p90_ms": round(ordered[p90_idx], 2),
        "max_ms": round(ordered[-1], 2),
        "samples_ms": [round(x, 2) for x in samples],
    }


def wait_helper_ready(dev: AdbDevice, timeout: float = 25.0) -> AccessibilityHelperClient:
    """Wait until AccessibilityHelperClient is reachable and AccessibilityService bound."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        helper = AccessibilityHelperClient(dev)
        if helper.ensure_ready():
            return helper
        time.sleep(0.5)
    raise RuntimeError(f"AccessibilityHelperClient not ready within {timeout}s")


def measure_container_cold_starts(serial: str, container_name: str, runs: int) -> dict[str, Any]:
    """Restart the Redroid container and measure ready + first screenshot latency."""
    if runs <= 0:
        return {"skipped": True}

    ready_samples: list[float] = []
    screenshot_samples: list[float] = []
    provision_samples: list[float] = []
    tmp_shot = Path("/tmp/agentdroid_cold_start_bench.png")

    for i in range(runs):
        tmp_shot.unlink(missing_ok=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"docker restart {container_name} failed: {proc.stderr.strip()}")

        subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=3)

        # Wait until adbd replies CNXN/AUTH before invoking adb connect (prevents adb server stall
        # while docker-proxy accepts connections early) and verify sys.boot_completed + pm readiness.
        host, _, port_s = serial.rpartition(":")
        while True:
            if time.perf_counter() - t0 > 120:
                raise TimeoutError(f"Container {container_name} did not reach ready state within 120s")
            try:
                if host and port_s.isdigit() and not probe_adbd_tcp(host, int(port_s), timeout=0.35):
                    time.sleep(0.15)
                    continue
                subprocess.run(["adb", "connect", serial], capture_output=True, text=True, timeout=4)
                probe = subprocess.run(
                    [
                        "adb",
                        "-s",
                        serial,
                        "shell",
                        'if [ "$(getprop sys.boot_completed)" = "1" ]; then echo BOOT=1; pm path android; fi',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if probe.returncode == 0 and "BOOT=1" in probe.stdout and "package:" in probe.stdout:
                    break
                if probe.returncode != 0:
                    subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=2)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.15)

        ready_ms = (time.perf_counter() - t0) * 1000.0
        ready_samples.append(ready_ms)

        # Capture first non-empty PNG screenshot (cold_start_to_screenshot parity).
        shot_proc = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
        )
        if shot_proc.returncode == 0 and len(shot_proc.stdout) > 1000:
            tmp_shot.write_bytes(shot_proc.stdout)
        else:
            raise RuntimeError("screencap failed after cold restart")

        cold_to_screen_ms = (time.perf_counter() - t0) * 1000.0
        screenshot_samples.append(cold_to_screen_ms)

        # Wait briefly and re-verify helper provisioning readiness so device is clean.
        t_prov = time.perf_counter()
        dev = AdbDevice(serial=serial)
        dev.connect(timeout=5.0)
        wait_helper_ready(dev, timeout=25.0)
        provision_samples.append((time.perf_counter() - t_prov) * 1000.0)
        print(
            f"  [cold_start {i+1}/{runs}] ready={ready_ms:.1f}ms "
            f"cold_start_to_screenshot={cold_to_screen_ms:.1f}ms helper_ready={provision_samples[-1]:.1f}ms"
        )

    return {
        "container": container_name,
        "ready": summarize(ready_samples),
        "cold_start_to_screenshot": summarize(screenshot_samples),
        "post_boot_helper_ready": summarize(provision_samples),
    }


def compute_vision_tokens(width: int, height: int) -> dict[str, Any]:
    """Compute documented high-detail vision token costs from exact screen pixel dimensions."""
    # OpenAI high-detail: scale so longest <= 2048, then shortest == 768 (preserve aspect), tile 512px.
    long_side = max(width, height)
    scale = min(2048.0 / long_side, 1.0)
    w_s, h_s = width * scale, height * scale
    if min(w_s, h_s) > 768.0:
        s2 = 768.0 / min(w_s, h_s)
        w_s, h_s = w_s * s2, h_s * s2
    tiles_x = math.ceil(w_s / 512.0)
    tiles_y = math.ceil(h_s / 512.0)
    openai_tokens = 85 + 170 * (tiles_x * tiles_y)

    # Anthropic Claude vision: resize longest <= 1568, tokens ~= ceil((w * h) / 750).
    a_scale = min(1568.0 / long_side, 1.0)
    aw, ah = round(width * a_scale), round(height * a_scale)
    anthropic_tokens = math.ceil((aw * ah) / 750.0)
    return {
        "native_resolution": f"{width}x{height}",
        "openai_scaled": f"{round(w_s)}x{round(h_s)}",
        "openai_tiles": f"{tiles_x}x{tiles_y}={tiles_x * tiles_y}",
        "openai_high_detail_tokens": openai_tokens,
        "anthropic_scaled": f"{aw}x{ah}",
        "anthropic_vision_tokens": anthropic_tokens,
    }


def measure_payload_and_tokens(
    dev: AdbDevice, helper: AccessibilityHelperClient, engine: AndroidEngine
) -> dict[str, Any]:
    """Measure exact raw XML vs compact AgentDroid formatted text vs PNG screenshot sizes."""
    screens: dict[str, Any] = {}
    targets = [
        ("fossify_math", "org.fossify.math"),
        ("android_settings", "com.android.settings"),
    ]
    for label, pkg in targets:
        dev.shell(f"am force-stop {pkg}")
        dev.launch_app(pkg)
        time.sleep(1.2)

        snap = helper._request("GET", "/snapshot?fields=xml")
        if not snap.get("has_screenshot"):
            time.sleep(1.2)
            snap = helper._request("GET", "/snapshot?fields=xml")
        xml_str = snap.get("xml", "")
        png_bytes = base64.b64decode(snap.get("screenshot_base64", "") or b"")
        dump = helper.dump_compact_ui(max_elements=80)
        compact_json = json.dumps(dump.get("elements", []), separators=(",", ":"))
        screen = engine.get_screen_data(max_elements=80)
        formatted = screen.get("formatted_text", "")
        width = int(snap.get("width") or 1080)
        height = int(snap.get("height") or 2400)

        screens[label] = {
            "package": pkg,
            "node_count_xml": snap.get("node_count"),
            "element_count_compact": dump.get("element_count"),
            "raw_xml_bytes": len(xml_str.encode("utf-8")),
            "raw_xml_est_tokens_chars_div_4": math.ceil(len(xml_str) / 4),
            "compact_json_bytes": len(compact_json.encode("utf-8")),
            "formatted_text_chars": len(formatted),
            "formatted_text_est_tokens_chars_div_4": math.ceil(len(formatted) / 4),
            "screenshot_png_bytes": len(png_bytes),
            "screenshot_base64_bytes": len(snap.get("screenshot_base64", "")),
            "vision_tokens": compute_vision_tokens(width, height),
        }
    return screens


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentDroid live micro-benchmarks.")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    parser.add_argument("--container", default="agentdroid-device")
    parser.add_argument("--cold-starts", type=int, default=3)
    args = parser.parse_args()

    if not FOSSIFY_APK.exists():
        raise FileNotFoundError(f"Missing required benchmark APK: {FOSSIFY_APK}")

    dev = AdbDevice(serial=args.serial)
    if not dev.connect(timeout=5.0):
        raise RuntimeError(f"Cannot connect to ADB device {args.serial}")
    helper = wait_helper_ready(dev, timeout=25.0)
    engine = AndroidEngine(adb=dev)

    print("=== AgentDroid Micro-Benchmark Suite ===")
    results: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "device_serial": args.serial,
        "device_model": dev.shell("getprop ro.product.model").strip(),
        "android_release": dev.shell("getprop ro.build.version.release").strip(),
        "wm_size": dev.shell("wm size").strip(),
        "helper_ping": helper.ping(),
    }

    # 1. Probe direct /action tap support on this kernel/input stack
    direct_tap_resp = helper._request("POST", "/action", {"cmd": "tap", "x": 540, "y": 1200})
    input_devs = dev.shell("dumpsys input | grep -E 'Device -?[0-9]+:|Sources:'")
    has_touchscreen = "0x00001002" in input_devs
    input_daemon_ok = helper._ensure_input_daemon(force=False)
    if has_touchscreen:
        env_note = (
            "Touchscreen input source (0x00001002) present; both InputDaemon (127.0.0.1:18889) "
            "and AccessibilityService.dispatchGesture are active."
        )
    else:
        env_note = (
            "Headless Redroid registers only Virtual keyboard input (-1, 0x00000301) without host uinput; "
            "AccessibilityService.dispatchGesture returns success=False, so AccessibilityHelperClient "
            "routes tap/swipe/long_press through the persistent loop InputDaemon (127.0.0.1:18889) "
            "instead of spawning adb shell input processes."
        )
    results["environment_probes"] = {
        "helper_direct_tap_response": direct_tap_resp,
        "has_touchscreen_source": has_touchscreen,
        "input_daemon_reachable": input_daemon_ok,
        "note": env_note,
    }
    print(
        "Direct tap probe:",
        direct_tap_resp,
        "| has_touchscreen:",
        has_touchscreen,
        "| input_daemon:",
        input_daemon_ok,
    )

    # 2. Container Cold Restarts
    print(f"Measuring container cold starts (n={args.cold_starts})...")
    results["container_cold_restart"] = measure_container_cold_starts(
        args.serial, args.container, args.cold_starts
    )
    # Rebind helper/engine after container restarts
    dev = AdbDevice(serial=args.serial)
    dev.connect(timeout=5.0)
    helper = wait_helper_ready(dev, timeout=25.0)
    helper._ensure_input_daemon(force=False)
    engine = AndroidEngine(adb=dev)

    # 3. APK Installations (Fossify Math 7.0 MB matching Mobilebox, plus Markor 11.8 MB)
    print("Measuring real APK installations...")
    fossify_fresh: list[float] = []
    for _ in range(3):
        dev.shell("pm uninstall org.fossify.math")
        t0 = time.perf_counter()
        proc = dev.run_adb(["install", "-g", str(FOSSIFY_APK)], timeout=120)
        elapsed = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0 or "Success" not in proc.stdout:
            raise RuntimeError(f"Fresh Fossify Math install failed: {proc.stdout} {proc.stderr}")
        fossify_fresh.append(elapsed)

    fossify_reinstall: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        proc = dev.run_adb(["install", "-r", "-t", "-g", str(FOSSIFY_APK)], timeout=120)
        elapsed = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0 or "Success" not in proc.stdout:
            raise RuntimeError(f"Streamed reinstall Fossify Math failed: {proc.stdout} {proc.stderr}")
        fossify_reinstall.append(elapsed)

    markor_reinstall: list[float] = []
    if MARKOR_APK.exists():
        for _ in range(3):
            t0 = time.perf_counter()
            proc = dev.run_adb(["install", "-r", "-t", "-g", str(MARKOR_APK)], timeout=120)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if proc.returncode != 0 or "Success" not in proc.stdout:
                raise RuntimeError(f"Markor install failed: {proc.stdout} {proc.stderr}")
            markor_reinstall.append(elapsed)

    pkg_check_samples: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        installed = dev.is_package_installed("org.fossify.math")
        pkg_check_samples.append((time.perf_counter() - t0) * 1000.0)
        if not installed:
            raise RuntimeError("is_package_installed returned False unexpectedly")

    results["apk_operations"] = {
        "fossify_math_apk_bytes": FOSSIFY_APK.stat().st_size,
        "apk_install_fossify_math_fresh": summarize(fossify_fresh),
        "apk_install_fossify_math_reinstall": summarize(fossify_reinstall),
        "markor_apk_bytes": MARKOR_APK.stat().st_size if MARKOR_APK.exists() else None,
        "apk_install_markor_reinstall": summarize(markor_reinstall) if markor_reinstall else None,
        "package_installed_check": summarize(pkg_check_samples),
    }

    # 4. Input & Perception Micro-Benchmarks
    print("Measuring IPC, ADB input, screenshots, and UI dumps...")
    ipc_global: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        resp = helper._request("POST", "/action", {"cmd": "global", "action": "home"})
        ipc_global.append((time.perf_counter() - t0) * 1000.0)
        if not resp.get("success"):
            raise RuntimeError(f"global home IPC failed: {resp}")

    adb_tap: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        dev.shell("input tap 540 1200")
        adb_tap.append((time.perf_counter() - t0) * 1000.0)

    helper_tap: list[float] = []
    helper_tap_backends: set[str] = set()
    for _ in range(10):
        t0 = time.perf_counter()
        res = helper.action("tap", x=540, y=1200)
        helper_tap.append((time.perf_counter() - t0) * 1000.0)
        helper_tap_backends.add(str(res.get("backend", "helper_ipc")))

    ui_dump: list[float] = []
    ui_dump_internal: list[float] = []
    dev.launch_app("org.fossify.math")
    time.sleep(0.8)
    for _ in range(20):
        t0 = time.perf_counter()
        d = helper.dump_compact_ui(max_elements=80)
        ui_dump.append((time.perf_counter() - t0) * 1000.0)
        if d.get("elapsed_ms") is not None:
            ui_dump_internal.append(float(d["elapsed_ms"]))

    tap_to_ui: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        helper.action("tap", x=540, y=1200)
        helper.dump_compact_ui(max_elements=80)
        tap_to_ui.append((time.perf_counter() - t0) * 1000.0)

    tap_to_shot: list[float] = []
    tmp_png = "/tmp/agentdroid_tap_shot_bench.png"
    for _ in range(10):
        t0 = time.perf_counter()
        dev.shell("input tap 540 1200")
        dev.screenshot(tmp_png)
        tap_to_shot.append((time.perf_counter() - t0) * 1000.0)

    atomic_snap: list[float] = []
    atomic_snap_internal: list[float] = []
    # Android 11 API 30 enforces ~1s minimum cooldown between AccessibilityService.takeScreenshot() calls
    # (ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT=3); sleep between timed samples.
    time.sleep(1.1)
    for _ in range(10):
        t0 = time.perf_counter()
        s = helper._request("GET", "/snapshot?fields=xml")
        atomic_snap.append((time.perf_counter() - t0) * 1000.0)
        if not s.get("has_screenshot"):
            raise RuntimeError(f"Atomic snapshot did not return screenshot: {s.get('screenshot_error')}")
        if s.get("atomic_elapsed_ms") is not None:
            atomic_snap_internal.append(float(s["atomic_elapsed_ms"]))
        time.sleep(1.1)

    burst_3: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        engine.execute_action_burst(["key:HOME", "tap:540,1200", "key:BACK"])
        burst_3.append((time.perf_counter() - t0) * 1000.0)

    shell_chain_3: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        dev.shell("input keyevent HOME && input tap 540 1200 && input keyevent BACK")
        shell_chain_3.append((time.perf_counter() - t0) * 1000.0)

    results["micro_benchmarks"] = {
        "artemis_ipc_global_home": summarize(ipc_global),
        "adb_input_tap": summarize(adb_tap),
        "helper_action_tap": {**summarize(helper_tap), "backends": sorted(helper_tap_backends)},
        "artemis_ui_dump_roundtrip": summarize(ui_dump),
        "artemis_ui_dump_on_device_ms": summarize(ui_dump_internal) if ui_dump_internal else None,
        "tap_to_ui_dump": summarize(tap_to_ui),
        "tap_to_screenshot_adb": summarize(tap_to_shot),
        "artemis_atomic_snapshot_roundtrip": summarize(atomic_snap),
        "artemis_atomic_snapshot_on_device_ms": summarize(atomic_snap_internal) if atomic_snap_internal else None,
        "compound_burst_3_actions": summarize(burst_3),
        "adb_single_shell_chain_3_actions": summarize(shell_chain_3),
    }

    # 5. Perception Payload & Token Comparison
    print("Measuring perception payload sizes and token estimates...")
    results["perception_payloads"] = measure_payload_and_tokens(dev, helper, engine)

    payload_text = json.dumps(results, indent=2) + "\n"
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(payload_text)
    artifact_dir = os.environ.get("AGENTDROID_BENCHMARK_ARTIFACT_DIR")
    if artifact_dir:
        art_path = Path(artifact_dir).expanduser() / RESULTS_PATH.name
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_text(payload_text)
    print(f"Saved results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
