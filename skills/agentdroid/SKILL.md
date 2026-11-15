---
name: agentdroid
description: General-purpose silent Android computer for AI agents (Redroid). Use Android for any task in a single token-efficient CLI call — search & install apps on the fly (F-Droid, URLs, APKs), browse URLs/deep links, push/pull files, read notifications/OTP/clipboard, or drive UI with semantic actions (zero API keys or .env needed!). Supports silent --headless background mode and live --watch visual mode.
---

# AgentDroid (`agentdroid`) Skill

`agentdroid` gives you a full, root-privileged, silent Android device that you can use as a general-purpose environment for **any task**.

> **No Separate API Keys or `.env` Required**:
> **You (Claude Code, Antigravity, Codex, Cursor, etc.) are already the brain!**
> `agentdroid` provides the sensory perception (`--json` gives you the current screen's labelled elements in ~150 tokens) and the hands (`--click`, `--fill`, `--scroll`, `--do`) so you can control Android directly.

---

## 1. Quick Check

```bash
agentdroid doctor --json || agentdroid up --headless --json
```

---

## 2. General-Purpose Single-Call Execution

Chain on-demand app installation (`-i` from F-Droid, HTTP URL, or local APK), file transfers (`--push` / `--pull`), URL opening (`--open-url`), and UI navigation (`--click`, `--fill`, `--scroll`, or sequential `-d`/`--do` steps) in **one command**:

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

## 3. Sequential Multi-Step UI Chains with `-d` / `--do`

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
- `tap:x,y` / `type:<text>` / `sleep:<seconds>`

---

## 4. Search & Install Any Tool/App On Demand

- Search F-Droid:
  ```bash
  agentdroid app search "pdf viewer" --json
  ```
- Install directly by F-Droid query, HTTPS URL, or APK (all runtime permissions & special AppOps are granted automatically):
  ```bash
  agentdroid app install "fdroid:com.termux" --launch --json
  ```

---

## 5. Headless vs. Watch Mode
 
 - **`--headless` (default)**: Silent background execution. Zero GUI windows, muted device audio, and a single compact JSON output with live UI tree.
 - **`--watch` (`-w`)**: Opens a sleek **floating mobile phone simulator overlay window** (`412×892`, `--always-on-top`, styled like macOS iOS Simulator) that stays docked next to the user's terminal/editor instead of taking over the full display, and streams real-time step telemetry.
 - **Standalone live viewer**:
   - `agentdroid watch` — Open floating phone simulator overlay + live step stream.
   - `agentdroid watch --headless` — Stream live agent events & foreground changes as background JSONL without any GUI window.
