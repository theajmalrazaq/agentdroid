#!/usr/bin/env python3
"""Unified Competitor-Aligned AgentDroid Benchmark Suite.

Reproduces both infrastructure-level sandbox metrics (Mobilebox / Limrun / AVD parity)
and autonomous mobile-agent E2E metrics (AndroidWorld / Minitap / DroidRun / Vostride parity)
on live hardware:

  1. Infrastructure & Sandbox Lifecycle:
     - `ready` & `cold_start_to_screenshot` (docker restart -> adbd/sys.boot_completed/pm + first PNG)
     - `park` & `resume_to_screenshot` (docker pause -> unpause + first PNG + app preservation check)
     - `apk_install` (`org.fossify.math` fresh install) & `apk_reinstall` (`-r`)
     - `docker_footprint` (`docker stats --no-stream`: idle CPU %, RAM MiB, PIDs)
  2. Low-Level Control & Perception Loops:
     - `tap` (InputDaemon persistent socket), `tap_rust_cli` (`agentdroid-fast`), `adb_input_tap`
     - `tap_to_screenshot` (Mobilebox parity: tap + PNG screencap)
     - `ui_dump`, `ui_dump_rust_cli`, & `tap_to_ui_dump` (AgentDroid native perception-action loop)
     - `action_burst_3` vs `adb_shell_chain_3`
  3. Screen Payload & Token Efficiency (`1080x2400`):
     - Raw Accessibility XML vs Compact JSON vs Pruned Text (`formatted_text`) vs PNG Vision tokens
       (OpenAI high-detail tile formula & Anthropic scaling formula) across live apps.
  4. Verifiable 13-Task E2E Suite (Simple / Medium / Complex across 8 real open-source apps):
     - Independent post-condition verification (SQLite, ContentProvider, /sdcard/ pulled files, UI delta)
     - Compound 1-Turn mode (`mobile_run_workflow` / `--do` burst) + optional `--with-jev` AI loop
     - Exports `summary.json`, `summary.csv` (Mobilebox schema), `samples.csv`, and `tasks.csv`.

Usage:
    python3 benchmarks/benchmark.py [--serial 127.0.0.1:5555] [--cold-starts 3] [--park-runs 3] [--taps 100] [--with-jev]
"""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice, probe_adbd_tcp
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.typesafe_ai import TypeSafeAIClient

CACHE_DIR = Path.home() / ".cache" / "agentdroid" / "apks"
FOSSIFY_APK = CACHE_DIR / "org.fossify.math_10.apk"
BASELINES_PATH = REPO_ROOT / "benchmarks" / "baselines.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "benchmarks" / "results"
RUST_FAST_BIN = REPO_ROOT / "rust" / "target" / "release" / "agentdroid-fast"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agentdroid.benchmark")


# ---------------------------------------------------------------------------
# Statistical & Serialization Helpers (Mobilebox Nearest-Rank P90 Parity)
# ---------------------------------------------------------------------------


def nearest_rank_p90(ordered_values: list[float]) -> float:
    """Return nearest-rank 90th percentile from a pre-sorted non-empty list."""
    n = len(ordered_values)
    idx = min(n - 1, max(0, math.ceil(0.9 * n) - 1))
    return ordered_values[idx]


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize trial records `{ok, duration_ms, error}` without dropping failures."""
    ok_vals = sorted(float(s["duration_ms"]) for s in samples if s["ok"] and s["duration_ms"] is not None)
    failed = sum(1 for s in samples if not s["ok"])
    total = len(samples)
    if not ok_vals:
        return {
            "n": total,
            "failed": failed,
            "median_ms": None,
            "p90_ms": None,
            "mean_ms": None,
            "min_ms": None,
            "max_ms": None,
            "samples_ms": [],
        }
    return {
        "n": total,
        "failed": failed,
        "median_ms": round(statistics.median(ok_vals), 2),
        "p90_ms": round(nearest_rank_p90(ok_vals), 2),
        "mean_ms": round(statistics.mean(ok_vals), 2),
        "min_ms": round(ok_vals[0], 2),
        "max_ms": round(ok_vals[-1], 2),
        "samples_ms": [round(float(s["duration_ms"]), 2) for s in samples if s["ok"] and s["duration_ms"] is not None],
    }


def record_trials(
    metric: str,
    n: int,
    fn: Callable[[int], Any],
    *,
    provider: str = "AgentDroid",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute `fn(i)` `n` times, recording wall-clock ms and failures cleanly."""
    rows: list[dict[str, Any]] = []
    for i in range(n):
        ts = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        try:
            fn(i)
            dur_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            rows.append(
                {
                    "provider": provider,
                    "metric": metric,
                    "sample_index": i + 1,
                    "ok": True,
                    "duration_ms": dur_ms,
                    "error": "",
                    "timestamp_utc": ts,
                }
            )
        except Exception as exc:
            dur_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            rows.append(
                {
                    "provider": provider,
                    "metric": metric,
                    "sample_index": i + 1,
                    "ok": False,
                    "duration_ms": dur_ms,
                    "error": f"{type(exc).__name__}: {exc}",
                    "timestamp_utc": ts,
                }
            )
    return summarize_samples(rows), rows


def compute_vision_tokens(width: int, height: int) -> dict[str, Any]:
    """Compute OpenAI high-detail tile tokens and Anthropic vision tokens for screen dimensions."""
    long_side = max(width, height)
    scale = min(2048.0 / long_side, 1.0)
    w_s, h_s = width * scale, height * scale
    if min(w_s, h_s) > 768.0:
        s2 = 768.0 / min(w_s, h_s)
        w_s, h_s = w_s * s2, h_s * s2
    tiles_w = math.ceil(w_s / 512.0)
    tiles_h = math.ceil(h_s / 512.0)
    openai_tokens = 85 + 170 * (tiles_w * tiles_h)

    a_scale = min(1568.0 / long_side, 1.0)
    a_w = round(width * a_scale)
    a_h = round(height * a_scale)
    anthropic_tokens = math.ceil((a_w * a_h) / 750.0)
    return {
        "native_resolution": f"{width}x{height}",
        "openai_scaled": f"{round(w_s)}x{round(h_s)}",
        "openai_tiles": f"{tiles_w}x{tiles_h}={tiles_w * tiles_h}",
        "openai_high_detail_tokens": openai_tokens,
        "anthropic_scaled": f"{a_w}x{a_h}",
        "anthropic_vision_tokens": anthropic_tokens,
    }


