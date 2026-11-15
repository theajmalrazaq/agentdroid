# AgentDroid (`agentdroid`) — AI Agent Operating Rules

This repository provides a **silent, general-purpose Android computer** (powered by **Redroid**; the on-device accessibility helper comes from **Google Artemis**) that AI agents can drive for **any task**.

> **No Separate LLM API Keys or `.env` Required**:
> **You (the host AI agent — Claude Code, Antigravity, Codex, Cursor, etc.) are already the brain!**
> Artemis's proven mobile driving engine (numbered indexed perception, action bursts, dynamic-first coordinate fallback, and dialog auto-dismissal) is embedded directly into `agentdroid` via **Model Context Protocol (MCP)** and compound CLI commands.

---

## Direct Agent Integration via MCP (Claude Code, Codex, Antigravity, Cursor)

Run once to mount AgentDroid's MCP tools into all your AI coding assistants:
```bash
agentdroid mcp --install
```

Your AI assistant can then directly call:
- `mobile_run_workflow(...)`: **RECOMMENDED PRIMARY TOOL**. Run complete Android tasks (install, push, open, do, click, fill, screenshot, clipboard, pull) in ONE tool call.
- `mobile_get_device_state(view_type="hierarchy"|"screenshot")`: Read compact numbered UI elements (`[#1] Button 'Sign In' | Center: (540, 960)`).
- `mobile_action_burst(actions=["click:#1", "type:user", "key:ENTER"])`: High-speed chained gestures without round-trip LLM latency.
- `mobile_perform_action(action="click", target="#1")`: Dynamic-first element click or coordinate tap.
- `mobile_auto_dismiss_dialogs()`: Detect and auto-clear Android permission popups, intro wizards, or ANR/crash alerts.
- `mobile_launch_app`, `mobile_install_app`, `mobile_open_url`, `mobile_read_notifications`, `mobile_clipboard`.

---

## Artemis Driving Mindset: The "Compound-First, Numbered-Index" Rule

When driving Android:
1. **Compound Single-Call First**: Execute multi-step tasks in ONE call (`mobile_run_workflow` or compound CLI). Never make 10-15 turn-by-turn tool calls.
2. **Prefer numbered index (`#id`)**: Targeting by index `#3` is faster and more reliable than fuzzy text matching.
3. **Coordinate Fallback**: If an element is within a Canvas or Flutter surface where the accessibility node is non-interactive, tap its center coordinates `(x, y)` directly.
4. **Action Bursts**: Execute multi-step sequences together so menus and popups don't close between LLM turns.

---

## How to Translate Natural User Requests into AgentDroid Commands

When the user tells you what to do in plain English, **YOU are the brain** that compiles their intent into a single compound execution:

| User's Natural Request | How You (the AI) Compile It |
| :--- | :--- |
| **"Create a file, edit it in Markor, and save it"** | `agentdroid --push ./file.md:/sdcard/Download/file.md -i "fdroid:net.gsantner.markor" --open-url "file:///sdcard/Download/file.md" -d "click:Edit" -d "type:\n- [x] Done\n" -d "click:Save" --pull /sdcard/Download/file.md:./artifacts/out.md --json` |
| **"Open website X and search / read"** | `agentdroid --open-url "https://example.com" -d "click:Search" -d "type:query" -d "key:ENTER" --json` |
| **"Check Android version / Wi-Fi in Settings"** | `agentdroid --launch "com.android.settings" -d "scroll-to:About" -d "click:About" --json` |
| **"Show me what you are doing" / "Let me see"** | Add `--watch` to the command so the live floating phone overlay window pops up for the user. |
| **"Install app X from F-Droid"** | `agentdroid -i "fdroid:<package>" --launch --json` |
| **"Check verification code / 2FA / notification"** | `agentdroid device notifications --json` (or add `--notifications` to any command) |

