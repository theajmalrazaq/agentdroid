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

## The Grand Android AI Agent Benchmark & Architecture Matrix

Comprehensive evaluation comparing **AgentDroid** against every major autonomous mobile agent, cloud harness, and Android execution platform across 10 empirical engineering dimensions:

| Agent / Framework | Architecture & Hosting | Decision Engine / Intelligence | Turn Decision Latency | Gesture Injection Latency | Perception Cost / Payload | Avg Multi-Step Task Duration | AndroidWorld Completion / Pass Rate | Idle CPU & RAM Footprint | Cost per Task / Running Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid + TypeSafe AI (Jev)** | **Local Redroid container + InputDaemon** | **TypeSafe AI `jev-latest` (System One Logits)** | **418–560 ms** | **1.8 ms** (Kernel `/dev/uinput`) | **1.7 KB** text hierarchy (`~430 tok`) | **5.6 s** (avg over 116 tasks) | **100% completed** · **31.4x faster** than Vostride | **0.32% CPU** · `1.16 GB` RAM | **$0.0002** / task (Free local hardware) |
| **AgentDroid + Coding LLM** | **Local Redroid container + Native MCP** | **Claude 3.5 / Gemini 2.5 / GPT-4o (Host Agent)** | **3,500–4,500 ms** | **1.8 ms** (Kernel `/dev/uinput`) | **2.8 KB** pruned JSON (`~690 tok`) | **24.5 s** (compound action bursts) | High (General-purpose interactive) | **0.32% CPU** · `1.16 GB` RAM | **$0.00** (Uses existing assistant plan) |
| **Vostride Benchmark Agent** | **Cloud VM / Emulated Android** | **Multimodal Vision VLM (GPT-4o / Claude)** | **8,000–15,000 ms** | **517 ms** (`adb shell input`) | **125 KB** PNG tiles (`1,445 tok`) | **176.9 s** (~3.0 minutes) | Standard baseline (**5h 42m** for 116 tasks) | VM dependent | **$0.08–$0.25** / task (Vision API costs) |
| **Google Artemis** | **Standalone Multi-Agent Graph (Planner+Operator)** | **Gemini 2.5 Pro / Flash Graph** | **3,000–5,000 ms** (Flash) · **15,000–40,000 ms** (Pro) | **150–400 ms** (A11y HTTP endpoint) | Full screenshot + raw XML | **180–300 s** (~3–5 minutes) | **99.1% Pass@1** (SOTA benchmark accuracy) | `2.2 GB` RAM (Multi-agent state) | Cloud LLM token costs |
| **Mobilebox (Limrun Cloud)** | **Cloud Android 14 instances (Nuremberg DC)** | **External developer LLM SDKs (LangGraph, etc.)** | **8,000–12,000 ms** (LLM dependent) | **76 ms** (Cloud instance WebSocket) | Full screenshot PNG (`50 KB+`) | **24.6–37.9 s** (Simple matterhorn demo) | Targeted cloud demos | Cloud serverless pool | **$0.01 / minute** usage rate |
| **Google Research M3A (SoM)** | **Android Studio AVD Emulator (QEMU)** | **GPT-4 Turbo / Gemini 1.5 Pro (Set-of-Marks)** | **12,000–25,000 ms** | **550 ms** (`adb shell input`) | Screenshot + Visual SoM bounding boxes | **234.0 s** (~3.9 minutes) | **30.6%** (A11y tree) · **25.4%** (SoM) | `3.5 GB` RAM · High QEMU CPU | High API cost per task |
| **AutoGLM / GLM-4V Mobile** | **Host Python + Real/Virtual Device** | **GLM-4V Fine-tuned Mobile Model** | **6,000–10,000 ms** | **500 ms** (`adb input`) | Screenshot vision tokens (`~1,200 tok`) | **60–120 s** | **80.2%** on AndroidWorld | Standard device host | API token pricing |
| **Mobile-Agent-v2 / AppAgent** | **Local Python + Vision Memory Bank** | **Qwen-VL / GPT-4o Vision** | **7,000–14,000 ms** | **520 ms** (`adb input`) | Screenshot + OCR + Visual icon crops | **90–180 s** | **73.3%** on AndroidWorld | High Python process RAM | Multimodal token costs |
| **UI-TARS (ByteDance)** | **Local / Cloud GPU Native GUI Model** | **UI-TARS 7B / 72B End-to-End VLM** | **4,000–8,000 ms** (GPU-accelerated) | **500 ms** (`adb input`) | Full resolution screenshot | **45–90 s** | **46.6%** on AndroidWorld | Requires dedicated GPU (A100/RTX 4090) | High local compute / Cloud GPU |
| **Android Studio AVD + UiAutomator** | **QEMU Full System Emulator + Test Scripts** | **None (Hardcoded Python / Java scripts)** | **0 ms** (Static execution) | **150–350 ms** (UiAutomator2 HTTP server) | Static selectors / UI Hierarchy dump | Script length dependent | **0% adaptable** (Breaks on any UI change) | **200%+ CPU** · `3.5 GB` RAM | Free local (High developer maintenance) |

---

### Why These Metrics Differ: The 4 Architectural Laws

1. **The Physics of Decision Latency (500 ms vs. 12,000 ms):**
   - Traditional vision agents encode `1080x2400` screens into image patches, upload them to remote LLMs, decode image tokens, generate reasoning chains, and emit JSON text (~8–15 seconds).
   - AgentDroid + Jev System One passes compact element trees directly into a specialized decision network returning calibrated decision logits in **418 ms**, cutting AI latency by **20x–30x**.
2. **The Gesture Injection Boundary (1.8 ms vs. 517 ms):**
   - Standard ADB tools fork an `adb shell input tap X Y` process, which invokes `/system/bin/input`, spins up an Android Dalvik/ART VM runtime, connects to `InputManagerService`, and exits (~500–600 ms).
   - AgentDroid's `InputDaemon` maintains an open Unix socket directly into Linux kernel `/dev/uinput`, writing binary touch events in **1.8 ms** (300x faster).
3. **Perception Payload Efficiency (1.7 KB vs. 125 KB):**
   - Vision-first tools burn 1,445 tokens per screen on image tiles. AgentDroid's accessibility engine prunes non-interactive background views, producing an indexed representation (`[#1] | Button: 'Login' | Center: (540, 1200)`) in **1,730 characters** (~430 tokens), saving 85%+ in token bandwidth.
4. **Containerization vs. Emulation (0.32% CPU vs. 200% CPU):**
   - Android Studio AVD emulates hardware registers and instruction translations via QEMU, consuming 3–4 GB RAM and heavy CPU.
   - Redroid shares the host Linux kernel (via `binder_linux` and `ashmem`), idling at **0.32% CPU** and **1.16 GB RAM** with AgentDroid's background memory trimmer.

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
