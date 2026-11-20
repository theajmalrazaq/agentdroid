# AgentDroid (`agentdroid`) — AI Agent Operating Rules

This repository provides a **silent, general-purpose Android computer** (powered by **Redroid**, **Google Artemis Accessibility Helper**, **InputDaemon**, and native Rust **`agentdroid-fast`**) that AI agents drive **directly in one shot**.

> **Zero Separate LLM Keys · Zero Custom Scripts:**
> **You (Claude Code, Antigravity, Codex, Cursor, Windsurf) are the brain.** Never write `.py`, `.sh`, or `python3 -c` scripts to drive the phone — execute the task directly in **one shot** via `mobile_run_workflow(...)` or `agentdroid --headless ... -d ...`.

---

## HARD OPERATING RULES (NON-NEGOTIABLE)

1. **ONE-SHOT DIRECT EXECUTION — NEVER CREATE SCRIPTS**
   - **FORBIDDEN**: Creating throwaway `.py` / `.sh` scripts (e.g. `solve.py`, `run_flow.sh`), writing inline `python3 -c "..."` importing `AndroidEngine` / `AdbDevice` / `CompoundPipeline`, writing ADB shell loops, or splitting a workflow into 5–15 ping-pong turns (`dump -> click -> dump -> type`).
   - **ONLY EXCEPTION**: Write Python/shell code ONLY if the user explicitly asks you to implement or modify repository source code, tests, or benchmarks. For **performing any Android task**, execute directly via native tools/CLI.
   - **PRIMARY EXECUTION PATH (1 call):**
     - **Via MCP:** Call `mobile_run_workflow(...)` with full `launch` / `open_url` / ordered `do=[...]` steps / `assert_text` in **one call**.
     - **Via CLI:** Run **one** `agentdroid --headless` command chaining `-d` flags (`wait-any:`, `if-visible:`, `fill:`, `capture:`, `{{var}}`, `--assert-text`, `--json`), or `agentdroid ai "<goal>" --launch <pkg> --json` when autonomous visual/dynamic UI exploration is needed.
   - **EXECUTION STRATEGY**:
     - **For deterministic or known app flows**: `agy cli` / MCP **One-Shot Compound Execution** (`mobile_run_workflow` or `agentdroid -d ...`) is the fastest path (~1.3 s execution, 0 extra LLM turns).
     - **For unknown, branching, or dynamic UIs**: **TypeSafe JEV** (`agentdroid ai`) provides sub-second closed-loop recalibration per step, but requires an active TypeSafe API key (`TYPESAFE_API_KEY`).
   - **UNKNOWN UI CAP (`<= 2` calls max):** If screen selectors are completely unknown, do **at most one** `mobile_get_device_state(view_type="hierarchy")` (or `agentdroid ui dump --json`), read every control ID/label, and immediately finish the entire workflow in **one** compound call.

   **Bad (Forbidden):**
   - Writing `/tmp/do_task.py` with `AndroidEngine(adb)` or running 6 separate `agentdroid tap` calls.

   **Good (One Shot):**
   ```bash
   agentdroid --headless --launch net.gsantner.markor \
     -d "if-visible:NEXT->click:NEXT" -d "if-visible:OK->click:OK" \
     -d "wait-text:fab_add_new_item" -d "click:fab_add_new_item" \
     -d "fill:new_file_dialog__name=notes" -d "hide-keyboard" -d "click:OK" \
     -d "fill:document__fragment__edit__highlighting_editor=Done" \
     -d "hide-keyboard" -d "click:action_save" --json
   ```

2. **SINGLE-CALL CROSS-APP DATA FLOW (`capture:` + `{{var}}` + `if-visible:`)**
   - **SINGLE-CALL READ + WRITE**: Use `capture:<var>=<regex>` / `capture-all:<var>=<regex>` + `{{var}}` interpolation to extract values from App A and inject them straight into App B inside **ONE** `agentdroid` CLI or `mobile_run_workflow` call (`0` mid-task LLM round-trips).
   - **CONDITIONAL RECOVERY INLINE**: Use `wait-any:<expected>|<blocker>` and `if-visible:<needle>-><step>` (e.g., `-d "if-visible:Allow->click:Allow"`) so permissions, changelogs, and popups self-heal in the same shot.
   - **PREFER DEEP LINKS & INTENTS**: Jump straight with `--locked-app <pkg> --open-url "<uri>"`.

3. **ZERO REDUNDANT SCREENSHOTS (`screenshots = 0` by default)**
   - **FORBIDDEN**: Calling `screenshot`, `adb screencap`, `agentdroid ui screenshot`, `view_type="screenshot"`, or `--screenshot` to read text, buttons, lists, menus, routes, forms, notifications, or to "verify" completed actions.
   - **MANDATORY**: Read `ui_summary` / `agentdroid ui dump --json` (`~5 ms`, IME keyboard chrome filtered automatically). Editable/long text fields include full text without truncation.
   - **LOADING / WEBVIEW / DYNAMIC SCREENS**: If `ui dump` shows only status bar items or a loading stub (`element_count <= 7`), **DO NOT take a screenshot**. Wait cleanly with `-d "wait-any:<expected>|<fallback>|<blocker>"` or `-d "wait-gone:<spinner>"`.
   - **ONLY TWO EXCEPTIONS**: (a) after `wait-*` settling, `ui dump` still exposes zero readable/actionable nodes (pure Canvas/OpenGL/image surface), OR (b) the user explicitly asked for an image/screenshot file.

