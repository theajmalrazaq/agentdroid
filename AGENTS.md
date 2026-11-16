# AgentDroid (`agentdroid`) — AI Agent Operating Rules

This repository provides a **silent, general-purpose Android computer** (powered by **Redroid**, **Google Artemis Accessibility Helper**, **InputDaemon**, and native Rust **`agentdroid-fast`**) that AI agents can drive for **any task**.

> **No Separate LLM API Keys or `.env` Required**:
> **You (the host AI agent — Claude Code, Antigravity, Codex, Cursor, etc.) are already the brain!**

---

## HARD OPERATING RULES (NON-NEGOTIABLE)

1. **ZERO REDUNDANT SCREENSHOTS (`screenshots = 0` by default)**
   - **FORBIDDEN**: Calling `screenshot`, `adb screencap`, `agentdroid ui screenshot`, `view_type="screenshot"`, or `--screenshot` to read text, buttons, lists, menus, routes, forms, notifications, or to "verify" completed actions.
   - **MANDATORY**: Read `ui_summary` / `agentdroid ui dump --json` (`~5 ms`, IME keyboard chrome filtered automatically). Editable/long text fields include full text without truncation.
   - **LOADING / WEBVIEW / DYNAMIC SCREENS**: If `ui dump` shows only status bar items or a loading stub (`element_count <= 7`), **DO NOT take a screenshot**. Poll cleanly with `-d "wait-any:<expected>|<fallback>|<blocker>"` or `-d "wait-gone:<spinner>"`.
   - **ONLY TWO EXCEPTIONS**: (a) after `wait-*` settling, `ui dump` still exposes zero readable/actionable nodes (pure Canvas/OpenGL/image surface), OR (b) the user explicitly asked for an image/screenshot file.

2. **TRUE SINGLE-CALL FIRST (`<= 1` call when extracting & writing across apps; `<= 2` calls max on unknown UIs)**
   - **FORBIDDEN**: Ping-ponging `dump -> tap -> dump -> type` across 5–10 LLM turns or shelling out multiple `agentdroid ui ...` calls when one compound pipeline handles all steps.
   - **SINGLE-CALL CROSS-APP READ + WRITE**: Use `capture:<var>=<regex>` / `capture-all:<var>=<regex>` + `{{var}}` interpolation to read values from App A and pass them straight into App B in **ONE `agentdroid` CLI or `mobile_run_workflow` call** (zero mid-task LLM round-trips!).
   - **CONDITIONAL RECOVERY INSIDE A CALL**: Use `wait-any:<expected>|<blocker>` and `if-visible:<needle>-><step>` (e.g., `-d "if-visible:Allow->click:Allow"`) to handle popups, onboarding, or transient redirects without burning another LLM turn.
   - **PREFER DEEP LINKS & INTENTS**: Jump straight with `--locked-app <pkg> --open-url "<uri>"`.

3. **TARGETING PRECISION (`btn:`, `edit:`, `exact:`, `id:`, `#id`)**
   - Default selectors rank clickable/editable nodes above static labels/WebView containers.
   - When a screen has both a label and a button with similar text (e.g. `"Search"` title vs button), pass `btn:Search`, `edit:Search`, `exact:Save`, or `#id`.

4. **HEADLESS REDROID ENVIRONMENT INVARIANTS**
   - **NO HARDWARE GPS**: Headless Redroid has no physical GPS receiver; tapping `"Your location"` stalls location requests. Supply explicit origins or resolved IP geolocation whenever driving location-dependent apps.
   - **DO NOT DUPLICATE `--watch` WINDOWS**: Check `pgrep -f "scrcpy.*$SERIAL"` before passing `--watch`. If a persistent `agentdroid watch` window is open, run commands with `--headless` (`headless=True`) — the live window reflects every action immediately.

5. **`append:` VS `type:` & `hide-keyboard`**
   - `-d "type:<text>"` sets/replaces field text; `-d "append:<text>"` jumps to EOF and appends cleanly (works with Unicode, newlines, and long notes).
   - Use `-d "hide-keyboard"` if a soft keyboard ever covers lower UI targets (IME key nodes are already hidden from `ui_summary` by default; pass `--include-ime` only if inspecting a keyboard itself).

---

## Direct Agent Integration via MCP (Claude Code, Codex, Antigravity, Cursor)

Run once to mount AgentDroid's MCP tools:
```bash
agentdroid mcp --install
```

Native MCP tools:
- `mobile_run_workflow(...)`: **PRIMARY TOOL**. Run complete single-call Android tasks (`install`, `push`, `open_url`, `locked_app_package`, `launch`, `do` with `capture:`/`{{var}}`/`wait-any:`/`if-visible:`, `wait_text`, `pull`, `assert_text`).
- `mobile_get_device_state(view_type="hierarchy")`: Compact IME-free UI elements (`display_size`, `elements`, `full_text`). Never pass `"screenshot"` unless hierarchy is genuinely empty.
- `mobile_action_burst(actions=[...])`: Execute ordered steps without LLM round-trip latency.
- `mobile_perform_action(action="click", target="btn:Submit")`
- `mobile_auto_dismiss_dialogs()`, `mobile_launch_app`, `mobile_install_app`, `mobile_open_url`, `mobile_read_notifications`, `mobile_clipboard`.

---

## Supported `--do` / `mobile_action_burst` Verbs

- `if-visible:<needle>-><verb:arg>` / `if-missing:<needle>-><verb:arg>` (conditional recovery without round-trip)
- `click:<selector>` (`#3`, `btn:#1`, `edit:#1`, `btn:Save`, `edit:Notes`, `exact:OK`, `id:action_save`, or text/substring)
- `fill:<selector>=<text>`
- `type:<text>` / `append:<text>` (supports `{{var}}`)
- `wait-text:<text>` / `wait-any:<a|b|c>` / `wait-gone:<text>` / `wait-stable`
- `capture:<var>=<regex>` / `capture-all:<var>=<regex>` (extract text into `{{var}}`)
- `open-url:<uri>` / `launch:<pkg>` / `shell:<cmd>`
- `scroll:down|up|left|right` / `scroll-to:<text>` (scaled dynamically to device resolution)
- `key:HOME|BACK|ENTER|TAB|ESCAPE` / `hide-keyboard` / `dismiss`
- `tap:x,y` / `tap_pct:x%,y%` / `sleep:<seconds>`