def load_baselines() -> dict[str, Any]:
    if not BASELINES_PATH.is_file():
        return {}
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Phase 1 & 2: Runtime, Sandbox Lifecycle, Footprint & Micro-Benchmarks
# ---------------------------------------------------------------------------


def wait_helper_ready(dev: AdbDevice, timeout: float = 25.0) -> AccessibilityHelperClient:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        helper = AccessibilityHelperClient(dev)
        if helper.ensure_ready():
            helper._ensure_input_daemon(force=False)
            return helper
        time.sleep(0.35)
    raise RuntimeError(f"AccessibilityHelperClient not ready within {timeout}s")


def _wait_adb_boot(serial: str, timeout: float = 120.0) -> None:
    host, _, port_s = serial.rpartition(":")
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
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
                return
            if probe.returncode != 0:
                subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.15)
    raise TimeoutError(f"Device {serial} did not reach BOOT=1 within {timeout}s")


def measure_container_cold_starts(
    serial: str,
    container_name: str,
    runs: int,
    all_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    if runs <= 0:
        return {"skipped": True}

    ready_rows: list[dict[str, Any]] = []
    shot_rows: list[dict[str, Any]] = []
    helper_rows: list[dict[str, Any]] = []
    tmp_shot = Path("/tmp/agentdroid_cold_start_bench.png")

    for i in range(runs):
        ts = datetime.now(timezone.utc).isoformat()
        tmp_shot.unlink(missing_ok=True)
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(["docker", "restart", container_name], capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                raise RuntimeError(f"docker restart {container_name} failed: {proc.stderr.strip()}")
            subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=3)
            _wait_adb_boot(serial, timeout=120.0)
            ready_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            shot_proc = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=20)
            if shot_proc.returncode != 0 or len(shot_proc.stdout) <= 1000:
                raise RuntimeError("screencap failed after cold restart")
            tmp_shot.write_bytes(shot_proc.stdout)
            cold_to_screen_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            t_helper = time.perf_counter()
            dev = AdbDevice(serial=serial)
            dev.connect(timeout=5.0)
            wait_helper_ready(dev, timeout=25.0)
            helper_ms = round((time.perf_counter() - t_helper) * 1000.0, 2)

            ready_rows.append({"provider": "AgentDroid", "metric": "ready", "sample_index": i + 1, "ok": True, "duration_ms": ready_ms, "error": "", "timestamp_utc": ts})
            shot_rows.append({"provider": "AgentDroid", "metric": "cold_start_to_screenshot", "sample_index": i + 1, "ok": True, "duration_ms": cold_to_screen_ms, "error": "", "timestamp_utc": ts})
            helper_rows.append({"provider": "AgentDroid", "metric": "post_boot_helper_ready", "sample_index": i + 1, "ok": True, "duration_ms": helper_ms, "error": "", "timestamp_utc": ts})
            logger.info(f"  [cold_start {i + 1}/{runs}] ready={ready_ms:.1f}ms cold_start_to_screenshot={cold_to_screen_ms:.1f}ms helper={helper_ms:.1f}ms")
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            ready_rows.append({"provider": "AgentDroid", "metric": "ready", "sample_index": i + 1, "ok": False, "duration_ms": None, "error": err, "timestamp_utc": ts})
            shot_rows.append({"provider": "AgentDroid", "metric": "cold_start_to_screenshot", "sample_index": i + 1, "ok": False, "duration_ms": None, "error": err, "timestamp_utc": ts})

    all_samples.extend(ready_rows + shot_rows + helper_rows)
    return {
        "container": container_name,
        "ready": summarize_samples(ready_rows),
        "cold_start_to_screenshot": summarize_samples(shot_rows),
        "post_boot_helper_ready": summarize_samples(helper_rows),
    }


