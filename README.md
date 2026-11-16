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

While [Google Artemis](https://github.com/google/artemis) runs an autonomous standalone LLM agent loop (`Flash` ~3–5 s/step, `Pro` ~15–40 s/step), **AgentDroid** embeds Artemis's accessibility helper APK (`v1.2.0`) into a local execution runtime driven directly by your existing AI coding assistant via compound pipelines or MCP.

> **Verification & Scope Note (2026-11-16):** Every AgentDroid figure below was measured live on `redroid11_x86_64` (Android 11, `1080x2400`, zero mocked or simulated runs) and saved in [`benchmarks/results/`](benchmarks/results/). External figures come strictly from primary published sources without extrapolating missing per-app metrics:
> - **Mobilebox (`mobilebox-dev/mobilebox`):** [`benchmarks/results/summary.csv`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/results/summary.csv) (`2026-11-08`), [`benchmarks/README.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/benchmarks/README.md), `README.md`, and [`examples/RUNS.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/examples/RUNS.md).
> - **Google Research AndroidWorld:** Rawles et al. ([arXiv:2405.14573v3](https://arxiv.org/html/2405.14573v3), Table 3 & Section 4.3).
> - **Google Artemis (`google/artemis`):** Repository `README.md` & [`androidworld_leaderboard.png`](https://github.com/google/artemis/blob/main/docs/assets/androidworld_leaderboard.png) (**99.1% Pass@1** across `116` tasks).

### 1. Infrastructure Parity Benchmark (`benchmarks/benchmark_agentdroid.py`)

Measured against Mobilebox's published benchmark methodology using [`org.fossify.math`](https://f-droid.org/packages/org.fossify.math/) (`7.05 MB` F-Droid APK here vs `~4 MB` v1.4.0 in Mobilebox's suite). AgentDroid runs in a persistent local Redroid Docker container (`STOPSIGNAL SIGKILL` + ADB `CNXN` pre-probe); cold-start rows below measure a full `docker restart agentdroid-device` (`n=3`), whereas normal warm container usage starts with `0 ms` boot wait. Cloud providers (`Mobilebox`, `Limrun`) serve pre-warmed / pooled cloud instances from Nuremberg.

| Metric | AgentDroid (Local Redroid `127.0.0.1:5555`) | Mobilebox EU (Nuremberg, `summary.csv`) | Limrun (Nuremberg, `summary.csv`) | Local AVD KVM On (`summary.csv`) | Local AVD KVM Off (`summary.csv`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cold-Start `ready` (median)** | **9,767 ms** (`n=3`, p90 `9,886`) | **17,833 ms** (`n=10`, p90 `18,072`) | **338 ms** (`n=10`, p90 `454`) | **49,231 ms** (+`75,307 ms` setup) | **782,342 ms** (`13.0 min`) |
| **`cold_start_to_screenshot` (median)** | **10,963 ms** (`n=3`, p90 `11,096`) | **19,353 ms** (`n=10`, p90 `19,487`) | **977 ms** (`n=10`, p90 `1,067`) | **50,009 ms** (`n=5`, p90 `50,278`) | **812,681 ms** (`13.5 min`) |
| **APK Install (`org.fossify.math`)** | **675 ms** fresh (`n=3`) · **648 ms** `-r` (`n=5`) | **1,172 ms** (`n=10`, p90 `1,544`) | **850 ms** (`n=10`, p90 `954`) | **6,091 ms** (`n=5`, p90 `7,307`) | **125,911 ms** (`n=1`) |
| **Single Tap (median)** | **1.82 ms** `InputDaemon` (`n=10`) · **3.06 ms** IPC global (`n=20`)* | **517 ms** (`n=100`, p90 `526`) | **76 ms** (`n=100`, p90 `78`) | **150 ms** (`n=50`, p90 `383`) | **1,880 ms** (`n=10`, p90 `5,107`) |
| **`tap_to_screenshot` (median)** | **758 ms** (`adb tap` + `adb screencap`, `n=10`, p90 `767`) | **1,448 ms** (`n=100`, p90 `1,487`) | **384 ms** (`n=100`, p90 `402`) | **1,035 ms** (`n=50`, p90 `3,523`) | **18,691 ms** (`n=10`, p90 `23,373`) |
| **Perception Turnaround (AgentDroid IPC)** | **5.67 ms** UI dump (`n=20`) · **6.46 ms** `tap_to_ui_dump` (`n=10`) · **72.0 ms** atomic XML+PNG (`n=10`) | Screenshot-first (`1,448 ms`) | Screenshot-first (`384 ms`) | AVD ADB pull (`1,035 ms`) | AVD ADB pull (`18,691 ms`) |
| **Container Billing** | **\$0.00 / min** (local host Docker) | **\$0.01 / min** (parked free) | Managed cloud pricing | Local CI / host VM | Local CI (non-KVM) |

*\*Architectural note on tap latency & cold restarts: On hosts where Linux `uinput` is unloaded (`has_touchscreen_source: false`), headless Redroid only exposes a virtual keyboard (`0x00000301`), causing Android's `AccessibilityService.dispatchGesture` (`/action cmd=tap`) to return `success=False`. Instead of falling back to `adb shell input tap` (`552.38 ms` median, `n=20`), `AccessibilityHelperClient` routes gestures over a persistent loopback TCP daemon (`com.agentdroid.InputDaemon` on `127.0.0.1:18889` calling `InputManager.injectInputEvent` directly) in **`1.82 ms`** median (`p90 1.95 ms`, `n=10`), while `dump_compact_ui` derives non-overlay foreground package/activity from `/ping` in **`5.67 ms`** median (`p90 7.07 ms`). Setting `STOPSIGNAL SIGKILL` and pre-probing `adbd` with a 24-byte `CNXN` check before `adb connect` eliminates Docker's 10s `SIGTERM` wait and `adb` server handshake stalls during `docker restart` (`9,767 ms` `ready`, `10,963 ms` `cold_start_to_screenshot`). See [`benchmarks/README.md`](benchmarks/README.md) for all `summary.csv` rows including `Mobilebox CI` and `Phone Harness`.*

### 2. Measured Real-App End-to-End Workflows vs. Published Agent Baselines

AgentDroid tasks below run end-to-end against live Android apps (`benchmarks/run_actual_app_benchmark.py`) with strict state-delta or disk verification (`all_passed: true`), executing **4–8 UI actions per single compound host-agent turn** (`1` LLM decision turn per workflow once screen layout is known):

| Workflow / Published Benchmark | System & Execution Model | Measured Time / Cadence | Measured Steps / Turns & Verification | Source |
| :--- | :--- | :--- | :--- | :--- |
| **Markor Markdown Note Append & Save** (`net.gsantner.markor`) | **AgentDroid** (`CompoundPipeline`, single turn) | **3.15 s** wall-clock | **4 UI steps**, 1 host turn; disk pull `50 B → 81 B`, exact marker & header verified | [`benchmark_actual_apps_results.json`](benchmarks/results/benchmark_actual_apps_results.json) |
| **DeskClock Alarm Add & State Delta** (`com.android.deskclock`) | **AgentDroid** (`AndroidEngine` single workflow) | **2.54 s** wall-clock | **4 UI steps**, 1 host turn; `digital_clock` count **`2 → 3`**, `ON` count **`0 → 1`** verified | [`benchmark_actual_apps_results.json`](benchmarks/results/benchmark_actual_apps_results.json) |
| **Settings App Permissions Audit** (`com.android.settings`) | **AgentDroid CLI** (`agentdroid run --headless`) | **7.68 s** subprocess (`7.53 s` internal) | **8 UI steps**, 1 host turn; asserted `"Permissions"` + `"Storage"` (`0` crashes) | [`benchmark_actual_apps_results.json`](benchmarks/results/benchmark_actual_apps_results.json) |
| **Fossify Math Install + `42 + 58 = 100`** (`org.fossify.math`) | **AgentDroid CLI** (`adb install` + `--headless`) | **0.59 s** install + **4.05 s** E2E (**4.64 s** total) | **7 UI steps**, 1 host turn; asserted `result == "100"` (`0` crashes) | [`benchmark_actual_apps_results.json`](benchmarks/results/benchmark_actual_apps_results.json) |
| **Wikipedia Matterhorn Demo** (Cloud Android 14) | **Mobilebox** (MCP turn-by-turn demo) | **24.6 s** (from home screen) | **8 MCP calls**; cloud container `@ \$0.01/min` | [`mobilebox/README.md`](https://github.com/mobilebox-dev/mobilebox) |
| **Settings > Display Brightness E2E** (incl. phone create+delete) | **Mobilebox** (curl / TS / Python / LLM SDKs) | **24.7 – 37.9 s** | Multi-call REST/MCP flows (`examples/RUNS.md`, `2026-11-04/05`) | [`mobilebox/examples/RUNS.md`](https://github.com/mobilebox-dev/mobilebox/blob/main/examples/RUNS.md) |
| **AndroidWorld 116-Task Suite Avg** (20 apps, GPT-4 Turbo) | **AndroidWorld M3A** (turn-by-turn VLM / text) | **234 s** (`3.9 min`) multimodal · **150 s** (`2.5 min`) text-only | **30.6%** SR (M3A a11y tree), **25.4%** SR (M3A SoM), **80.0%** Human (`116` tasks) | [`arXiv:2405.14573v3`](https://arxiv.org/html/2405.14573v3) (Table 3 & §4.3) |
| **AndroidWorld 116-Task Suite SOTA** (Multi-model VLM agent) | **Google Artemis** (Flash / Pro autonomous graph) | **~3–5 s/step** (Flash) · **~15–40 s/step** (Pro) | **99.1% Pass@1** completion rate across `116` AndroidWorld tasks | [`google/artemis`](https://github.com/google/artemis) · [`leaderboard`](https://github.com/google/artemis/blob/main/docs/assets/androidworld_leaderboard.png) |

### 3. Live Perception Payload & Token Comparison (`1080x2400`)

Measured directly from live app windows via `benchmarks/benchmark_agentdroid.py`:

| Live App Window | Raw XML (`uiautomator` / `/snapshot?fields=xml`) | AgentDroid `formatted_text` (`AndroidEngine`) | Reduction vs. Raw XML | High-Detail Screenshot (`1080x2400` PNG) |
| :--- | :--- | :--- | :--- | :--- |
| **Fossify Math** (`34` XML nodes) | `13,721 B` (`~3,430` est. tok @ 4 chars/tok) | **`1,730 chars`** (**`~433` est. tok**, 28 elements) | **87.4% smaller** (`7.9x`) | `54,662 B` · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic `706x1568`) |
| **Android Settings** (`47` XML nodes) | `18,959 B` (`~4,740` est. tok @ 4 chars/tok) | **`2,774 chars`** (**`~694` est. tok**, 40 elements) | **85.4% smaller** (`6.8x`) | `125,747 B` · **1,445 tok** (OpenAI `2x4` tiles) / **1,477 tok** (Anthropic `706x1568`) |

All reproduction scripts and raw JSON datasets live under [`benchmarks/`](benchmarks/).

## Troubleshooting

`agentdroid doctor` checks adb, binder, device and helper status. Logs: `docker compose logs redroid server`.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, and [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK (only the APK; none of its LLM agent is used). Both are Apache-2.0; Redroid kernel modules are GPL-2.0. AgentDroid is Apache-2.0.