### The "Maximum 2-Turn Rule" for Unknown Screens
If you are dealing with a new, unfamiliar screen where you cannot guess the button names in advance:
1. **Turn 1 (Launch & Inspect)**: Run `agentdroid --launch <pkg> --json` (or `mobile_run_workflow`). Auto-dismiss clears onboarding wizards, and `ui_summary` immediately returns all numbered elements (`[#1]`, `[#2]`).
2. **Turn 2 (Execute Entire Action Burst)**: Do **NOT** tap one button per turn! Now that you see the screen, execute all remaining steps together in ONE compound action burst:
   `-d "click:#2" -d "type:query" -d "key:ENTER" -d "click:#5" --pull ... --json`
3. **NEVER ping-pong**: Never do `dump -> tap -> dump -> tap` over 10 separate turns.

---

## Core Principle: Single-Call Compound Execution (Zero Token Waste)

Do **not** issue 15 separate tool calls to install an app, grant permissions, push a file, launch an activity, tap coordinates, take screenshots, and pull results one by one.

Instead, combine everything into **one `agentdroid` command**:

### 1. General Task: Install, Push, Launch, Navigate & Pull Back Result

```bash
# Example: Install Markor from F-Droid (or URL/APK), push a file, open it, edit, and pull back!
agentdroid \
  --headless \
  --install "fdroid:net.gsantner.markor" \
  --push ./draft.md:/sdcard/Download/draft.md \
  --open-url "file:///sdcard/Download/draft.md" \
  -d "click:Edit" \
  -d "type:\nCompleted by AI Agent\n" \
  -d "click:Save" \
  --pull /sdcard/Download/draft.md:./artifacts/draft_edited.md \
  --notifications \
  --json
```

### 2. Multi-Step Sequential UI Workflow with `--do`

Use `-d` / `--do` to chain multiple semantic actions in one execution:
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

Supported `--do` verbs:
- `click:<text_or_id_or_#index>` (e.g. `click:Login`, `click:#3`)
- `fill:<selector>=<text>` (e.g. `fill:Email=user@test.com`)
- `scroll:down` / `scroll:up` / `scroll-to:<text>`
- `key:HOME` / `key:BACK` / `key:ENTER`
- `tap:x,y` / `type:<text>` / `sleep:<seconds>`

---

## Execution Modes: `--headless` vs `--watch`

1. **`--headless` (Default — Silent Background Mode for AI Agents)**:
   - Runs completely in the background with **zero GUI windows** (`scrcpy` and browsers are suppressed), muted device audio, disabled system animations (`0.0`), and auto-dismissed setup/error dialogs.
   - Always pass `--headless --json` when running autonomously so you receive a single structured JSON response with the live UI tree.

2. **`--watch` (`-w` — Live Visual Mode for the User)**:
   - Pass `--watch` whenever the user asks to **see** or **watch** what you are doing on the Android device.
   - Automatically launches a **sleek floating mobile phone overlay window** (`412×892`, `--always-on-top`, like macOS iOS Simulator) that stays docked next to the user's terminal/editor instead of taking over the full display.
   - Streams real-time step-by-step actions and telemetry in the terminal.
   - Standalone live viewer: `agentdroid watch` (opens floating phone simulator overlay + live stream) or `agentdroid watch --headless` (streams background JSONL telemetry).

---

## General-Purpose Capabilities Reference

| Task / Capability | Single-Call Command |
| :--- | :--- |
| **Inspect screen UI in ~150 tokens** | `agentdroid ui dump --json` *(or `--json` on `run`)* |
| **Search F-Droid for tools/apps** | `agentdroid app search "markdown editor" --json` |
| **Install app on the fly (F-Droid, URL, APK)** | `agentdroid -i "fdroid:termux" --launch --json` |
| **Push & pull files** | `agentdroid --push ./file.txt --click "Open" --pull /sdcard/Download/out.txt:./artifacts/ --json` |
| **Open web URLs or deep links (`tg://`, `mailto:`)** | `agentdroid --open-url "https://example.com" --notifications --json` |
| **Read notifications (2FA/OTP codes, messages)** | `agentdroid device notifications --json` *(or `--notifications` flag on `run`)* |
| **Read / write Android clipboard** | `agentdroid device clipboard "text to copy"` / `agentdroid device clipboard --json` |
| **Run while showing live screen to user** | `agentdroid --watch --launch "com.android.settings" -d "click:Display"` |