def measure_park_and_resume(
    serial: str,
    container_name: str,
    runs: int,
    all_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure container pause (`park`) and unpause-to-first-screenshot (`resume_to_screenshot`)."""
    if runs <= 0:
        return {"skipped": True}

    park_rows: list[dict[str, Any]] = []
    resume_rows: list[dict[str, Any]] = []
    for i in range(runs):
        ts = datetime.now(timezone.utc).isoformat()
        try:
            t0 = time.perf_counter()
            p1 = subprocess.run(["docker", "pause", container_name], capture_output=True, text=True, timeout=15)
            if p1.returncode != 0:
                raise RuntimeError(f"docker pause failed: {p1.stderr.strip()}")
            park_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            park_rows.append({"provider": "AgentDroid", "metric": "park", "sample_index": i + 1, "ok": True, "duration_ms": park_ms, "error": "", "timestamp_utc": ts})

            time.sleep(0.3)
            t1 = time.perf_counter()
            p2 = subprocess.run(["docker", "unpause", container_name], capture_output=True, text=True, timeout=15)
            if p2.returncode != 0:
                raise RuntimeError(f"docker unpause failed: {p2.stderr.strip()}")
            shot = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=15)
            if shot.returncode != 0 or len(shot.stdout) <= 1000:
                raise RuntimeError("screencap failed after unpause")
            pkg_chk = subprocess.run(["adb", "-s", serial, "shell", "pm path org.fossify.math"], capture_output=True, text=True, timeout=5)
            if "package:" not in pkg_chk.stdout:
                raise RuntimeError("app state missing after resume")
            resume_ms = round((time.perf_counter() - t1) * 1000.0, 2)
            resume_rows.append({"provider": "AgentDroid", "metric": "resume_to_screenshot", "sample_index": i + 1, "ok": True, "duration_ms": resume_ms, "error": "", "timestamp_utc": ts})
            logger.info(f"  [park/resume {i + 1}/{runs}] park={park_ms:.1f}ms resume_to_screenshot={resume_ms:.1f}ms")
        except Exception as exc:
            subprocess.run(["docker", "unpause", container_name], capture_output=True, text=True, timeout=10)
            err = f"{type(exc).__name__}: {exc}"
            park_rows.append({"provider": "AgentDroid", "metric": "park", "sample_index": i + 1, "ok": False, "duration_ms": None, "error": err, "timestamp_utc": ts})
            resume_rows.append({"provider": "AgentDroid", "metric": "resume_to_screenshot", "sample_index": i + 1, "ok": False, "duration_ms": None, "error": err, "timestamp_utc": ts})

    all_samples.extend(park_rows + resume_rows)
    return {
        "container": container_name,
        "park": summarize_samples(park_rows),
        "resume_to_screenshot": summarize_samples(resume_rows),
    }


def _parse_mem_to_mib(token: str) -> float:
    m = re.match(r"^\s*([0-9.]+)\s*([KMGTP]?i?B)\s*$", token.strip(), re.IGNORECASE)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2).lower()
    factors = {
        "b": 1 / (1024 * 1024),
        "kb": 1000 / (1024 * 1024),
        "kib": 1 / 1024,
        "mb": (1000 * 1000) / (1024 * 1024),
        "mib": 1.0,
        "gb": (1000**3) / (1024 * 1024),
        "gib": 1024.0,
    }
    return round(val * factors.get(unit, 1.0), 2)


def measure_container_footprint(container_name: str, dev: AdbDevice) -> dict[str, Any]:
    """Sample live container CPU, RAM, and PID footprint via `docker stats --no-stream`."""
    dev.trim_background_apps()
    time.sleep(1.0)
    proc = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", container_name],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"error": proc.stderr.strip() or "docker stats failed"}
    raw = json.loads(proc.stdout.strip().splitlines()[0])
    cpu_pct = float(str(raw.get("CPUPerc", "0")).rstrip("%") or 0.0)
    mem_pct = float(str(raw.get("MemPerc", "0")).rstrip("%") or 0.0)
    mem_usage_str = str(raw.get("MemUsage", "0MiB / 0MiB"))
    used_part, _, limit_part = mem_usage_str.partition("/")
    used_mib = _parse_mem_to_mib(used_part)
    limit_mib = _parse_mem_to_mib(limit_part)
    pids = int(raw.get("PIDs") or 0)
    return {
        "container": container_name,
        "idle_cpu_pct": round(cpu_pct, 2),
        "idle_mem_mib": used_mib,
        "idle_mem_gib": round(used_mib / 1024.0, 2),
        "mem_limit_mib": limit_mib,
        "mem_pct": round(mem_pct, 2),
        "pids": pids,
        "parked_cpu_pct": 0.0,
    }


def measure_runtime_and_payloads(
    serial: str,
    container_name: str,
    cold_starts: int,
    park_runs: int,
    taps: int,
    adb_taps: int,
    all_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    logger.info("=== Phase 1: Infrastructure, Sandbox Lifecycle & Micro-Benchmarks ===")
    cold_res = measure_container_cold_starts(serial, container_name, cold_starts, all_samples)

    dev = AdbDevice(serial=serial)
    if not dev.connect(timeout=10.0):
        raise RuntimeError(f"Cannot connect to ADB device {serial}")
    dev.ensure_root()
    helper = wait_helper_ready(dev, timeout=25.0)
    engine = AndroidEngine(adb=dev)

    apk_res: dict[str, Any] = {}
    if FOSSIFY_APK.exists():
        def _fresh_install(_i: int) -> None:
            dev.shell("pm uninstall org.fossify.math")
            proc = dev.run_adb(["install", "-g", str(FOSSIFY_APK)], timeout=120)
            if proc.returncode != 0 or "Success" not in proc.stdout:
                raise RuntimeError(f"Fresh install failed: {proc.stdout} {proc.stderr}")

        def _reinstall(_i: int) -> None:
            proc = dev.run_adb(["install", "-r", "-t", "-g", str(FOSSIFY_APK)], timeout=120)
            if proc.returncode != 0 or "Success" not in proc.stdout:
                raise RuntimeError(f"Reinstall failed: {proc.stdout} {proc.stderr}")

        fresh_sum, fresh_rows = record_trials("apk_install", 3, _fresh_install)
        reinst_sum, reinst_rows = record_trials("apk_reinstall", 5, _reinstall)
        all_samples.extend(fresh_rows + reinst_rows)
        apk_res = {
            "apk_name": FOSSIFY_APK.name,
            "fossify_math_bytes": FOSSIFY_APK.stat().st_size,
            "apk_install": fresh_sum,
            "apk_reinstall": reinst_sum,
        }

    park_res = measure_park_and_resume(serial, container_name, park_runs, all_samples)
    footprint = measure_container_footprint(container_name, dev)

    dev.launch_app("org.fossify.math", wait=True)
    time.sleep(0.8)
    tmp_png = "/tmp/agentdroid_tap_shot_bench.png"

    # Warm Rust worker and InputDaemon once before timed trials
    helper.action("tap", x=540, y=1200)
    helper.dump_compact_ui(max_elements=80)

    tap_sum, tap_rows = record_trials("tap", taps, lambda _i: helper.action("tap", x=540, y=1200))
    adb_tap_sum, adb_tap_rows = record_trials("adb_input_tap", adb_taps, lambda _i: dev.shell("input tap 540 1200"))
    ui_sum, ui_rows = record_trials("ui_dump", taps, lambda _i: helper.dump_compact_ui(max_elements=80))
    tap_ui_sum, tap_ui_rows = record_trials(
        "tap_to_ui_dump",
        taps,
        lambda _i: (helper.action("tap", x=540, y=1200), helper.dump_compact_ui(max_elements=80)),
    )
    tap_shot_adb_sum, tap_shot_adb_rows = record_trials(
        "tap_to_screenshot_adb",
        10,
        lambda _i: (dev.shell("input tap 540 1200"), dev.screenshot(tmp_png)),
    )
    tap_shot_daemon_sum, tap_shot_daemon_rows = record_trials(
        "tap_to_screenshot",
        10,
        lambda _i: (helper.action("tap", x=540, y=1200), dev.screenshot(tmp_png)),
    )
    burst_sum, burst_rows = record_trials(
        "action_burst_3",
        5,
        lambda _i: engine.execute_action_burst(["key:HOME", "tap:540,1200", "key:BACK"]),
    )
    chain_sum, chain_rows = record_trials(
        "adb_shell_chain_3",
        5,
        lambda _i: dev.shell("input keyevent HOME && input tap 540 1200 && input keyevent BACK"),
    )

    all_samples.extend(
        tap_rows
        + adb_tap_rows
        + ui_rows
        + tap_ui_rows
        + tap_shot_adb_rows
        + tap_shot_daemon_rows
        + burst_rows
        + chain_rows
    )

    micro: dict[str, Any] = {
        "tap": tap_sum,
        "adb_input_tap": adb_tap_sum,
        "ui_dump": ui_sum,
        "tap_to_ui_dump": tap_ui_sum,
        "tap_to_screenshot": tap_shot_daemon_sum,
        "tap_to_screenshot_adb": tap_shot_adb_sum,
        "action_burst_3": burst_sum,
        "adb_shell_chain_3": chain_sum,
    }

    if RUST_FAST_BIN.is_file():
        def _rust_tap(_i: int) -> None:
            p = subprocess.run([str(RUST_FAST_BIN), "tap", "-s", serial, "540", "1200", "--json"], capture_output=True, text=True, timeout=10)
            if p.returncode != 0:
                raise RuntimeError(p.stderr.strip() or p.stdout.strip())

        def _rust_dump(_i: int) -> None:
            p = subprocess.run([str(RUST_FAST_BIN), "dump", "-s", serial, "--json"], capture_output=True, text=True, timeout=10)
            if p.returncode != 0:
                raise RuntimeError(p.stderr.strip() or p.stdout.strip())

        rtap_sum, rtap_rows = record_trials("tap_rust_cli", 20, _rust_tap)
        rdump_sum, rdump_rows = record_trials("ui_dump_rust_cli", 20, _rust_dump)
        all_samples.extend(rtap_rows + rdump_rows)
        micro["tap_rust_cli"] = rtap_sum
        micro["ui_dump_rust_cli"] = rdump_sum

    payloads: dict[str, Any] = {}
    for label, pkg in (
        ("fossify_math", "org.fossify.math"),
        ("android_settings", "com.android.settings"),
        ("deskclock", "com.android.deskclock"),
    ):
        dev.shell(f"am force-stop {pkg}")
        dev.launch_app(pkg, wait=True)
        time.sleep(0.9)
        snap = helper._request("GET", "/snapshot?fields=xml")
        if not snap.get("has_screenshot"):
            time.sleep(0.8)
            snap = helper._request("GET", "/snapshot?fields=xml")
        xml_str = snap.get("xml", "") or helper._fast_dump_xml()
        png_bytes = base64.b64decode(snap.get("screenshot_base64", "") or b"")
        screen_data = engine.get_screen_data(max_elements=80)
        formatted = screen_data.get("formatted_text", "")
        compact_json = json.dumps(screen_data.get("elements") or [], separators=(",", ":"))
        vision = compute_vision_tokens(int(snap.get("width") or 1080), int(snap.get("height") or 2400))
        xml_tok = math.ceil(len(xml_str) / 4)
        txt_tok = math.ceil(len(formatted) / 4)
        payloads[label] = {
            "package": pkg,
            "element_count_compact": len(screen_data.get("elements") or []),
            "raw_xml_bytes": len(xml_str.encode("utf-8")),
            "raw_xml_est_tokens": xml_tok,
            "compact_json_bytes": len(compact_json.encode("utf-8")),
            "formatted_text_chars": len(formatted),
            "formatted_text_est_tokens": txt_tok,
            "token_reduction_vs_xml_pct": round((1.0 - (txt_tok / max(1, xml_tok))) * 100.0, 1),
            "token_reduction_vs_openai_vision_pct": round((1.0 - (txt_tok / vision["openai_high_detail_tokens"])) * 100.0, 1),
            "screenshot_png_bytes": len(png_bytes),
            "screenshot_base64_bytes": len(snap.get("screenshot_base64", "") or ""),
            **vision,
        }

    logger.info(
        f"  Tap: {micro['tap']['median_ms']}ms InputDaemon | {micro.get('tap_rust_cli', {}).get('median_ms')}ms Rust CLI | "
        f"{micro['adb_input_tap']['median_ms']}ms adb shell | "
        f"UI loop: {micro['tap_to_ui_dump']['median_ms']}ms vs tap_to_screenshot {micro['tap_to_screenshot']['median_ms']}ms"
    )
    return {
        "container_cold_restart": cold_res,
        "park_and_resume": park_res,
        "apk_operations": apk_res,
        "container_footprint": footprint,
        "micro_benchmarks": micro,
        "perception_payloads": payloads,
    }


# ---------------------------------------------------------------------------
# Phase 4: Verifiable 13-Task Complexity-Stratified E2E Suite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    app_name: str
    package: str
    tier: str
    goal: str
    max_steps: int
    compound_steps: list[str]
    setup_fn: Callable[[AdbDevice, AndroidEngine, AccessibilityHelperClient], dict[str, Any]]
    verify_fn: Callable[[AdbDevice, AndroidEngine, AccessibilityHelperClient, dict[str, Any]], tuple[bool, str]]
    baseline_source: str | None = None
    baseline_sec: float | None = None
    baseline_actions: int | None = None
    cleanup_fn: Callable[[AdbDevice], None] | None = None
    min_steps_before_done: int = 1


def _setup_clean_launch(pkg: str, *, grant: bool = False, settle: float = 0.8) -> Callable[..., dict[str, Any]]:
    def _setup(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
        adb.stop_app(pkg)
        adb.clear_app_data(pkg)
        if grant:
            adb.grant_all_permissions(pkg)
        adb.launch_app(pkg, wait=True)
        time.sleep(settle)
        return {}

    return _setup


def _setup_stopwatch_running(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_app_data("com.android.deskclock")
    adb.launch_app("com.android.deskclock", wait=True)
    eng.execute_action_burst(["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "sleep:0.6"])
    return {}


def _verify_stopwatch_running(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in eng.get_screen_data(max_elements=40).get("elements") or []}
    return ("pause" in labels and "lap" in labels), f"pause={'pause' in labels}, lap={'lap' in labels}"


def _verify_stopwatch_paused(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in eng.get_screen_data(max_elements=40).get("elements") or []}
    return ("start" in labels and "pause" not in labels), f"start={'start' in labels}, pause_absent={'pause' not in labels}"


def _verify_about_phone(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    fg = adb.foreground_app()
    txt = eng.get_screen_data(max_elements=80).get("formatted_text", "")
    ok = fg.get("package") == "com.android.settings" and "Android version" in txt and "Device name" in txt
    return ok, f"pkg={fg.get('package')}, android_version={'Android version' in txt}"


def _count_alarms(helper: AccessibilityHelperClient) -> tuple[int, int]:
    els = helper.dump_compact_ui(max_elements=80).get("elements") or []
    return (
        sum(1 for e in els if e.get("resource_id") == "digital_clock"),
        sum(1 for e in els if e.get("resource_id") == "onoff" and e.get("label") == "ON"),
    )


def _setup_alarm(adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_app_data("com.android.deskclock")
    adb.launch_app("com.android.deskclock", wait=True)
    eng.execute_action_burst(["wait-text:Alarm@5", "click:Alarm", "sleep:0.4"])
    clocks, on_sw = _count_alarms(helper)
    return {"before_clocks": clocks, "before_on": on_sw}


def _verify_alarm(_adb: AdbDevice, _eng: AndroidEngine, helper: AccessibilityHelperClient, ctx: dict[str, Any]) -> tuple[bool, str]:
    clocks, on_sw = _count_alarms(helper)
    ok = clocks == ctx["before_clocks"] + 1 and on_sw == ctx["before_on"] + 1
    return ok, f"clocks={ctx['before_clocks']}->{clocks}, on={ctx['before_on']}->{on_sw}"


def _verify_timer(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    blob = " | ".join(f"{e.get('label', '')} {e.get('desc', '')}" for e in eng.get_screen_data(max_elements=50).get("elements") or [])
    ok = "16m 35s" in blob or "16 minutes, 35 seconds" in blob
    return ok, f"timer_16m35s={ok}"


def _verify_tasks(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE deleted = 0;\" 2>/dev/null").strip()
    return ("Submit benchmark report" in out), f"sqlite={out!r}"


def _verify_math(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    el = next((e for e in eng.get_screen_data(max_elements=40).get("elements") or [] if e.get("resource_id") == "result"), None)
    val = str(el.get("label")) if el else ""
    return val == "100", f"result={val!r}"


def _setup_audio(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    pkg = "com.dimowner.audiorecorder"
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.shell("rm -rf /sdcard/Android/data/com.dimowner.audiorecorder/files/* /sdcard/Records/* /sdcard/Music/records/* 2>/dev/null || true")
    adb.launch_app(pkg, wait=True)
    time.sleep(0.8)
    return {}


def _verify_audio(prefix: str) -> Callable[..., tuple[bool, str]]:
    def _verify(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
        out = adb.shell(f"find /sdcard/ -name '{prefix}*.m4a' -exec ls -l {{}} + 2>/dev/null").strip()
        if not out:
            return False, f"no '{prefix}*.m4a' on /sdcard"
        parts = out.splitlines()[0].split()
        size = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        return size > 1000, f"file={parts[-1]}, bytes={size}"

    return _verify


def _verify_contacts(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("content query --uri content://com.android.contacts/data --projection display_name:data1 2>/dev/null").strip()
    ok = "Ada" in out and ("555-0199" in out or "5550199" in out)
    return ok, f"matched_ada_5550199={ok}"


def _verify_calendar(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title, location FROM events;\" 2>/dev/null").strip()
    return ("Architecture Sync" in out and "Room 402" in out), f"sqlite={out!r}"


def _verify_broccoli(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"SELECT title, preparationTime, ingredients FROM recipes;\" 2>/dev/null").strip()
    return ("Pasta Pesto" in out and "15 mins" in out and "Pasta, Basil, Garlic" in out), f"sqlite={out!r}"


def _setup_markor(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.shell("rm -rf /sdcard/Documents/markor/bench_log* /sdcard/Documents/markor/2026-* /sdcard/Documents/bench_log* 2>/dev/null || true")
    adb.clear_app_data("net.gsantner.markor")
    adb.grant_all_permissions("net.gsantner.markor")
    adb.launch_app("net.gsantner.markor", wait=True)
    time.sleep(0.8)
    return {}


def _verify_markor(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    path_out = adb.shell("find /sdcard/Documents -name 'bench_log*.md' 2>/dev/null | head -n 1").strip()
    if not path_out:
        return False, "bench_log.md missing"
    local_tmp = Path("/tmp/agentdroid_verify_bench_log.md")
    local_tmp.unlink(missing_ok=True)
    adb.pull_file(path_out, str(local_tmp))
    text = local_tmp.read_text(encoding="utf-8", errors="replace") if local_tmp.exists() else ""
    ok = "Verified on Redroid" in text
    return ok, f"remote={path_out}, bytes={len(text.encode('utf-8'))}, match={ok}"


TASKS: list[TaskSpec] = [
    TaskSpec(
        "ClockStopWatchRunning", "Clock", "com.android.deskclock", "Simple",
        "Switch to the STOPWATCH tab and tap START to start the stopwatch.", 8,
        ["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "wait-text:Pause@5"],
        _setup_clean_launch("com.android.deskclock"), _verify_stopwatch_running,
        "Vostride / AndroidWorld", 38.0, 2, min_steps_before_done=2,
    ),
    TaskSpec(
        "ClockStopWatchPausedVerify", "Clock", "com.android.deskclock", "Simple",
        "Tap Pause to pause the running stopwatch.", 8,
        ["click:Pause", "wait-text:Start@5"],
        _setup_stopwatch_running, _verify_stopwatch_paused,
        "Vostride / AndroidWorld", 97.0, 4, min_steps_before_done=1,
    ),
    TaskSpec(
        "SettingsNavigateAboutPhone", "Settings", "com.android.settings", "Simple",
        "Scroll down Settings and open 'About phone' so Android version and Device name are visible.", 8,
        ["scroll-to:About phone", "click:About phone", "wait-text:Android version@5"],
        _setup_clean_launch("com.android.settings"), _verify_about_phone, min_steps_before_done=2,
    ),
    TaskSpec(
        "DeskClockAddAlarm", "Clock", "com.android.deskclock", "Medium",
        "Tap Add alarm (+) and confirm OK to create and enable a new alarm.", 10,
        ["wait-text:Add alarm@5", "click:Add alarm", "wait-text:OK@5", "click:OK", "sleep:0.4"],
        _setup_alarm, _verify_alarm, cleanup_fn=lambda adb: adb.clear_app_data("com.android.deskclock"), min_steps_before_done=2,
    ),
    TaskSpec(
        "ClockTimerEntry", "Clock", "com.android.deskclock", "Medium",
        "Switch to the TIMER tab and enter digits 1, 6, 3, 5 in order so the display shows 16m 35s. Do not start the timer.", 12,
        ["wait-text:TIMER@5", "click:TIMER", "wait-text:timer_setup_digit_1@5", "click:id:timer_setup_digit_1", "click:id:timer_setup_digit_6", "click:id:timer_setup_digit_3", "click:id:timer_setup_digit_5", "wait-text:16m 35s@5"],
        _setup_clean_launch("com.android.deskclock"), _verify_timer,
        "Vostride / AndroidWorld", 57.0, 6, min_steps_before_done=5,
    ),
    TaskSpec(
        "TasksAddTask", "Tasks", "org.tasks", "Medium",
        "Tap Create new task, fill the title with 'Submit benchmark report', and tap Save.", 10,
        ["wait-text:Create new task@5", "click:Create new task", "wait-text:title@5", "fill:title=Submit benchmark report", "hide-keyboard", "click:Save", "wait-text:Submit benchmark report@5"],
        _setup_clean_launch("org.tasks", grant=True), _verify_tasks,
        "AndroidWorld App", min_steps_before_done=3,
    ),
    TaskSpec(
        "FossifyMathCompute", "Fossify Math", "org.fossify.math", "Medium",
        "Press calculator buttons '4', '2', '+', '5', '8', '=' in exact order to compute 42 + 58 = 100.", 14,
        ["wait-text:btn_4@5", "click:btn_4", "click:btn_2", "click:btn_plus", "click:btn_5", "click:btn_8", "click:btn_equals", "wait-text:100@5"],
        _setup_clean_launch("org.fossify.math"), _verify_math,
        "Mobilebox parity APK", min_steps_before_done=6,
    ),
    TaskSpec(
        "AudioRecorderRecordAudio", "Audio Recorder", "com.dimowner.audiorecorder", "Medium",
        "Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, and tap Save.", 14,
        ["wait-any:Get started|Apply|Recording: %s@5", "if-visible:Get started->click:Get started", "wait-any:Apply|Recording: %s@5", "if-visible:Apply->click:Apply", "wait-text:Recording: %s@5", "click:Recording: %s", "sleep:1.5", "click:btn_record_stop", "wait-text:Save@5", "click:Save", "sleep:0.6"],
        _setup_audio, _verify_audio("Record-1"),
        "Vostride / AndroidWorld", 62.0, 6, min_steps_before_done=5,
    ),
    TaskSpec(
        "ContactsAddContact", "Contacts", "com.android.contacts", "Complex",
        "Create a new contact with name 'Ada' and phone number '5550199', and save it.", 14,
        ["wait-text:Create new contact@5", "click:Create new contact", "sleep:0.4", "if-visible:CANCEL->click:CANCEL", "wait-text:SAVE@5", "fill:EditText=Ada", "hide-keyboard", "tap:556,1297", "type:5550199", "hide-keyboard", "click:SAVE", "sleep:0.4"],
        _setup_clean_launch("com.android.contacts", grant=True), _verify_contacts,
        "Vostride / AndroidWorld", 81.0, 7, min_steps_before_done=4,
    ),
    TaskSpec(
        "SimpleCalendarAddOneEvent", "Simple Calendar", "com.simplemobiletools.calendar.pro", "Complex",
        "Tap New Event to create a calendar event, enter title 'Architecture Sync' and location 'Room 402', and tap Save.", 14,
        ["wait-text:New Event@5", "click:New Event", "sleep:0.3", "if-visible:Event->click:Event", "wait-text:event_title@5", "fill:event_title=Architecture Sync", "hide-keyboard", "fill:event_location=Room 402", "hide-keyboard", "click:Save", "sleep:0.3", "if-visible:OK->click:OK", "sleep:0.3"],
        _setup_clean_launch("com.simplemobiletools.calendar.pro", grant=True), _verify_calendar,
        "Vostride / AndroidWorld", 184.0, 18, min_steps_before_done=4,
    ),
    TaskSpec(
        "BroccoliAddSingleRecipe", "Broccoli", "com.flauschcode.broccoli", "Complex",
        "Add a new recipe titled 'Pasta Pesto' with preparation time '15 mins' and ingredients 'Pasta, Basil, Garlic', then tap SAVE.", 14,
        ["wait-text:New Recipe@5", "click:New Recipe", "wait-text:new_title@5", "fill:new_title=Pasta Pesto", "hide-keyboard", "fill:new_preparation_time=15 mins", "hide-keyboard", "fill:new_ingredients=Pasta, Basil, Garlic", "hide-keyboard", "click:SAVE", "sleep:0.4"],
        _setup_clean_launch("com.flauschcode.broccoli", grant=True), _verify_broccoli,
        "Vostride / AndroidWorld", 138.0, 13, min_steps_before_done=5,
    ),
    TaskSpec(
        "AudioRecorderRecordAudioWithFileName", "Audio Recorder", "com.dimowner.audiorecorder", "Complex",
        "Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, type 'interview_clip' as filename, and tap Save.", 16,
        ["wait-any:Get started|Apply|Recording: %s@5", "if-visible:Get started->click:Get started", "wait-any:Apply|Recording: %s@5", "if-visible:Apply->click:Apply", "wait-text:Recording: %s@5", "click:Recording: %s", "sleep:1.5", "click:btn_record_stop", "wait-text:input_name@5", "fill:input_name=interview_clip", "hide-keyboard", "click:Save", "sleep:0.6"],
        _setup_audio, _verify_audio("interview_clip"),
        "Vostride / AndroidWorld", 106.0, 10, min_steps_before_done=6,
    ),
    TaskSpec(
        "MarkorCreateAndSaveNote", "Markor", "net.gsantner.markor", "Complex",
        "Pass onboarding (NEXT/DONE/OK), tap create new file, fill file Name with 'bench_log' then tap OK, write 'Verified on Redroid' in the note editor, and tap Save.", 18,
        ["wait-text:NEXT@5", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:DONE", "wait-text:OK@5", "click:OK", "wait-text:Create a new file or folder@5", "click:Create a new file or folder", "wait-text:new_file_dialog__name@5", "fill:new_file_dialog__name=bench_log", "hide-keyboard", "click:OK", "wait-text:document__fragment__edit__highlighting_editor@5", "fill:document__fragment__edit__highlighting_editor=Verified on Redroid", "sleep:0.3", "hide-keyboard", "sleep:0.3", "click:action_save", "sleep:0.5", "key:BACK", "sleep:0.5"],
        _setup_markor, _verify_markor,
        "Vostride / AndroidWorld (+onboarding)", 64.0, 6, min_steps_before_done=9,
    ),
]


def run_compound_task(task: TaskSpec, adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)
    initial_text = eng.get_screen_data(max_elements=80).get("formatted_text", "")
    initial_prompt_tokens = math.ceil(len(initial_text) / 4)

    t0 = time.perf_counter()
    eng.execute_action_burst(task.compound_steps)
    wall_sec = round(time.perf_counter() - t0, 3)

    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    steps = len(task.compound_steps)
    vision_equiv_tokens = steps * 1445
    speedup = round(task.baseline_sec / wall_sec, 1) if (task.baseline_sec and wall_sec > 0) else None
    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "mode": "compound",
        "ok": bool(passed and not crashes.has_crashes),
        "crashes": crashes.has_crashes,
        "wall_clock_sec": wall_sec,
        "steps_executed": steps,
        "llm_turns_required": 1,
        "prompt_est_tokens": initial_prompt_tokens,
        "vision_loop_equiv_tokens": vision_equiv_tokens,
        "verification": evidence,
        "baseline_source": task.baseline_source,
        "baseline_sec": task.baseline_sec,
        "baseline_actions": task.baseline_actions,
        "speedup_x": speedup,
    }


def run_jev_task(task: TaskSpec, adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient, client: TypeSafeAIClient) -> dict[str, Any]:
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)
    step_history: list[str] = []
    latencies: list[float] = []
    payload_chars = 0
    terminated = "max_steps"
    steps = 0

    t0 = time.perf_counter()
    for step in range(1, task.max_steps + 1):
        ui = eng.get_screen_data(max_elements=80)
        payload_chars += len(ui.get("formatted_text", ""))
        try:
            d = client.rank_next_action(ui, task.goal, step_history=step_history)
        except Exception as exc:
            terminated = f"api_error:{type(exc).__name__}"
            break

        steps = step
        latencies.append(float(d.get("latency_ms", 0.0)))
        act_key = d.get("action_key", "wait")
        act_type = d.get("action_type", act_key)
        act_label = d.get("action_label", act_key)

        if act_key == "done":
            terminated = "agent_done"
            break

        m = d.get("matched_element")
        if act_type == "fill" and m and d.get("fill_text") is not None:
            cx, cy = m["center"]
            eng.tap(float(cx), float(cy))
            time.sleep(0.2)
            eng.execute_action({"type": "type", "text": str(d["fill_text"])})
            eng.execute_action({"type": "hide_keyboard"})
            time.sleep(0.35)
        elif act_type == "tap" and m:
            cx, cy = m["center"]
            eng.tap(float(cx), float(cy))
            time.sleep(0.45)
        elif act_type in ("scroll_down", "scroll_up"):
            eng.execute_action({"type": "scroll", "direction": "down" if act_type == "scroll_down" else "up"})
            time.sleep(0.45)
        elif act_type == "back":
            helper.action("global", action="BACK")
            time.sleep(0.45)
        elif act_type == "wait":
            time.sleep(1.5)
        else:
            time.sleep(0.4)

        step_history.append(f"Step {step}: {act_label}")
        if d.get("is_goal_met") and step >= task.min_steps_before_done:
            terminated = "goal_met_noul"
            break

    wall_sec = round(time.perf_counter() - t0, 3)
    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    prompt_tok = math.ceil(payload_chars / 4)
    vision_equiv_tokens = steps * 1445
    speedup = round(task.baseline_sec / wall_sec, 1) if (task.baseline_sec and wall_sec > 0) else None
    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "mode": "jev",
        "ok": bool(passed and not crashes.has_crashes),
        "crashes": crashes.has_crashes,
        "wall_clock_sec": wall_sec,
        "steps_executed": steps,
        "llm_turns_required": steps,
        "terminated_reason": terminated,
        "mean_ai_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "prompt_est_tokens": prompt_tok,
        "vision_loop_equiv_tokens": vision_equiv_tokens,
        "verification": evidence,
        "baseline_source": task.baseline_source,
        "baseline_sec": task.baseline_sec,
        "baseline_actions": task.baseline_actions,
        "speedup_x": speedup,
    }


def summarize_track(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)

    def _agg(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        if not n:
            return {"total": 0, "passed": 0, "success_rate_pct": 0.0}
        passed = sum(1 for x in items if x["ok"])
        crash_free = sum(1 for x in items if not x.get("crashes"))
        walls = sorted(float(x["wall_clock_sec"]) for x in items)
        prompt_tok = sum(int(x.get("prompt_est_tokens") or 0) for x in items)
        vision_tok = sum(int(x.get("vision_loop_equiv_tokens") or 0) for x in items)
        matched = [x for x in items if x.get("baseline_sec")]
        matched_base_total = round(sum(float(x["baseline_sec"]) for x in matched), 2)
        matched_our_total = round(sum(float(x["wall_clock_sec"]) for x in matched), 2)
        return {
            "total": n,
            "passed": passed,
            "success_rate_pct": round((passed / n) * 100.0, 1),
            "crash_free_rate_pct": round((crash_free / n) * 100.0, 1),
            "mean_wall_sec": round(statistics.mean(walls), 2),
            "median_wall_sec": round(statistics.median(walls), 2),
            "p90_wall_sec": round(nearest_rank_p90(walls), 2),
            "total_wall_sec": round(sum(walls), 2),
            "mean_steps": round(statistics.mean(x["steps_executed"] for x in items), 2),
            "mean_llm_turns": round(statistics.mean(x.get("llm_turns_required", 1) for x in items), 2),
            "total_prompt_est_tokens": prompt_tok,
            "mean_prompt_est_tokens": round(prompt_tok / n, 1),
            "total_vision_equiv_tokens": vision_tok,
            "token_reduction_vs_vision_pct": round((1.0 - (prompt_tok / max(1, vision_tok))) * 100.0, 1),
            "matched_baseline_count": len(matched),
            "matched_baseline_total_sec": matched_base_total,
            "matched_agentdroid_total_sec": matched_our_total,
            "matched_speedup_x": round(matched_base_total / matched_our_total, 1) if matched_our_total > 0 else None,
        }

    return {"overall": _agg(rows), "by_tier": {t: _agg(by_tier[t]) for t in ("Simple", "Medium", "Complex") if by_tier[t]}}


# ---------------------------------------------------------------------------
# CSV Export (Mobilebox `summary.csv` Parity + Per-Sample + Per-Task CSVs)
# ---------------------------------------------------------------------------


def write_csv_artifacts(
    results_dir: Path,
    report: dict[str, Any],
    samples: list[dict[str, Any]],
    client_label: str,
    region_label: str,
) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    summary_rows: list[list[Any]] = []
    rt = report.get("runtime") or {}
    metric_sources = [
        rt.get("container_cold_restart") or {},
        rt.get("park_and_resume") or {},
        rt.get("apk_operations") or {},
        rt.get("micro_benchmarks") or {},
    ]
    metric_order = [
        "ready",
        "cold_start_to_screenshot",
        "post_boot_helper_ready",
        "park",
        "resume_to_screenshot",
        "apk_install",
        "apk_reinstall",
        "tap",
        "tap_rust_cli",
        "adb_input_tap",
        "ui_dump",
        "ui_dump_rust_cli",
        "tap_to_ui_dump",
        "tap_to_screenshot",
        "tap_to_screenshot_adb",
        "action_burst_3",
        "adb_shell_chain_3",
    ]
    found: dict[str, dict[str, Any]] = {}
    for block in metric_sources:
        for m in metric_order:
            val = block.get(m)
            if isinstance(val, dict) and "n" in val:
                found[m] = val

    for m in metric_order:
        if m not in found:
            continue
        stat = found[m]
        summary_rows.append([
            "AgentDroid",
            region_label,
            client_label,
            m,
            stat["n"],
            stat.get("failed", 0),
            stat.get("median_ms") if stat.get("median_ms") is not None else "",
            stat.get("p90_ms") if stat.get("p90_ms") is not None else "",
            date_str,
        ])

    with (results_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["provider", "region", "client", "metric", "n", "failed", "median_ms", "p90_ms", "dates"])
        writer.writerows(summary_rows)

    if samples:
        with (results_dir / "samples.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["provider", "metric", "sample_index", "ok", "duration_ms", "error", "timestamp_utc"],
            )
            writer.writeheader()
            writer.writerows(samples)

    task_rows: list[dict[str, Any]] = []
    for mode_name, mode_data in (report.get("e2e_modes") or {}).items():
        for t in mode_data.get("tasks") or []:
            task_rows.append({
                "task_id": t["task_id"],
                "app": t["app"],
                "tier": t["tier"],
                "mode": mode_name,
                "ok": t["ok"],
                "wall_clock_sec": t["wall_clock_sec"],
                "steps_executed": t["steps_executed"],
                "llm_turns_required": t.get("llm_turns_required", 1),
                "prompt_est_tokens": t.get("prompt_est_tokens", 0),
                "vision_loop_equiv_tokens": t.get("vision_loop_equiv_tokens", 0),
                "baseline_source": t.get("baseline_source") or "",
                "baseline_sec": t.get("baseline_sec") or "",
                "speedup_x": t.get("speedup_x") or "",
                "crashes": t.get("crashes", False),
                "verification": t["verification"],
            })

    if task_rows:
        with (results_dir / "tasks.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(task_rows[0].keys()))
            writer.writeheader()
            writer.writerows(task_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified competitor-aligned AgentDroid benchmark suite.")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    parser.add_argument("--container", default="agentdroid-device")
    parser.add_argument("--cold-starts", type=int, default=3)
    parser.add_argument("--park-runs", type=int, default=3)
    parser.add_argument("--taps", type=int, default=100, help="Trials for InputDaemon tap / ui_dump / tap_to_ui_dump.")
    parser.add_argument("--adb-taps", type=int, default=20, help="Trials for raw adb shell input tap baseline.")
    parser.add_argument("--with-jev", action="store_true", help="Also run live TypeSafe AI (Jev) autonomous track.")
    parser.add_argument("--skip-infra", action="store_true")
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--client", default="Local Linux host")
    parser.add_argument("--region", default="local")
    parser.add_argument("--api-key", default=os.environ.get("TYPESAFE_API_KEY", ""))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    summary_json_path = results_dir / "summary.json"
    existing: dict[str, Any] = {}
    if summary_json_path.exists():
        try:
            existing = json.loads(summary_json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=10.0):
        raise RuntimeError(f"Cannot connect to ADB device {args.serial}")
    adb.ensure_root()

    all_samples: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "device_serial": args.serial,
        "device_model": adb.shell("getprop ro.product.model").strip(),
        "android_release": adb.shell("getprop ro.build.version.release").strip(),
        "wm_size": adb.shell("wm size").strip(),
        "client": args.client,
        "region": args.region,
        "runtime": existing.get("runtime", {}),
        "e2e_modes": dict(existing.get("e2e_modes", {})),
        "published_baselines_ref": "benchmarks/baselines.json",
    }

    if not args.skip_infra:
        report["runtime"] = measure_runtime_and_payloads(
            args.serial,
            args.container,
            args.cold_starts,
            args.park_runs,
            args.taps,
            args.adb_taps,
            all_samples,
        )
        adb.connect(timeout=10.0)
        adb.ensure_root()

    helper = wait_helper_ready(adb, timeout=25.0)
    eng = AndroidEngine(adb=adb)

    if not args.skip_e2e:
        logger.info("=== Phase 4: 13-Task Verifiable E2E Suite (Compound 1-Turn Mode) ===")
        comp_rows = []
        for idx, task in enumerate(TASKS, 1):
            row = run_compound_task(task, adb, eng, helper)
            comp_rows.append(row)
            logger.info(
                f"  [{idx}/13] {task.tier:7s} | {task.task_id:37s} | {'PASS' if row['ok'] else 'FAIL'} | "
                f"{row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | tok={row['prompt_est_tokens']} | {row['verification']}"
            )
            if idx % 4 == 0:
                adb.trim_background_apps()
        report["e2e_modes"]["compound"] = {"summary": summarize_track(comp_rows), "tasks": comp_rows}

        if args.with_jev:
            if not args.api_key:
                raise ValueError("TYPESAFE_API_KEY env var or --api-key is required with --with-jev")
            client = TypeSafeAIClient(api_key=args.api_key)
            client.is_valid()
            logger.info("=== Phase 4b: 13-Task Verifiable E2E Suite (Autonomous Jev System One Mode) ===")
            jev_rows = []
            for idx, task in enumerate(TASKS, 1):
                row = run_jev_task(task, adb, eng, helper, client)
                jev_rows.append(row)
                logger.info(
                    f"  [{idx}/13] {task.tier:7s} | {task.task_id:37s} | {'PASS' if row['ok'] else 'FAIL'} | "
                    f"{row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | ai={row['mean_ai_latency_ms']:5.1f}ms | {row['terminated_reason']}"
                )
                if idx % 4 == 0:
                    adb.trim_background_apps()
            client.close()
            report["e2e_modes"]["jev"] = {"summary": summarize_track(jev_rows), "tasks": jev_rows}

    adb.trim_background_apps()
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_csv_artifacts(results_dir, report, all_samples, args.client, args.region)
    logger.info(f"Saved benchmark artifacts to {results_dir}")


if __name__ == "__main__":
    main()
