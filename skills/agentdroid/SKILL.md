---
name: agentdroid
description: General-purpose silent Android computer for AI agents (Redroid + Google Artemis). Use Android for any task in a single token-efficient CLI call — search & install apps on the fly (F-Droid, URLs, APKs), browse URLs/deep links, push/pull files, read notifications/OTP/clipboard, or automate any workflow with --headless background mode and --watch live visual mode.
---

# AgentRedroid (`agentdroid`) Skill

`agentdroid` gives you a full, root-privileged, silent Android device that you can use as a general-purpose environment for **any task** — not just app testing.

Always prefer chaining everything you need into a **single compound `agentdroid` command** rather than making multiple back-and-forth tool calls.

## 1. Ensure Device is Ready

```bash
agentdroid doctor --json || agentdroid up --headless --json
```

## 2. General-Purpose Single-Call Execution

You can combine on-demand app installation (`-i` from F-Droid, HTTP URL, or local APK), file transfers (`--push` / `--pull`), URL/deep-link opening (`--open-url`), clipboard (`--set-clipboard` / `--get-clipboard`), notifications (`--notifications`), and multi-step Artemis goals (`--step` / `-g`) with autonomous retry-until-output (`--until-output`) in one command:

```bash
agentdroid \
  --headless \
  -i "fdroid:markor" \
  --push ./notes.md:/sdcard/Download/notes.md \
  --launch \
  --step "Open notes.md from Downloads, append today's summary, and save" \
  --expect "JSON with saved_file_path and word_count" \
  --until-output \
  --pull /sdcard/Download/notes.md:./artifacts/notes_updated.md \
  --notifications \
  --screenshot ./artifacts/result.png \
  --json
```

## 3. Search & Install Any Tool/App On Demand

- Search F-Droid for an app/tool when you need one:
  ```bash
  agentdroid app search "pdf viewer" --json
  ```
- Install directly by F-Droid query/package ID, HTTPS URL, or local APK (all runtime permissions & special AppOps are granted automatically):
  ```bash
  agentdroid app install "fdroid:com.termux" --launch --json
  ```

## 4. Headless vs. Watch Mode

- **`--headless` (default)**: Silent background execution. Zero GUI windows, muted device audio, and a single compact JSON output.
- **`--watch` (`-w`)**: Opens a live `scrcpy` window (or `--watch-web` browser stream) and streams real-time step telemetry so the user can watch what you are doing on the Android device.
- **Standalone live viewer**:
  - `agentdroid watch` — Open `scrcpy` + live step stream.
  - `agentdroid watch --headless` — Stream live agent events & foreground changes as background JSONL without any GUI window.