4. **TARGETING PRECISION (`btn:`, `edit:`, `exact:`, `id:`, `#id`)**
   - Default selectors rank clickable/editable nodes above static labels/WebView containers.
   - When a screen has both a label and a button with similar text (e.g. `"Search"` title vs button), pass `btn:Search`, `edit:Search`, `exact:Save`, or `#id`.

5. **HEADLESS REDROID ENVIRONMENT INVARIANTS**
   - **NO HARDWARE GPS**: Headless Redroid has no physical GPS receiver; tapping `"Your location"` stalls location requests. Supply explicit origins or resolved IP geolocation whenever driving location-dependent apps.
   - **DO NOT DUPLICATE `--watch` WINDOWS**: Check `pgrep -f "scrcpy.*$SERIAL"` before passing `--watch`. If a persistent `agentdroid watch` window is open, run commands with `--headless` (`headless=True`) — the live window reflects every action immediately.

6. **`append:` VS `type:` & `hide-keyboard`**
   - `-d "type:<text>"` sets/replaces field text; `-d "append:<text>"` jumps to EOF and appends cleanly (works with Unicode, newlines, and long notes).
   - Use `-d "hide-keyboard"` if a soft keyboard covers lower UI targets (`hide-keyboard` safely dismisses IME via global Back only when `mInputShown=true`; IME key nodes are hidden from `ui_summary` by default).

7. **DYNAMIC APP RESOLUTION PROTOCOL (INSTALLED, UNINSTALLED & DEFAULT UTILITIES)**
   - **Zero Shell Package Hunting**: Never run raw ADB bash grep loops (`pm list packages | grep ...`). If you need to see what is installed on an unknown device, call `mobile_diagnose()` (includes `installed_apps` in ~25 ms) or run `agentdroid app list --json`.
   - **Handling Uninstalled Apps Dynamically**:
     - **One-Shot Install via F-Droid**: Pass `install: ["fdroid:<name_or_query>"]` directly in `mobile_run_workflow(...)` or CLI `agentdroid app install fdroid:<name>`. AgentDroid queries the official F-Droid catalog, downloads the verified APK, installs, and auto-grants permissions in one step.
     - **Direct APK or URL**: Pass `install: ["https://example.com/app.apk"]` or local path.
     - **Web App / Deep Link Fallback**: If an app is proprietary or uninstalled without an APK, open its mobile web app or intent directly via `open_url: "https://..."` or `--open-url "https://..."`.
   - **Default Redroid Utilities Reference** (bundled lightweight apps for standard workflows):
     - **Google Maps / Navigation**: `us.spotco.maps` (GMaps WV wrapper). Open directions directly via intent:
       `--launch us.spotco.maps --open-url "https://www.google.com/maps/dir/<Origin>/<Destination>"` (avoids heavy Play Services / proprietary client).
     - **Notes & Markdown**: `net.gsantner.markor` (Markor). Main screen: FAB `#fab_add_new_item` -> file name `#new_file_dialog__name` -> `click:btn:OK` -> editor `#document__fragment__edit__highlighting_editor` -> save `#action_save` -> preview `#action_preview`.
     - **Web Browser**: `de.baumann.browser` (FOSS Browser).
     - **Media Player**: `org.videolan.vlc` (VLC).
     - **Calculator**: `org.fossify.math`.

8. **ONE-SHOT CROSS-APP DATA EXTRACTION (`capture:` -> `{{var}}`)**
   - When asked to "Check X in App A and save it in App B", do **NOT** split into multiple LLM turns. Run **ONE** `mobile_run_workflow` or `agentdroid` call:
   ```python
   # Example: Read Google Maps route time and write directly into a new Markor note
   mobile_run_workflow(
       launch="us.spotco.maps",
       open_url="https://www.google.com/maps/dir/Faisalabad/Lahore",
       do=[
           "wait-any:Driving Mode|2h|Route",
           "capture:duration=(?:Driving Mode\\s*)?(\\d+\\s*(?:h|hr|min)\\s*\\d*\\s*m?)",
           "launch:net.gsantner.markor",
           "click:fab_add_new_item",
           "fill:new_file_dialog__name=trip_summary",
           "click:OK",
           "fill:document__fragment__edit__highlighting_editor=Faisalabad to Lahore: {{duration}}",
           "hide-keyboard",
           "click:action_save",
           "click:action_preview",
           "wait-stable"
       ],
       assert_text="Faisalabad to Lahore"
   )
   ```

---

## Direct Agent Integration via MCP (Claude Code, Codex, Antigravity, Cursor)

Run once to mount AgentDroid's MCP tools:
```bash
agentdroid mcp --install
```

Native MCP tools:
- `mobile_run_workflow(...)`: **PRIMARY ONE-SHOT TOOL**. Run complete Android tasks (`install`, `push`, `open_url`, `locked_app_package`, `launch`, `do` with `capture:`/`{{var}}`/`wait-any:`/`if-visible:`, `wait_text`, `pull`, `assert_text`) in a single call.
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
