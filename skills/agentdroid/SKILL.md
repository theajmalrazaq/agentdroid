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
- `mobile_get_device_state(view_type="hierarchy"|"screenshot")`: Returns numbered indexed elements `[#1] Button "Settings" | Center: (540, 960)` in ~150 tokens.
- `mobile_perform_action(action="click"|"tap"|"fill"|"type"|"key"|"scroll"|"swipe", target="...")`: Artemis dynamic-first targeting (`#1`, text, or coordinates).
- `mobile_action_burst(actions=[...])`: High-speed sequence of rapid actions without LLM latency between steps.
- `mobile_auto_dismiss_dialogs()`: Auto-detects and clears runtime permission prompts or crash/ANR alerts.
- `mobile_launch_app`, `mobile_install_app`, `mobile_open_url`, `mobile_read_notifications`, `mobile_clipboard`, `mobile_diagnose`.

---

## 2. Artemis Mobile Driving Mindset (Best Practices)

1. **Observe Before Acting**:
   Always call `mobile_get_device_state` (or `agentdroid ui dump`) to view the current screen before issuing clicks.
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

## 3. General-Purpose Single-Call CLI Execution

For terminal execution, chain installation, file transfers, URL opening, and UI navigation in **one command**:

```bash
agentdroid \
  --headless \
  -i "fdroid:net.gsantner.markor" \
  --push ./notes.md:/sdcard/Download/notes.md \
  --launch \
  --click "Open from storage" \
  --click "notes.md" \
  --fill "content_editor=Updated by AI Agent\n" \
  --click "Save" \
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
