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

## Empirical Benchmark Suite

AgentDroid is evaluated on live hardware (`redroid11_x86_64`, Android 11, `1080x2400`) across the three standard research benchmark axes:
1. **Systems & Gesture Latency Parity** (`benchmarks/benchmark_agentdroid.py`) vs. Mobilebox (`summary.csv`), Limrun, and Local AVD.
2. **Perception Payload & Token Economics** (`benchmarks/benchmark_agentdroid.py`) vs. Raw UI XML and Vision Screenshot PNGs (`arXiv:2405.14573v3`).
3. **Verifiable Complexity-Stratified End-to-End Task Suite** (`benchmarks/run_e2e_benchmark.py`) across `13` real tasks (`Simple`, `Medium`, `Complex`) spanning `8` Android apps with independent SQLite, ContentProvider, `/sdcard/` disk, and UI state-delta verifiers.

> **Full Benchmark Tables, Per-Task Traces & Raw Telemetry:** See [`benchmarks/README.md`](benchmarks/README.md) and [`benchmarks/results/`](benchmarks/results/).

### Industry Architecture & Literature Comparison

| Agent / Platform | Execution Stack | Decision Engine | Turn Decision Latency | Gesture Injection Latency | Perception Payload | Mean E2E Task Duration | Empirical Pass / Success Rate | Host Idle Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid (Compound / MCP)** | **Local Redroid + `InputDaemon`** | **Host Coding Agent (`1`-turn burst)** | **Single turn** (plans once) | **1.82 ms** (`/dev/uinput`) | **1.7–2.8 KB** pruned text (`~433–694 tok`) | **3.77 s** (`49.1 s` total / `13` tasks) | **100.0%** (`13/13` ground-truth E2E) | **0.32% CPU** · `1.16 GB` RAM |
| **AgentDroid + TypeSafe AI (Jev)** | **Local Redroid + `InputDaemon`** | **TypeSafe AI `jev-latest` (System One)** | **323–558 ms** (keep-alive) | **1.82 ms** (`/dev/uinput`) | **1.7–2.8 KB** (`~167–585 tok`/turn) | **10.33 s** (`134.3 s` total / `13` tasks) | **92.3%** (`12/13` autonomous loop) | **0.32% CPU** · `1.16 GB` RAM |
| **Vostride AndroidWorld Agent** | Cloud VM / Emulated Android | Multimodal VLM (GPT-4o / Claude) | 8,000–15,000 ms | 517 ms (`adb shell input`) | 125 KB PNG tiles (`1,445 tok`) | **91.9 s** (`827.0 s` on matched `9` tasks) | Standard full-suite leaderboard | Cloud VM |
| **Google Artemis** | Multi-Agent Graph | Gemini 2.5 Pro / Flash Graph | 3,000–5,000 ms (Flash) · 15–40s (Pro) | 150–400 ms (A11y HTTP) | Screenshot + raw XML | 180–300 s (published suite) | **99.1%** (published full AndroidWorld) | ~2.2 GB RAM |
| **Mobilebox (Limrun Cloud)** | Cloud Android 14 (Nuremberg) | External SDK / VLM | LLM dependent | **76 ms** (Cloud WebSocket) | Full screenshot PNG | 24.6–37.9 s (demo tasks) | Cloud infra baseline | Cloud serverless |
| **Google M3A (`arXiv:2405.14573v3`)** | Android Studio AVD (QEMU+KVM) | GPT-4 Turbo / Gemini 1.5 Pro | 12,000–25,000 ms | ~550 ms (`adb shell input`) | A11y tree / SoM PNG | ~234.0 s | **30.6%** (A11y) · **25.4%** (SoM) | `3.5 GB` RAM · High CPU |
| **AutoGLM / GLM-4V Mobile** | Host Python + Device | Fine-tuned GLM-4V | 6,000–10,000 ms | ~500 ms (`adb input`) | Vision tokens (~1,200 tok) | 60–120 s | **80.2%** (published AndroidWorld) | Standard host |
| **Mobile-Agent-v2 / AppAgent** | Local Python + Vision Memory | Qwen-VL / GPT-4o Vision | 7,000–14,000 ms | ~520 ms (`adb input`) | Screenshot + OCR crops | 90–180 s | **73.3%** (published AndroidWorld) | Python runtime |
| **UI-TARS (ByteDance)** | Dedicated GPU VLM | UI-TARS 7B / 72B | 4,000–8,000 ms | ~500 ms (`adb input`) | Full resolution screenshot | 45–90 s | **46.6%** (published AndroidWorld) | Dedicated GPU |

