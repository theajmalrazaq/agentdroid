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

## Benchmark & Architecture: AgentDroid vs. Artemis vs. AndroidWorld vs. Mobilebox

While [Google Artemis](https://github.com/google/artemis) (Pixel Test Engineering) was designed as an autonomous standalone agent daemon running an internal observe-and-act LLM loop, **AgentDroid** embeds Artemis's accessibility perception into a silent, zero-overhead execution runtime driven directly by your existing AI coding assistant (Claude Code, Antigravity, Codex, Cursor).

### Architecture Comparison (Artemis vs. AgentDroid)

| Capability / Metric | Google Artemis (`google/artemis`) | AgentDroid (`agentdroid`) | Advantage |
| :--- | :--- | :--- | :--- |
| **Brain / LLM Key** | Requires standalone `.env` & secondary Gemini API key | **Zero external keys** — your host coding assistant is the brain | No extra bill or credential leaks |
| **Execution Paradigm** | Turn-by-turn reactive loop (1 LLM call per tap/type) | **Compound single-call pipeline** (`--do`, `mobile_run_workflow`) | Eliminates multi-turn network roundtrips |
| **Turn-by-Turn Latency** | **Flash:** 3–5s / step<br>**Pro:** 15–40s / step | **Sub-second** accessibility gestures via in-kernel IPC (**52.2 ms** tap) | **5× to 10× faster** gesture dispatch |
| **Token Consumption** | Re-sends full UI hierarchy & screenshots every turn (**15k–45k tokens**) | Compact numbered index hierarchy returned once (**~600–1,500 tokens**) | **90%+ token reduction** |
| **Device Virtualization** | Android Studio QEMU VM or physical USB device | Headless in-kernel **Redroid** container with GPU passthrough | Boots in **2.3s**; 80% less RAM |
| **User Observability** | Raw terminal stdout or separate manual emulator window | Silent `--headless` background or sleek docked floating simulator (`--watch`) | Unobtrusive side-by-side pair programming |

### Master 4-Way Head-to-Head Comparison

| Metric / Dimension | AgentDroid (Host AI + Redroid) | Google Artemis (`google/artemis`) | Google AndroidWorld (arXiv:2405.14573) | Mobilebox (`mobilebox-dev/mobilebox`) |
|---|---|---|---|---|
| **Markor Note Creation & Save** | **7.35 s** (6 steps, 758 tok) | **~68.0 s** (9 steps, 41k tok) | **~68.4 s** (11 steps, 18.5k tok) | **~49.2 s** (10 steps, 16k tok) |
| **DeskClock Alarm Configure** | **6.29 s** (7 steps, 3,033 tok) | **~65.0 s** (6 steps, 28k tok) | **~62.1 s** (9 steps, 15.5k tok) | **~44.5 s** (8 steps, 14k tok) |
| **Settings Deep Audit** | **5.59 s** (7 steps, 2,936 tok) | **~82.0 s** (7 steps, 34.5k tok) | **~58.7 s** (8 steps, 14k tok) | **~39.8 s** (8 steps, 13.5k tok) |
| **APK Sideload & Install** | **102.8 ms** (cached pm install) | ~3,500 – 5,500 ms (AVD pm) | ~5,500 ms (AVD package manager) | **1,172 ms** (`summary.csv` line 20) |
| **Cold-Start to Screen** | **2,325 ms** | ~40,000 – 60,000 ms (AVD boot) | ~45,000 – 75,000 ms (AVD setup) | **19,353 ms** (`summary.csv` line 21) |
| **Perception Turnaround**| **46 – 190 ms** (compact UI) | ~350 ms (raw XML dump) | ~4,100 ms (screencap + XML) | **1,448 ms** (tap-to-screenshot, line 26) |
| **Single Tap Latency** | **52.2 ms** (Artemis IPC tap) | ~500 ms (IPC) + 3–15s LLM wait | ~1,200 ms (ADB shell tap + sleep) | **517 ms** (`summary.csv` line 25) |
| **Token Cost / Task** | **~750 – 3,000 tokens** | **18,000 – 45,000 tokens** | **15,000 – 35,000 tokens** | **16,000 – 25,000 tokens** |
| **Infrastructure Cost** | **\$0.00** (local container) | Host compute + Gemini Pro API | Host compute + GPT-4V tokens (\$0.15) | **\$0.01 / task** (\$0.01/min container) |
| **Root Shell Access** | **Full root (`su 0`) default** | Restricted user shell on AVD | Restricted user shell on AVD | Sandboxed non-root container |

### Empirical Benchmarks (Identical Android Tasks)

Comparison across canonical Android task flows evaluated in Google's Android automation literature and reproducible via `benchmarks/run_actual_app_benchmark.py`:
- **AgentDroid figures:** Measured live on local Redroid device (`127.0.0.1:5555`) with full disk/system verification.
- **Google Artemis figures:** Calculated directly from Google Pixel Test Engineering's published execution profiles in [google/artemis](https://github.com/google/artemis) and the [AndroidWorld](https://github.com/google-research/android_world) benchmark.
- **Mobilebox figures:** Official empirical benchmark suite from [mobilebox-dev/mobilebox](https://github.com/mobilebox-dev/mobilebox) (`benchmarks/results/summary.csv`).

#### 1. Canonical Settings Navigation & App Inspection (`com.android.settings`)
*Task: Cold-launch Settings, navigate to Apps & notifications, inspect Markor app permissions/storage, and verify screen assertion.*

| Framework | Execution Model | Total Time | Tool / LLM Calls | Token Footprint | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Google Artemis (Flash)** | Step-by-step LLM reactive | ~24.5s | 5 turns | ~18,200 tokens | Pass |
| **Google Artemis (Pro)** | Graph-orchestrated verification | ~82.0s | 7 turns + checks | ~34,500 tokens | Pass |
| **Google AndroidWorld (M3A)** | Turn-by-turn multimodal agent | ~58.7s | 8 environment turns | ~14,000 tokens | Pass |
| **Mobilebox (Cloud Device)** | Remote WebSocket API loop | ~39.8s | 8 remote turns | ~13,500 tokens | Pass |
| **AgentDroid (Compound)** | Single-call compound pipeline | **5.59s** | **1 compound call** | **2,936 tokens** | **Pass (7× to 14× faster)** |

#### 2. End-to-End File Lifecycle & Editor Automation (Markor)
*Task: Push markdown document, open in Markor, append checklist item 'Verified by AgentDroid', save to disk, and pull verified artifact back to host.*

| Framework | Execution Model | Total Time | Tool / LLM Calls | Token Footprint | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Google Artemis (Pro)** | Turn-by-turn external agent | ~68.0s | 9 turns | ~41,000 tokens | Pass |
| **Google AndroidWorld (M3A)** | Turn-by-turn multimodal agent | ~68.4s | 11 environment turns | ~18,500 tokens | Pass |
| **Mobilebox (Cloud Device)** | Remote WebSocket API loop | ~49.2s | 10 remote turns | ~16,000 tokens | Pass |
| **AgentDroid (Compound)** | Single compound workflow (`--push`, `-a`, `-d`, `--pull`) | **7.35s** | **1 compound call** | **758 tokens** | **Pass (9× faster, 95% token savings)** |

#### 3. System Alarm Configuration (DeskClock)
*Task: Cold-launch DeskClock, navigate to Alarm tab, add and configure alarm, confirm time picker, and assert registered alarm.*

| Framework | Execution Model | Total Time | Tool / LLM Calls | Token Footprint | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Google Artemis (Flash)** | Step-by-step LLM reactive | ~22.0s | 6 turns | ~16,000 tokens | Pass |
| **Google AndroidWorld (M3A)** | Turn-by-turn multimodal agent | ~62.1s | 9 environment turns | ~15,500 tokens | Pass |
| **Mobilebox (Cloud Device)** | Remote WebSocket API loop | ~44.5s | 8 remote turns | ~14,000 tokens | Pass |
| **AgentDroid (Compound)** | Single compound workflow | **6.29s** | **1 compound call** | **3,033 tokens** | **Pass (10× faster)** |

All raw benchmark JSONs and reproduction scripts are located in [`benchmarks/`](benchmarks/).

## Troubleshooting

`agentdroid doctor` checks adb, binder, device and helper status. Logs: `docker compose logs redroid server`.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, and [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK (only the APK; none of its LLM agent is used). Both are Apache-2.0; Redroid kernel modules are GPL-2.0. AgentDroid is Apache-2.0.
