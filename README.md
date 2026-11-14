English | [简体中文](README.zh-cn.md)

# AgentRedroid (`agentdroid`) — Silent General-Purpose Android Device for AI Agents

**AgentRedroid** turns [Redroid (Remote Android in Cloud)](https://github.com/remote-android/redroid-doc) and [Google Artemis](https://github.com/google/artemis) into a **silent, general-purpose Android device** that an AI agent can use for **any task** — searching and installing apps on the fly, browsing the web, opening deep links, pushing/pulling files, reading OTP/notification messages, automating real-world mobile workflows, or testing apps.

Instead of wasting tokens on dozens of back-and-forth MCP tool calls (tap, screenshot, tap, screenshot...), AI agents drive the phone through a **single compound CLI tool (`agentdroid`)** that chains setup, file transfers, app installation, multi-step UI execution (until the required output is obtained), and data extraction into one command.

- **Silent & Headless by Default (`--headless`)**: Runs in the background with zero GUI windows, muted audio streams, root ADB (`ro.secure=0`), disabled animations (`0.0`), skipped setup wizards, and pre-installed **Artemis Accessibility Helper** (`com.artemis.helper`).
- **Live Visual Watch Mode (`--watch`)**: Pass `--watch` (or run `agentdroid watch`) to open a live `scrcpy` window (or Artemis Web Stream) and real-time step telemetry so you can watch what the AI agent is doing on the device.

---

## Table of Contents
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [General-Purpose Compound CLI (`agentdroid`)](#general-purpose-compound-cli-agentdroid)
- [Headless vs. Watch Mode](#headless-vs-watch-mode)
- [Silent Device Provisioning](#silent-device-provisioning)
- [Redroid Base Configuration & Kernel Modules](#redroid-base-configuration--kernel-modules)
- [Native Bridge & GMS Support](#native-bridge--gms-support)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ AI Agent (Antigravity / Claude Code / Codex / Cursor / Custom Agent)    │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ Single compound CLI call (`agentdroid`)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ `agentdroid` Compound Pipeline (`--headless` silent bg | `--watch` UI)  │
│  1. Silent Provisioning Check   4. Artemis Multi-Step Goal Execution    │
│  2. App Search/Install & Grant  5. Until-Output Autonomous Recovery     │
│  3. File Push / URL / Clipboard 6. File Pull / Notifications / JSON     │
└───────────────┬───────────────────────────────────┬─────────────────────┘
                │ ADB + Port 18888 Tunnel           │ HTTP / SSE (:8000)
                ▼                                   ▼
┌───────────────────────────────────┐ ┌───────────────────────────────────┐
│ `agentdroid-device` (Redroid)     │ │ `agentdroid-artemis` Controller   │
│ • Android 11–16 in Docker         │◄┤ • Google Artemis Flash / Pro Loop │
│ • Root ADB (`ro.secure=0`)        │ │ • Planner + Safety Net + Checker  │
│ • Animations=0, Audio=SILENT      │ │ • Live MJPEG & SSE Step Stream    │
│ • ArtemisAccessibilityHelper.apk  │ └───────────────────────────────────┘
└───────────────────────────────────┘
```

---

## Quick Start

### 1. Prerequisites (Linux Host Kernel Modules)
Ensure Docker and the required Android kernel modules (`binder_linux`, `ashmem_linux` or `memfd`) are loaded on your Linux host (see [deploy/](deploy/README.md) for distro-specific guides):

```bash
sudo apt install -y linux-modules-extra-$(uname -r) adb scrcpy
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
sudo modprobe ashmem_linux || true
```

### 2. Configure API Key & Install `agentdroid` CLI

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY / OPEN_ROUTER_API_KEY)

pip install -e .
# Or with uv:
uv tool install -e .
```

### 3. Boot the Silent Android Device + Artemis Controller Stack

```bash
# Starts Redroid + Artemis in Docker Compose and silently provisions the Android device
agentdroid up --headless

# Verify device, root ADB, silent settings, and Artemis Accessibility Helper
agentdroid doctor
```

---

## General-Purpose Compound CLI (`agentdroid`)

AI agents can use `agentdroid` as a complete mobile computer — chaining app search/installation, file push/pull, URL/deep-link opening, clipboard/notification reading, and multi-step natural-language tasks into **one single command**:

### 1. Do Any General Task (Web Research, App Workflows, Data Extraction)

```bash
agentdroid \
  --headless \
  --open-url "https://news.ycombinator.com" \
  --goal "Read the top 5 front-page stories and extract their titles and points" \
  --expect "JSON array of {title, points}" \
  --until-output \
  --json
```

### 2. Search & Install Tools/Apps On the Fly (F-Droid, URL, or Local APK)

If the AI agent needs an app or tool (a browser, PDF reader, markdown editor, terminal, QR scanner, or custom APK), it can search F-Droid or install directly by name/URL/path with all permissions auto-granted:

```bash
# Search F-Droid for any open-source Android tool
agentdroid app search "markdown editor" --json

# Install directly from F-Droid (or HTTPS URL / local path), push a file, use the app, and pull the result!
agentdroid \
  --headless \
  --install "fdroid:net.gsantner.markor" \
  --push ./draft.md:/sdcard/Download/draft.md \
  --launch \
  --step "Open draft.md from Downloads, format the headings, and export/save the file" \
  --pull /sdcard/Download/draft.md:./artifacts/final.md \
  --expect "confirmation that file was saved" \
  --until-output \
  --json
```

### 3. Read Notifications (2FA/OTP Codes, Messages) & Clipboard

```bash
# Read active device notifications or clipboard in a compound run or standalone
agentdroid device notifications --json
agentdroid device clipboard "text to paste on phone"
```

### 4. Run with `--watch` so You Can Watch the AI Agent Live

```bash
agentdroid \
  --watch \
  --goal "Open Settings, check battery and storage usage, then open the browser and search for Weather"
```

### 5. Fast Deterministic Gestures + Compact ~150-Token UI Dump (No LLM Needed)

```bash
# Inspect all visible interactive/labelled elements on screen via Artemis Accessibility Helper (~30ms)
agentdroid ui dump --json

# Chain fast deterministic gestures and dump the resulting screen state in one call
agentdroid --tap 540,1200 --type "hello@example.com" --key ENTER --dump-ui --json
```

---

## Headless vs. Watch Mode

`agentdroid` includes a built-in `scrcpy`-like watcher designed for both background AI agents and human inspection:

| Command / Flag | Behavior |
| :--- | :--- |
| `agentdroid run --headless ...` *(default)* | Executes 100% silently in the background. No `scrcpy` or browser windows open, audio is muted, and a single structured result is returned. |
| `agentdroid run --watch ...` (`-w`) | Spawns a live `scrcpy` window (with `--no-audio --stay-awake --no-control`) and streams real-time Artemis step telemetry (`[Step 1] tap...`) in the terminal while the task runs. |
| `agentdroid run --watch-web ...` | Opens the Artemis Live Web Console (`http://127.0.0.1:8000`) with MJPEG screen streaming and step replay. |
| `agentdroid watch` | Standalone live viewer: attaches `scrcpy` + real-time terminal action stream to the running device at any time (add `--interactive` to allow mouse/keyboard input). |
| `agentdroid watch --headless` | Streams live agent step events and foreground app changes as background JSONL without opening any GUI window. |

---

## Silent Device Provisioning

When `agentdroid up` or `agentdroid provision` runs (via [`scripts/provision-device.sh`](scripts/provision-device.sh)), it automatically configures the Android container for zero-friction AI automation:

1. **Root ADB without prompts**: `ro.secure=0`, `ro.adb.secure=0`, `ro.debuggable=1`
2. **Zero UI animations**: `window_animation_scale=0.0`, `transition_animation_scale=0.0`, `animator_duration_scale=0.0`
3. **No setup wizards or lockscreen**: `device_provisioned=1`, `user_setup_complete=1`, `ro.setupwizard.mode=DISABLED`, `locksettings set-disabled true`, `stay_on_while_plugged_in=7`
4. **No blocking system popups**: `hide_error_dialogs=1`, `package_verifier_enable=0`, `verifier_verify_adb_installs=0`, `heads_up_notifications_enabled=0`
5. **100% silent audio**: `ro.audio.silent=1` and all media/notification/ring/alarm streams muted (`volume=0`)
6. **Pre-installed Artemis Accessibility Helper**: [`packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk`](packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk) is pre-installed and bound in `enabled_accessibility_services` so UI tree dumps and gestures execute in ~30ms without cold-start delay.
7. **Auto-granted runtime permissions & AppOps**: Every APK installed via `agentdroid` has all `android.permission.*` runtime permissions and special AppOps (`SYSTEM_ALERT_WINDOW`, `MANAGE_EXTERNAL_STORAGE`, `POST_NOTIFICATIONS`, `WRITE_SETTINGS`) automatically granted.

---

## Redroid Base Configuration & Kernel Modules

Supported Redroid images (configurable via `REDROID_IMAGE` in `.env`):
- Android 16 (`redroid/redroid:16.0.0-latest`, `redroid/redroid:16.0.0_64only-latest`)
- Android 15 (`redroid/redroid:15.0.0-latest`, `redroid/redroid:15.0.0_64only-latest`)
- Android 14 (`redroid/redroid:14.0.0-latest`, `redroid/redroid:14.0.0_64only-latest`)
- Android 13 (`redroid/redroid:13.0.0-latest`, `redroid/redroid:13.0.0_64only-latest`)
- Android 12 (`redroid/redroid:12.0.0-latest`, `redroid/redroid:12.0.0_64only-latest`)
- Android 11 (`redroid/redroid:11.0.0-latest`)

| Boot Param | Description | Default in `docker-compose.yml` |
| --- | --- | --- |
| `androidboot.redroid_width` | Display width | `1080` |
| `androidboot.redroid_height` | Display height | `1920` |
| `androidboot.redroid_dpi` | Display DPI | `320` |
| `androidboot.redroid_fps` | Display FPS | `30` |
| `androidboot.redroid_gpu_mode` | `auto`, `host` (GPU accelerated), or `guest` (software rendering) | `guest` |
| `androidboot.use_memfd` | Use `memfd` instead of deprecated `ashmem` | `true` |
| `ro.secure=0` | Root ADB shell provided by default | `0` |

See [deploy/README.md](deploy/README.md) for distro-specific kernel module instructions (Ubuntu, Debian, Fedora, Arch, CentOS, WSL, Kubernetes, LXC).

---

## Native Bridge & GMS Support

- **ARM apps on x86_64**: Published `redroid` images include `libndk_translation`. See [@zhouziyang/libndk_translation](https://github.com/zhouziyang/libndk_translation) for details.
- **GMS (Google Mobile Services)**: Can be added via Open GApps, MicroG, or MindTheGapps. See [android-builder-docker](./android-builder-docker) for custom image building.

---

## Troubleshooting

- Run `agentdroid doctor` (or `agentdroid doctor --json`) to inspect host tools, kernel `binder` support, ADB root status, silent device settings, Artemis Accessibility Helper reachability, and the Artemis Controller daemon.
- Collect low-level Redroid container debug blobs with `./debug.sh agentdroid-device`.

---

## License

- **Redroid** and **Google Artemis** components are licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
- Redroid kernel modules are under [GPL v2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html).
