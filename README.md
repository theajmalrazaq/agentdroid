English | [简体中文](README.zh-cn.md)

# AgentDroid (`agentdroid`) — Silent General-Purpose Android Computer for AI Agents

**AgentDroid** combines [Redroid (Remote Android in Cloud)](https://github.com/remote-android/redroid-doc) and [Google Artemis](https://github.com/google/artemis) into a **silent, headless-by-default Android device** that any AI agent can use as a general-purpose mobile computer — searching & installing apps on the fly, browsing the web, opening deep links, pushing/pulling files, reading OTP/notification messages, automating real-world mobile workflows, or testing APKs.

Instead of wasting tokens on dozens of back-and-forth MCP tool calls (tap, screenshot, tap, screenshot...), AI agents drive the phone through **one compound CLI tool (`agentdroid`)** that chains setup, file transfers, app installation, multi-step UI execution (until the required output is obtained), and data extraction into a single command.

- **One-Command Install & Auto AI-Agent Setup (`./install.sh`)**: Installs host dependencies & kernel modules, puts `agentdroid` on `PATH`, boots the silent Android container, and automatically mounts the `agentdroid` skill & rules into **Antigravity, Claude Code, Codex, Cursor, and Windsurf**.
- **Silent & Headless by Default (`--headless`)**: Runs in the background with zero GUI windows, muted audio streams, root ADB (`ro.secure=0`), disabled animations (`0.0`), skipped setup wizards, and pre-installed **Artemis Accessibility Helper** (`com.artemis.helper`).
- **Latest Android 16 & Modern Native UI/UX**: Defaults to **Android 16** (`redroid/redroid:16.0.0_64only-latest`), crisp **440 DPI**, **60 FPS**, modern **1080×2400 (20:9)** phone ratio, system-wide **Dark Theme**, and **Gesture Navigation** (no ugly retro 3-button bar).
- **Floating Mobile Simulator Watch Mode (`--watch`)**: Opens a sleek, floating phone overlay (`412×892`, `--always-on-top`) styled like macOS iOS Simulator — sits right next to your terminal/editor instead of taking over the full display!
- **Drastically More Lightweight than Android Studio**: Runs directly as a container sharing the host Linux kernel (~1.2 GB RAM, 5s boot) instead of QEMU full-system hardware emulation (4–8 GB RAM, 60s boot).

---

## Table of Contents
- [One-Command Install & Setup](#one-command-install--setup)
- [How to Prompt Your AI Agent](#how-to-prompt-your-ai-agent)
- [Is Redroid More Lightweight than Android Studio?](#is-redroid-more-lightweight-than-android-studios-emulator)
- [Architecture](#architecture)
- [General-Purpose Compound CLI (`agentdroid`)](#general-purpose-compound-cli-agentdroid)
- [CLI Reference (`agentdroid`)](#cli-reference-agentdroid)
- [Headless vs. Watch Mode (Floating Mobile Simulator)](#headless-vs-watch-mode-floating-mobile-simulator)
- [Silent Device Provisioning & Modern UI/UX](#silent-device-provisioning--modern-uiux)
- [Redroid Base Configuration & Kernel Modules](#redroid-base-configuration--kernel-modules)
- [Native Bridge & GMS Support](#native-bridge--gms-support)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## One-Command Install & Setup

Run **one command** to install host tools (`adb`, `scrcpy`, Redroid kernel modules), link `agentdroid` globally on your `PATH`, mount the `agentdroid` skill & operating rules into all your AI coding assistants, and start the silent Android device:

```bash
# Option A: One-liner from anywhere
curl -fsSL https://raw.githubusercontent.com/theajmalrazaq/agentsredroid/master/install.sh | bash

# Option B: From a local clone
git clone https://github.com/theajmalrazaq/agentsredroid.git && cd agentsredroid
./install.sh
```

What `./install.sh` (and `agentdroid setup`) does automatically:
1. **Host & Kernel Modules**: Installs `adb` and `scrcpy` if missing, and loads/persists Linux kernel modules (`binder_linux`, `ashmem_linux`).
2. **Global CLI**: Links `agentdroid` into `~/.local/bin` and `/usr/local/bin` so it runs anywhere.
3. **Zero API Keys / Zero `.env` Required**: Your host AI agent (Claude Code, Antigravity, Codex, Cursor, etc.) **is already the brain**. `agentdroid` gives it eyes (compact screen UI dumps in ~150 tokens) and hands (`--click`, `--fill`, `--scroll`, `--do`) directly over ADB and the on-device Artemis Accessibility Helper.
4. **AI Agent Skill & Rule Mounting**: Automatically installs [`skills/agentdroid/SKILL.md`](skills/agentdroid/SKILL.md) and [`AGENTS.md`](AGENTS.md) into:
   - **Antigravity / Gemini**: `~/.gemini/jetski/skills/agentdroid/SKILL.md` & `~/.gemini/GEMINI.md`
   - **Claude Code**: `~/.claude/skills/agentdroid/SKILL.md` & `~/.claude/rules/agentdroid.md`
   - **Codex CLI**: `~/.codex/skills/agentdroid/SKILL.md` & `~/.codex/AGENTS.md`
   - **Cursor**: `~/.cursor/rules/agentdroid.mdc`
   - **Windsurf**: `~/.codeium/windsurf/memories/global_rules.md`
   - **Universal Agents**: `~/.agents/skills/agentdroid/SKILL.md`
5. **Silent Android Boot**: Starts the Docker Compose stack (`agentdroid-device` + `agentdroid-artemis`) and provisions the Android instance for silent background operation.

---

## How to Prompt Your AI Agent

Once `./install.sh` finishes, open **Antigravity, Claude Code, Codex, Cursor, or Windsurf** in any workspace and ask it to use `agentdroid` for any task:

- **General Android Tasks (Silent Background)**:
  > *"Use `agentdroid` to open Hacker News in the browser, read the top 5 stories, and save a summary."*
- **Install Tools On the Fly & Process Files**:
  > *"Use `agentdroid` to find and install a markdown or PDF app on Android, push `./report.md` to the device, format and export it, and pull the result back."*
- **Read 2FA / Notifications / Messages**:
  > *"Use `agentdroid` to sign into the app, read the verification code from Android notifications, complete login, and return the dashboard state."*
- **Build & Test an Android App**:
  > *"Build the debug APK, use `agentdroid` to install it with all permissions, test the onboarding and settings screens, check for crashes, and return a screenshot."*
- **Watch Live While the AI Works (`--watch`)**:
  > *"Use `agentdroid --watch` to open YouTube and play a lofi stream so I can watch what you're doing on the screen."*

---

## Is Redroid More Lightweight Than Android Studio's Emulator?

**Yes — Redroid is dramatically lighter, faster, and more resource-efficient than Android Studio's Android Emulator (AVD).**

### 1. Architectural Difference: Containerization vs. Full-System Emulation

- **Android Studio AVD (Heavyweight QEMU Hypervisor)**:
  Android Studio's emulator boots a **complete guest operating system inside a QEMU virtual machine**. It runs an isolated Linux guest kernel, virtualizes hardware controllers (memory controllers, virtual NICs, virtual disks, CPU instruction translations), and requires a dedicated guest memory heap.
- **Redroid (Lightweight AIC - Android in Cloud Container)**:
  Redroid uses **native Linux containerization (cgroups + namespaces)**. It shares the **host Linux kernel directly** via native IPC kernel modules (`binder_linux`, `memfd`/`ashmem`). There is **zero virtualization overhead, no guest kernel, and no QEMU hardware emulation**. Android processes run directly as native processes on your host CPU.

### 2. Side-by-Side Comparison

| Metric | AgentDroid (`agentdroid`) | Android Studio AVD (Emulator) | Why Redroid Wins |
| :--- | :--- | :--- | :--- |
| **RAM Footprint** | **~1.2 GB – 1.8 GB** | **4 GB – 8 GB+** *(+ 4–6 GB for Android Studio IDE)* | Redroid only runs Android system services; no guest VM memory allocation. |
| **Boot Time** | **5 – 10 seconds** | **30 – 90+ seconds** *(cold boot)* | Starting container processes vs. booting an entire virtual machine kernel. |
| **CPU Overhead** | **Near-zero idle CPU (~1–2%)** | **High CPU spikes (15–40% idle)** | Native Linux process execution vs. QEMU instruction translation traps. |
| **Disk Size** | **~1.5 GB** compressed container image | **15 GB – 30 GB** per virtual device | Layered Docker image vs. full virtual disk images (`system.img`, `userdata.img`). |
| **Concurrent Instances** | **5 to 10+ instances** on a modest server/laptop | **1 to 2 instances max** before host thrashing | AIC containers share host memory pages; QEMU locks exclusive RAM per VM. |
| **Headless Automation** | **100% silent by default** (`--headless`) | Complex setup (`-no-window -no-audio`) | Redroid is built from the ground up for cloud & autonomous agent workloads. |
| **GPU Requirement** | **Runs anywhere** (software `guest` or GPU `host`) | Often crashes on VPS/cloud without GPU passthrough | Pure software rendering fallback works out-of-the-box on every cloud VM. |

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

### 1. General Task: Install App, Push File, Open & Edit via Semantic Actions
You can install any tool/app on the fly (from F-Droid, HTTPS URL, or APK), push workspace files, launch, and execute semantic UI actions:

```bash
# Example: Install Markor from F-Droid, push notes.md, edit, save, and pull back!
agentdroid \
  --headless \
  --install "fdroid:net.gsantner.markor" \
  --push ./notes.md:/sdcard/Download/notes.md \
  --launch \
  --click "Open from storage" \
  --click "notes.md" \
  --click "Edit" \
  --type "Updated by AI Agent" \
  --click "Save" \
  --pull /sdcard/Download/notes.md:./artifacts/notes_updated.md \
  --notifications \
  --json
```

### 2. Multi-Step Sequential UI Chains with `-d` / `--do`
AI agents can chain multiple sequential actions in strict order:

```bash
agentdroid \
  --headless \
  --launch "com.android.settings" \
  --do "scroll-to:About" \
  --do "click:About" \
  --do "scroll-to:Android version" \
  --assert-text "Android" \
  --json
```

Supported `--do` verbs: `click:<text_or_#id>`, `fill:<sel>=<text>`, `scroll:down|up`, `scroll-to:<text>`, `key:<HOME|BACK|ENTER>`, `tap:x,y`, `type:<text>`, `sleep:<sec>`.

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
  --launch "com.android.settings" \
  --do "click:Display" \
  --do "click:Dark theme"
```

### 5. Fast Deterministic Gestures + Compact ~150-Token UI Dump

```bash
# Inspect all visible interactive/labelled elements on screen via Artemis Accessibility Helper (~30ms)
agentdroid ui dump --json

# Chain fast deterministic gestures and dump the resulting screen state in one call
agentdroid --tap 540,1200 --type "hello@example.com" --key ENTER --dump-ui --json
```

---

## CLI Reference (`agentdroid`)

| Subcommand | Description | Example |
| :--- | :--- | :--- |
| `agentdroid setup` | One-command setup: link CLI, write `.env`, mount AI agent skills/rules, boot stack | `agentdroid setup --api-key $GEMINI_API_KEY` |
| `agentdroid [run] ...` | Execute compound workflow (install, push/pull, open URL, AI goals, crash/UI check) | `agentdroid -i app.apk --launch -g "Log in" -u --json` |
| `agentdroid watch` | Watch live via `scrcpy`/Web (`--watch`) or stream background JSONL (`--headless`) | `agentdroid watch` / `agentdroid watch --headless` |
| `agentdroid app` | `search`, `install` (APK/URL/`fdroid:`), `grant`, `launch`, `stop`, `clear`, `list` | `agentdroid app search "browser" --json` |
| `agentdroid device` | `push`, `pull`, `open` (URLs/deep links), `clipboard`, `notifications`, `shell` | `agentdroid device notifications --json` |
| `agentdroid ui` | Sub-second `dump`, `tap`, `type`, `swipe`, `key`, `screenshot` via A11y Helper | `agentdroid ui dump --json` |
| `agentdroid pipeline` | Execute declarative multi-step JSON pipeline file | `agentdroid pipeline examples/app-test-pipeline.json --json` |
| `agentdroid up` / `down` | Start or stop the Redroid + Artemis Docker Compose stack | `agentdroid up --headless` / `agentdroid down` |
| `agentdroid provision` | Apply silent AI agent settings & install/bind Artemis Accessibility Helper | `agentdroid provision --force` |
| `agentdroid doctor` | Full health check of host tools, `binder`, root ADB, A11y Helper, and Artemis | `agentdroid doctor --json` |

---

## Headless vs. Watch Mode (Floating Mobile Simulator)

`agentdroid` includes a built-in mobile watcher designed for both silent background AI agents and human inspection:

| Command / Flag | Behavior |
| :--- | :--- |
| `agentdroid run --headless ...` *(default)* | **Silent Background Mode**: Executes 100% silently in the background. No GUI windows open, audio is muted, animations are 0.0, and a single structured JSON result is returned. |
| `agentdroid run --watch ...` (`-w`) | **Floating Phone Simulator Overlay**: Opens a sleek, floating phone simulator window (`412×892`, `--always-on-top`) styled like macOS iOS Simulator — stays docked next to your terminal/code without taking over your screen! Streams real-time step telemetry. |
| `agentdroid run --watch --borderless` | **Borderless Screen Overlay**: Floats the phone screen borderless without window chrome. |
| `agentdroid run --watch --interactive` | **Interactive Control**: Allows mouse clicks and keyboard typing directly inside the simulator watch window. |
| `agentdroid run --watch-web ...` | **Web Console Stream**: Opens the Artemis Live Web Console (`http://127.0.0.1:8000`) with MJPEG screen streaming and step replay. |
| `agentdroid watch` | **Standalone Live Viewer**: Attaches the floating mobile simulator window to the running Android device at any time. |
| `agentdroid watch --headless` | **Telemetry Stream**: Streams live agent step events and foreground app changes as background JSONL without opening any GUI window. |

---

## Silent Device Provisioning & Modern UI/UX

When `agentdroid up` or `agentdroid provision` runs (via [`scripts/provision-device.sh`](scripts/provision-device.sh)), it automatically configures the Android container for zero-friction AI automation and polished native UI/UX:

1. **Modern Android 16 Native UI/UX**:
   - **System-wide Dark Theme by default**: `cmd uimode night yes` / `ui_night_mode=2` (eliminates blinding white screens).
   - **Gesture Navigation**: `com.android.internal.systemui.navbar.gestural` / `navigation_mode=2` (eliminates the bulky retro 3-button navigation bar).
   - **Clean Phone Haptics & Audio**: Mutes all sounds (`volume=0`, `ro.audio.silent=1`), disables touch vibrations (`haptic_feedback_enabled=0`), and disables camera/lock clicks.
   - **Crisp Density & 60 FPS**: Rendered at **440 DPI** and **60 FPS** on a modern **1080×2400 (20:9)** mobile viewport.
2. **Root ADB without prompts**: `ro.secure=0`, `ro.adb.secure=0`, `ro.debuggable=1`
3. **Zero UI animations**: `window_animation_scale=0.0`, `transition_animation_scale=0.0`, `animator_duration_scale=0.0`
4. **No setup wizards or lockscreen**: `device_provisioned=1`, `user_setup_complete=1`, `ro.setupwizard.mode=DISABLED`, `locksettings set-disabled true`, `stay_on_while_plugged_in=7`
5. **No blocking system popups**: `hide_error_dialogs=1`, `package_verifier_enable=0`, `verifier_verify_adb_installs=0`, `heads_up_notifications_enabled=0`
6. **Pre-installed Artemis Accessibility Helper**: [`packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk`](packages/artemis-accessibility-helper/ArtemisAccessibilityHelper.apk) is pre-installed and bound in `enabled_accessibility_services` so UI tree dumps (~150 tokens) and gestures execute in ~30ms without cold-start delay.
7. **Auto-granted runtime permissions & AppOps**: Every APK installed via `agentdroid` has all `android.permission.*` runtime permissions and special AppOps (`SYSTEM_ALERT_WINDOW`, `MANAGE_EXTERNAL_STORAGE`, `POST_NOTIFICATIONS`, `WRITE_SETTINGS`) automatically granted.

---

## Redroid Base Configuration & Kernel Modules

Supported Redroid images (defaults to **Android 16**, configurable via `REDROID_IMAGE` in `.env`):
- **Android 16 (`redroid/redroid:16.0.0_64only-latest`, `redroid/redroid:16.0.0-latest`) — Default**
- Android 15 (`redroid/redroid:15.0.0-latest`, `redroid/redroid:15.0.0_64only-latest`)
- Android 14 (`redroid/redroid:14.0.0-latest`, `redroid/redroid:14.0.0_64only-latest`)
- Android 13 (`redroid/redroid:13.0.0-latest`, `redroid/redroid:13.0.0_64only-latest`)
- Android 12 (`redroid/redroid:12.0.0-latest`, `redroid/redroid:12.0.0_64only-latest`)
- Android 11 (`redroid/redroid:11.0.0-latest`)

| Boot Param | Description | Default in `docker-compose.yml` |
| --- | --- | --- |
| `androidboot.redroid_width` | Display width | `1080` |
| `androidboot.redroid_height` | Display height (modern 20:9 ratio) | `2400` |
| `androidboot.redroid_dpi` | Display DPI (crisp flagship density) | `440` |
| `androidboot.redroid_fps` | Display FPS | `60` |
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
