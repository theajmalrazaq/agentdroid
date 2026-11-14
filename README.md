English | [简体中文](README.zh-cn.md)

# AgentRedroid (`agentdroid`) — Silent General-Purpose Android Computer for AI Agents

**AgentRedroid** combines [Redroid (Remote Android in Cloud)](https://github.com/remote-android/redroid-doc) and [Google Artemis](https://github.com/google/artemis) into a **silent, headless-by-default Android device** that any AI agent can use as a general-purpose mobile computer — searching & installing apps on the fly, browsing the web, opening deep links, pushing/pulling files, reading OTP/notification messages, automating real-world mobile workflows, or testing APKs.

Instead of wasting tokens on dozens of back-and-forth MCP tool calls (tap, screenshot, tap, screenshot...), AI agents drive the phone through **one compound CLI tool (`agentdroid`)** that chains setup, file transfers, app installation, multi-step UI execution (until the required output is obtained), and data extraction into a single command.

- **One-Command Install & Auto AI-Agent Setup (`./install.sh`)**: Installs host dependencies & kernel modules, puts `agentdroid` on `PATH`, boots the silent Android container, and automatically mounts the `agentdroid` skill & rules into **Antigravity, Claude Code, Codex, Cursor, and Windsurf**.
- **Silent & Headless by Default (`--headless`)**: Runs in the background with zero GUI windows, muted audio streams, root ADB (`ro.secure=0`), disabled animations (`0.0`), skipped setup wizards, and pre-installed **Artemis Accessibility Helper** (`com.artemis.helper`).
- **Live Visual Watch Mode (`--watch`)**: Pass `--watch` (or run `agentdroid watch`) to open a live `scrcpy` window (or Artemis Web Stream) and real-time step telemetry whenever you want to watch what your AI agent is doing.

---

## Table of Contents
- [One-Command Install & Setup](#one-command-install--setup)
- [How to Prompt Your AI Agent](#how-to-prompt-your-ai-agent)
- [Architecture](#architecture)
- [General-Purpose Compound CLI (`agentdroid`)](#general-purpose-compound-cli-agentdroid)
- [CLI Reference (`agentdroid`)](#cli-reference-agentdroid)
- [Headless vs. Watch Mode](#headless-vs-watch-mode)
- [Silent Device Provisioning](#silent-device-provisioning)
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
2. **Global CLI**: Links `agentdroid` (and `agentsredroid`) into `~/.local/bin` and `/usr/local/bin` so it runs anywhere.
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
