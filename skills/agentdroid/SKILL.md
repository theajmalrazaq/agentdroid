---
name: agentdroid
description: General-purpose silent Android computer for AI agents (Redroid + Artemis Driving Engine). Use Android for any task natively via Model Context Protocol (MCP) or single token-efficient CLI calls — search & install apps on the fly (F-Droid, URLs, APKs), browse URLs/deep links, push/pull files, read notifications/OTP/clipboard, or drive UI with Artemis-grade indexed perception & action bursts (zero API keys or .env needed!). Supports silent --headless background mode and live --watch visual mode.
---

# AgentDroid (`agentdroid`) Skill — Artemis Driving Engine

`agentdroid` gives you a full, root-privileged, silent Android device that you can drive directly using Artemis's proven mobile automation engine.

> **No Separate LLM API Keys or `.env` Required**:
> **You (Claude Code, Antigravity, Codex, Cursor, etc.) are already the brain!**
> Artemis's driving engine (numbered indexed perception, action bursts, dynamic-first coordinate fallback, and dialog auto-dismissal) is embedded natively into `agentdroid` — both via **Model Context Protocol (MCP)** and compound CLI commands.

---

## 1. Connect via Model Context Protocol (MCP)

Run once to mount AgentDroid's MCP tools into Claude Code, Codex, Antigravity, and Cursor:

```bash
agentdroid mcp --install
```

Once connected, your agent receives these native tools:
- `mobile_run_workflow(install=[...], push=[...], open_url="...", launch="...", do=[...], pull=[...], screenshot="...", set_clipboard="...")`: **RECOMMENDED PRIMARY TOOL**. Runs a complete multi-step Android task in ONE call with zero token waste and zero round-trip latency.
- `mobile_get_device_state(view_type="hierarchy"|"screenshot")`: Read compact numbered UI elements (`[#1] Button "Settings" | Center: (540, 960)`).
- `mobile_action_burst(actions=[...])`: High-speed sequence of rapid actions without LLM latency between steps.
- `mobile_perform_action(action="click"|"tap"|"fill"|"type"|"key"|"scroll"|"swipe", target="...")`: Artemis dynamic-first targeting (`#1`, text, or coordinates).
- `mobile_auto_dismiss_dialogs()`: Auto-detects and clears runtime permission prompts, intro wizards, or crash alerts.
- `mobile_launch_app`, `mobile_install_app`, `mobile_open_url`, `mobile_read_notifications`, `mobile_clipboard`, `mobile_diagnose`.

---

## 2. Artemis Mobile Driving Mindset (Best Practices)

1. **Compound Single-Call First (Primary Rule)**:
   Always prefer executing the entire workflow in ONE call (`mobile_run_workflow` or `agentdroid` CLI with chained actions). Do **not** issue 10-15 separate tool calls or step-by-step dumps and screenshots for standard tasks.
2. **Target by Numbered Index (`#id`)**:
   Elements are tagged with `#1`, `#2`, `#3`... Clicking by index (`click:#3`) is dramatically faster and more reliable than fuzzy text matching.
3. **The "Dynamic-First, Coordinate-Fallback" Rule**:
   - Try the element index `#id` or semantic selector first.
   - If an element is in custom Canvas, Flutter, or Compose where accessibility trees don't register clicks, fall back to absolute coordinate taps `(x, y)` from the element's `Center: (x, y)`.
4. **Beat UI Latency with Action Bursts**:
   When opening dropdowns, filling forms, or searching, execute actions together in an action burst (`['click:#2', 'sleep:0.2', 'type:query', 'key:ENTER']`) so transient menus don't auto-close.
5. **Auto-Dismiss Dialogs on Blockers**:
   If an action doesn't progress, call `mobile_auto_dismiss_dialogs()` or check for Android permission popups ("While using the app", "Allow", "Close app").

---

## 3. Natural Language Translation Guide (Compiling User Intent)

The user gives you goals in plain conversational English. **You are the brain** that translates their intent into a compound execution:

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

## 4. General-Purpose Single-Call CLI Execution

For terminal execution, chain installation, file transfers, URL opening, and UI navigation in **one command**:

```bash
agentdroid \
  --headless \
  -i "fdroid:net.gsantner.markor" \
  --push ./notes.md:/sdcard/Download/notes.md \
  --open-url "file:///sdcard/Download/notes.md" \
  -d "click:Edit" \
  -d "type:\nUpdated by AI Agent\n" \
  -d "click:Save" \
  --pull /sdcard/Download/notes.md:./artifacts/notes_updated.md \
  --notifications \
  --json
```

---

## 4. Sequential Multi-Step UI Chains with `-d` / `--do`

Chain multiple semantic actions in strict order:
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
- `tap:x,y` / `tap_pct:x%,y%` / `type:<text>` / `sleep:<seconds>` / `dismiss`

---

## 5. Headless vs. Watch Mode

- **`--headless` (default)**: Silent background execution. Zero GUI windows, muted device audio, and a single compact JSON output with live UI tree.
- **`--watch` (`-w`)**: Opens a sleek **floating mobile phone simulator overlay window** (`412×892`, `--always-on-top`, styled like macOS iOS Simulator) that stays docked next to the user's terminal/editor instead of taking over the full display.
