# AgentDroid

A silent, headless **Android computer for AI agents**, built on [Redroid](https://github.com/remote-android/redroid-doc), powered by the **Google Artemis mobile driving engine**.

- **Local AI Agents (Claude Code, Antigravity, Codex, Cursor):** Drive Android directly via **native Model Context Protocol (MCP)** or compound CLI calls.
- **Zero External LLM Keys / Zero Cloud Dependencies:** Your existing AI coding assistant is the brain. No secondary API accounts, no server daemons, no credential leakage.

AgentDroid embeds Artemis's driving engine (numbered indexed perception `[#1]`, action bursts, dynamic-first coordinate fallback, and system dialog auto-dismissal) so your coding agent has direct, native control over Android.

## Architecture

```
 Claude / Codex / Antigravity ──MCP (stdio) / CLI──► agentdroid (Python) ──► adb ──► Redroid Android
```

| Path | What it is |
| :--- | :--- |
| [`agentdroid/`](agentdroid/) | Local automation engine, Artemis driving core, and native Model Context Protocol (MCP) server. |
| [`docker/`](docker/), [`docker-compose.yml`](docker-compose.yml) | Redroid device image and container configuration. |
| [`scripts/provision-device.sh`](scripts/provision-device.sh) | Silent root ADB, dark theme, gesture nav, animations off. |
| [`skills/`](skills/), [`AGENTS.md`](AGENTS.md) | Skill and rules mounted into coding assistants by `install.sh`. |

## Quick start (local, with your AI coding agent)

```bash
git clone https://github.com/theajmalrazaq/agentdroid.git && cd agentdroid
./install.sh          # host tools, kernel modules, `agentdroid` on PATH, agent skills, device up
```

### 1. Drive via Model Context Protocol (MCP) in Claude Code / Codex / Antigravity / Cursor
```bash
agentdroid mcp --install   # automatically configures Claude, Codex, Antigravity, and Cursor
```
Your agent gets native mobile tools (`mobile_run_workflow`, `mobile_get_device_state`, `mobile_perform_action`, `mobile_action_burst`, `mobile_auto_dismiss_dialogs`, etc.).

### 2. Drive via Terminal CLI
Ask your agent: *"Use agentdroid to open Hacker News and summarize the top 5 stories."*

```bash
# Silent background mode (inspects screen in ~150 tokens, chains clicks/fills):
agentdroid --headless --open-url "https://news.ycombinator.com" \
  --do "scroll:down" --assert-text "Hacker News" --json

# Floating phone overlay window to watch in real time:
agentdroid --watch --launch com.android.settings
```

## Why Redroid instead of the Android Studio emulator?

Redroid runs Android as a container on the host kernel (no QEMU VM), so it typically needs far less RAM and boots in seconds. Figures vary by host; measure on yours.

## Comprehensive Benchmark Suite: AgentDroid vs. Competitors & 116 AndroidWorld Tasks

AgentDroid is empirically benchmarked across three dimensions on live hardware (`redroid11_x86_64`, Android 11, `1080x2400`):
1. **Low-level Infrastructure & Gestures** vs. Mobilebox (`summary.csv`) and Local AVD.
2. **Architectural & Turn Latency** vs. Google Artemis, AndroidWorld M3A, and Mobilebox.
3. **Full 116-Task AndroidWorld Benchmark** vs. published Vostride leaderboard baselines driven by TypeSafe AI (Jev System One).

> **Full Benchmark Suite & All 116 Executed Tasks:** See [`benchmarks/README.md`](benchmarks/README.md) for the complete 116-row side-by-side data table, stream logs, and reproduction scripts.

### 1. Unified Architectural & Competitor Comparison

| Platform / Agent Stack | Execution Model | Turn Decision Latency | UI Perception Payload | Gesture Injection Overhead | Average Task Duration | Idle Container Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid + TypeSafe AI (Jev)** | **Direct System One Logits** | **418–560 ms** (`jev-latest`) | **1.7 KB** text hierarchy (`~430 tok`) | **1.8 ms** (`InputDaemon` uinput) | **~5.6 s** (avg over 116 tasks) | **0.32% CPU** · `1.16 GB` RAM |
| **AgentDroid + Coding LLM** | **Compact Token Hierarchy + MCP** | **3,500–4,500 ms** (Gemini/Claude) | **2.8 KB** token-pruned JSON | **1.8 ms** (`InputDaemon` uinput) | **~24.5 s** | **0.32% CPU** · `1.16 GB` RAM |
| **Vostride Benchmark Baseline** | **Multimodal Vision + OCR Agent** | **8,000–15,000 ms** | **125 KB** PNG tiles (`1,445 tok`) | **517 ms** (`adb shell input`) | **176.9 s** (~3.0 min) | Cloud dependent |
| **Google Artemis (Pro Graph)** | **Planner + Operator + Checker** | **15,000–40,000 ms** | Full screenshot + a11y tree | **150–400 ms** (HTTP helper) | **180–300 s** (~3–5 min) | `2.2 GB` RAM |
| **Mobilebox (Limrun Cloud)** | **Remote WebRTC / Cloud ADB** | **8,000–12,000 ms** (LLM dependent)| Full screenshot PNG (`50 KB+`) | **76 ms** (cloud instance WS) | **24.6–37.9 s** (simple demo) | Cloud instance ($0.01/min) |
| **Google Research M3A (SoM)** | **Vision Set-of-Marks + GPT-4** | **12,000–25,000 ms** | Screenshot + bounding boxes | **550 ms** (raw ADB input) | **234.0 s** (~3.9 min) | Emulated AVD (`~3 GB`) |

### 2. Infrastructure & Gesture Latency Parity (`benchmarks/benchmark_agentdroid.py`)

Measured directly against Mobilebox's primary [`summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) dataset:

| Metric | AgentDroid (Local Redroid `127.0.0.1:5555`) | Mobilebox EU (Nuremberg, `summary.csv`) | Limrun (Nuremberg, `summary.csv`) | Local AVD KVM On (`summary.csv`) | Local AVD KVM Off (`summary.csv`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cold-Start `ready` (median)** | **9,767 ms** (`n=3`, p90 `9,886`) | **17,833 ms** (`n=10`, p90 `18,072`) | **338 ms** (`n=10`, p90 `454`) | **49,231 ms** (+`75,307 ms` setup) | **782,342 ms** (`13.0 min`) |
| **`cold_start_to_screenshot` (median)** | **10,963 ms** (`n=3`, p90 `11,096`) | **19,353 ms** (`n=10`, p90 `19,487`) | **977 ms** (`n=10`, p90 `1,067`) | **50,009 ms** (`n=5`, p90 `50,278`) | **812,681 ms** (`13.5 min`) |
| **APK Install (`org.fossify.math`)** | **675 ms** fresh (`n=3`) · **648 ms** `-r` (`n=5`) | **1,172 ms** (`n=10`, p90 `1,544`) | **850 ms** (`n=10`, p90 `954`) | **6,091 ms** (`n=5`, p90 `7,307`) | **125,911 ms** (`n=1`) |
| **Single Tap (median)** | **1.82 ms** `InputDaemon` (`n=10`) · **3.06 ms** IPC global (`n=20`) | **517 ms** (`n=100`, p90 `526`) | **76 ms** (`n=100`, p90 `78`) | **150 ms** (`n=50`, p90 `383`) | **1,880 ms** (`n=10`, p90 `5,107`) |
| **`tap_to_screenshot` (median)** | **758 ms** (`adb tap` + `adb screencap`, `n=10`) | **1,448 ms** (`n=100`, p90 `1,487`) | **384 ms** (`n=100`, p90 `402`) | **1,035 ms** (`n=50`, p90 `3,523`) | **18,691 ms** (`n=10`, p90 `23,373`) |

### 3. Empirical 116-Task AndroidWorld Execution Summary

Driven by TypeSafe AI (Jev System One) across all 20 applications:
- **Total Tasks Executed:** **116 tasks** (100% completed)
- **Vostride Total Duration:** **5.70 hours** (`20,531.0s`, 1,960 actions)
- **AgentDroid + TypeSafe AI (Jev) Duration:** **10.90 minutes** (`654.2s`, 460 steps)
- **Overall Empirical Speedup:** **31.4x faster**
- **Average Jev Decision Latency:** **559.0 ms**
- **Full 116-row table and live stream log:** See [`benchmarks/README.md`](benchmarks/README.md) and [`benchmarks/live_116_progress.json`](benchmarks/live_116_progress.json).

## Troubleshooting

`agentdroid doctor` checks adb, binder, device, and helper status. Logs: `docker compose logs redroid server`.
Use `agentdroid device clean` to flush background apps and reclaim RAM.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK, and [TypeSafe AI](https://typesafe.ai) for sub-second calibrated decision models. AgentDroid is Apache-2.0.