### Key Measured Takeaways
- **Kernel Touch & Observation Loops:** Persistent `/dev/uinput` gesture injection (`1.82 ms` median vs `552.4 ms` `adb shell input`) yields a **303x** touch speedup; `tap_to_ui_dump` (`6.46 ms`) beats `tap_to_screenshot` (`758 ms`) by **117x**.
- **Token Bandwidth Compression:** Pruned indexed screen text (`1,730–2,774 chars` / `~433–694` est. tokens) cuts payload size by **85.4%–87.4%** vs raw XML (`13.7–18.9 KB`) and requires **52%–70% fewer tokens** per step than `1080x2400` Vision PNGs (`1,445` OpenAI / `1,477` Anthropic tokens).
- **Matched AndroidWorld Speedup (`10.6x` Autonomous / `25.8x` Compound):** Across the 9 tasks matching published Vostride AndroidWorld baselines (`827.0 s` total), **AgentDroid + Jev** runs in **`78.31 s`** (`8/9 = 88.9%` SR, `10.6x` faster) and **AgentDroid Compound** runs all 9 in **`32.09 s`** (`9/9 = 100.0%` SR, `25.8x` faster).

### Infrastructure & Gesture Latency Parity (`benchmarks/benchmark_agentdroid.py`)

Measured directly against Mobilebox's primary [`summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) dataset:

| Metric | AgentDroid (Local Redroid `127.0.0.1:5555`) | Mobilebox EU (Nuremberg, `summary.csv`) | Limrun (Nuremberg, `summary.csv`) | Local AVD KVM On (`summary.csv`) | Local AVD KVM Off (`summary.csv`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cold-Start `ready` (median)** | **9,767 ms** (`n=3`, p90 `9,886`) | **17,833 ms** (`n=10`, p90 `18,072`) | **338 ms** (`n=10`, p90 `454`) | **49,231 ms** (+`75,307 ms` setup) | **782,342 ms** (`13.0 min`) |
| **`cold_start_to_screenshot` (median)** | **10,963 ms** (`n=3`, p90 `11,096`) | **19,353 ms** (`n=10`, p90 `19,487`) | **977 ms** (`n=10`, p90 `1,067`) | **50,009 ms** (`n=5`, p90 `50,278`) | **812,681 ms** (`13.5 min`) |
| **APK Install (`org.fossify.math`)** | **675 ms** fresh (`n=3`) · **648 ms** `-r` (`n=5`) | **1,172 ms** (`n=10`, p90 `1,544`) | **850 ms** (`n=10`, p90 `954`) | **6,091 ms** (`n=5`, p90 `7,307`) | **125,911 ms** (`n=1`) |
| **Single Tap (median)** | **1.82 ms** `InputDaemon` (`n=10`) · **3.06 ms** IPC (`n=20`) | **517 ms** (`n=100`, p90 `526`) | **76 ms** (`n=100`, p90 `78`) | **150 ms** (`n=50`, p90 `383`) | **1,880 ms** (`n=10`, p90 `5,107`) |
| **`tap_to_screenshot` (median)** | **758 ms** (`adb tap` + `adb screencap`, `n=10`) | **1,448 ms** (`n=100`, p90 `1,487`) | **384 ms** (`n=100`, p90 `402`) | **1,035 ms** (`n=50`, p90 `3,523`) | **18,691 ms** (`n=10`, p90 `23,373`) |

## Troubleshooting

`agentdroid doctor` checks adb, binder, device, and helper status. Logs: `docker compose logs redroid server`.
Use `agentdroid device clean` to flush background apps and reclaim RAM.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK, and [TypeSafe AI](https://typesafe.ai) for sub-second calibrated decision models. AgentDroid is Apache-2.0.
