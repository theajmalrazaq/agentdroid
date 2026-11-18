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

### 2. One-Shot Execution (Zero Custom Scripts, Zero Ping-Pong Loops)
Ask your agent to **execute tasks directly in one shot** rather than writing `.py`/`.sh` wrapper scripts or running step-by-step `dump -> click -> dump` loops (enforced in [`AGENTS.md`](AGENTS.md) and [`skills/agentdroid/SKILL.md`](skills/agentdroid/SKILL.md)):

- **Host Coding Agent (`mobile_run_workflow` / compound CLI):** Chains launch, waits, conditionals (`if-visible:`), inline regex extraction (`capture:` + `{{var}}`), fills, and assertions in **one call** (`~3.8 s` mean across 13 verified E2E apps).
- **Autonomous Closed-Loop (`agentdroid ai`):** Runs TypeSafe AI `jev-latest` for unseen dynamic flows without writing code.

```bash
# Compound one-shot CLI (reads screen in ~433 tokens, branches, types, verifies):
agentdroid --headless --open-url "https://news.ycombinator.com" \
  -d "wait-any:Hacker News|More" -d "scroll:down" --assert-text "Hacker News" --json

# Multi-step Android workflow in one command (push -> edit -> save -> pull -> assert):
agentdroid --headless --launch com.android.deskclock \
  -d "wait-text:STOPWATCH@5" -d "click:STOPWATCH" -d "click:START" -d "wait-text:Pause@5" --json

# Autonomous Jev System One loop on unseen UIs:
agentdroid ai "Compute 42 + 58 = 100" --launch org.fossify.math --json

# Floating phone overlay window to watch live:
agentdroid --watch --launch com.android.settings
```

## Why Redroid instead of the Android Studio emulator?

Redroid runs Android as a container on the host kernel (no QEMU VM), so it typically needs far less RAM and boots in seconds. Figures vary by host; measure on yours.

## Benchmark

Evaluated on live hardware (`redroid11_x86_64`, Android 11, `1080x2400`) via [`benchmarks/benchmark.py`](benchmarks/benchmark.py) across `13` verifiable real-app tasks (SQLite, `ContentProvider`, `/sdcard/`, and UI-delta verified) against published baselines ([per-task breakdown & logs](benchmarks/README.md)):

| Platform / Agent | Task Success Rate | Avg Task Time | Action + Observe Latency | Payload / Step | Boot / Install |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentDroid (1-Turn Compound / MCP)** | **100.0%** (`13/13` verified) | **2.35 s** (`30.6 s` total · **32.4x** vs Vostride) | **0.83 ms** tap · **16.4 ms** UI loop (`82.9 ms` burst) | **430–674 tok** (`1.7–2.7 KB` text) | **11.9 s** boot · **910 ms** APK |
| **AgentDroid + Jev (`jev-latest` AI)** | **92.3%** (`12/13` verified) | **10.33 s** (`323–558 ms`/turn · **10.6x** vs Vostride) | **0.83 ms** tap · **16.4 ms** UI loop | **430–674 tok** (`1.7–2.7 KB` text) | **11.9 s** boot · **910 ms** APK |
| **Vostride** *(matched `9` tasks)* | Baseline (`9` matched) | **91.9 s** (`827.0 s` total) | **517 ms** tap · **8–15 s** VLM | **1,445 tok** (`125 KB` PNG) | Cloud VM |
| **Google Artemis** *(AndroidWorld)* | **99.1%** *(published)* | **180–300 s** | **150–400 ms** A11y · **3–40 s** LLM | Screenshot + XML | Standalone stack |
| **AutoGLM / GLM-4V Mobile** | **80.2%** *(published)* | **60–120 s** | **500 ms** `adb` · **6–10 s** VLM | ~1,200 tok PNG | Host + Device |
| **Mobile-Agent-v2 / AppAgent** | **73.3%** *(published)* | **90–180 s** | **520 ms** `adb` · **7–14 s** VLM | PNG + OCR crops | Host + Python |
| **UI-TARS (ByteDance)** | **46.6%** *(published)* | **45–90 s** | **500 ms** `adb` · **4–8 s** VLM | Full PNG | Dedicated GPU |
| **Google M3A** *(`arXiv:2405.14573v3`)* | **30.6%** *(A11y)* · **25.4%** *(SoM)* | **~234.0 s** | **550 ms** `adb` · **12–25 s** VLM | XML / SoM PNG | AVD QEMU (`49.2 s` boot) |
| **Mobilebox** *(Nuremberg, `summary.csv`)* | Infra baseline | **24.6–37.9 s** *(demo)* | **517 ms** tap · **1,448 ms** cap | `50+ KB` PNG | **17.8 s** boot · **1,172 ms** APK |
| **Android Studio AVD (KVM On/Off)** | Static scripts (`0%` adapt) | Script dependent | **150–1,880 ms** · **1–18 s** cap | Static selectors | **49.2 s / 13.0 min** boot |

## Troubleshooting

`agentdroid doctor` checks adb, binder, device, and helper status. Logs: `docker compose logs redroid server`.
Use `agentdroid device clean` to flush background apps and reclaim RAM.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK, and [TypeSafe AI](https://typesafe.ai) for sub-second calibrated decision models. AgentDroid is Apache-2.0.
