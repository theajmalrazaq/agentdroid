---
name: agentdroid
description: General-purpose silent Android computer for AI agents (Redroid + Artemis Accessibility Helper + InputDaemon + Rust agentdroid-fast engine). One-shot compound workflows with capture/variable interpolation, conditional self-healing (wait-any, if-visible), zero-screenshot IME-filtered perception, and direct MCP/CLI control without writing wrapper scripts.
---

# AgentDroid (`agentdroid`) Skill

`agentdroid` provides a root-privileged, silent Android device backed by a native Rust accelerator (`agentdroid-fast`) for sub-millisecond XML parsing, ADB SmartSocket transport, and persistent socket input/hierarchy IPC.

---

## HARD OPERATING RULES (NON-NEGOTIABLE)

1. **ONE-SHOT DIRECT EXECUTION — NEVER CREATE SCRIPTS**
   - **FORBIDDEN**: Creating `.py` or `.sh` wrapper scripts (`run_task.py`, `tmp.sh`, `python3 -c "..."`), calling `AndroidEngine`/`AdbDevice` from throwaway code, or ping-ponging `dump -> tap -> dump -> type` across multiple turns.
   - **ONLY EXCEPTION**: Write Python/shell code only if the user explicitly asks to develop or test repository code. For **driving Android**, always execute in **one shot**:
     - **MCP primary:** `mobile_run_workflow(...)` with ordered `do=[...]` steps, `open_url`, `push`, `pull`, `assert_text`.
     - **CLI primary:** One `agentdroid --headless --launch <pkg> -d "..." -d "..." --assert-text "..." --json` call (or `agentdroid ai "<goal>" --launch <pkg> --json` for closed-loop dynamic navigation).
   - **EXECUTION STRATEGY**:
     - **For deterministic or known app flows**: `agy cli` / MCP **One-Shot Compound Execution** (`mobile_run_workflow` or `agentdroid -d ...`) is the fastest path (~1.3 s execution, 0 extra LLM turns).
     - **For unknown, branching, or dynamic UIs**: **TypeSafe JEV** (`agentdroid ai`) provides sub-second closed-loop recalibration per step, but requires an active TypeSafe API key (`TYPESAFE_API_KEY`).
   - **UNKNOWN UI CAP (`<= 2` calls max):** If targets are unknown, run **at most one** `mobile_get_device_state(view_type="hierarchy")` / `agentdroid ui dump --json`, inspect all IDs/labels, then finish the entire remaining task in **one** compound shot.

2. **SINGLE-CALL CROSS-APP FLOW (`capture:` + `{{var}}` + `if-visible:`)**
   - **CROSS-APP WORKFLOWS (Read X from App A → Write X into App B)**: Execute in **ONE compound call** using `-d "capture:<var>=<regex>"` (or `capture-all:`) + `{{var}}` substitution into later `append:` / `type:` / `fill:` steps (`0` mid-task LLM turns).
   - **SELF-HEALING BRANCHES**: Use `-d "wait-any:<expected>|<popup>"` and `-d "if-visible:<needle>-><step>"` so dialogs, onboarding, and redirects resolve inline without extra turns.
   - **DEEP LINKS FIRST**: Prefer `--locked-app <pkg> --open-url "<uri>"` when navigating to known destinations/files.

3. **ZERO REDUNDANT SCREENSHOTS (`screenshots = 0` by default)**
   - **FORBIDDEN**: Calling `screenshot`, `adb screencap`, `agentdroid ui screenshot`, `view_type="screenshot"`, or `--screenshot` to read text, menus, forms, lists, routes, notifications, or verify actions.
   - **MANDATORY**: Read `ui_summary` / `agentdroid ui dump --json` (`~5 ms`, IME keyboard keys filtered automatically; `full_text` preserved on long/editable nodes).
   - **WEBVIEW / DYNAMIC SCREENS**: If `ui dump` shows only status bar items or loading containers (`element_count <= 7`), **NEVER panic-screenshot**. Wait via `-d "wait-any:<expected>|<fallback>"` or `-d "wait-gone:<spinner>"`.
   - **ONLY TWO ALLOWED EXCEPTIONS**: (a) after settling, `ui dump` exposes zero readable/actionable nodes (pure Canvas/OpenGL/game surface), OR (b) the user explicitly asked for an image artifact.

4. **PRECISE TARGETING**
   - `click:` ranks `clickable` / `editable` elements ahead of passive labels/containers.
   - Disambiguate cleanly with `btn:<label>`, `edit:<label>`, `exact:<label>`, `id:<res_id>`, or `#<index>`.

5. **HEADLESS REDROID INVARIANTS**
   - **NO HARDWARE GPS**: Headless Redroid has no GPS receiver (`"Your location"` stalls). Supply explicit origins/addresses when apps require location.
   - **NO DUPLICATE `--watch` WINDOWS**: Check `pgrep -f "scrcpy.*$SERIAL"` first; if `agentdroid watch` is already running, pass `--headless` so the active overlay streams cleanly without spawning duplicate windows.

6. **TEXT ENTRY & KEYBOARD**
   - `-d "append:<text>"` jumps to EOF before appending (safe for notes/documents, UTF-8, and multiline text); `-d "type:<text>"` replaces text.
   - Pass `-d "hide-keyboard"` if a soft keyboard occludes lower UI elements.

---

## Supported `--do` & `mobile_action_burst` Verbs

- `click:<#idx|btn:#N|edit:#N|btn:X|edit:X|exact:X|id:X|text>`
- `fill:<selector>=<text>` / `type:<text>` / `append:<text>`
- `wait-text:<text>[@sec]` / `wait-any:<a|b|c>[@sec]` / `wait-gone:<text>[@sec]` / `wait-stable[@sec]` / `wait-change[@sec]`
- `if-visible:<needle>-><verb:arg>` / `if-missing:<needle>-><verb:arg>`
- `capture:<var>=<regex>` / `capture-all:<var>=<regex>` *(inject via `{{var}}`)*
- `open-url:<uri>` / `launch:<pkg>` / `shell:<cmd>`
- `scroll:down|up|left|right` / `scroll-to:<text>` *(scales dynamically to screen resolution)*
- `key:HOME|BACK|ENTER|TAB|ESCAPE` / `hide-keyboard` / `dismiss`
- `tap:x,y` / `tap_pct:x%,y%` / `sleep:<seconds>`

---

## One-Shot Cross-App Compound Execution Example

```bash
agentdroid --headless \
  --push ./notes.md:/sdcard/Download/notes.md \
  --launch "com.example.reader" \
  -d "wait-any:Summary|Allow|Accept" \
  -d "if-visible:Allow->click:btn:Allow" \
  -d "wait-text:Summary" \
  -d "capture:status=Status:\\s*([^\\n]+)" \
  -d "open-url:file:///sdcard/Download/notes.md" \
  -d "wait-text:notes" \
  -d "click:edit:#1" \
  -d "append:- Status: {{status}}" \
  -d "click:btn:Save" \
  --pull /sdcard/Download/notes.md:./out.md \
  --json
```
