# AgentRedroid (`agentdroid`) — AI Agent Operating Rules

This repository provides a **silent, general-purpose Android computer** (powered by **Redroid** + **Google Artemis**) that AI agents can use for **any task** — searching & installing tools or apps on the fly, browsing the web, opening deep links, pushing/pulling files, reading notifications/OTP codes/clipboard, automating daily workflows across any Android app, or testing APKs — without wasting tokens on multi-turn MCP tool calls.

---

## Core Principle: Single-Call Compound Execution (Zero Token Waste)

Do **not** issue 15 separate tool calls to install an app, grant permissions, push a file, launch an activity, tap coordinates, take screenshots, and pull results one by one.

Instead, combine everything you need into **one `agentdroid` command** that executes the entire pipeline and returns a single compact JSON payload (`--json`):

```bash
# Example: Install an app by name from F-Droid (or URL/path), push a file,
# execute multi-step natural-language instructions until the required output is obtained,
# pull generated files back, and return 1 compact JSON!
agentdroid \
  --headless \
  --install "fdroid:org.mozilla.fennec_fdroid" \
  --push ./input_data.pdf:/sdcard/Download/input_data.pdf \
  --open-url "https://news.ycombinator.com" \
  --step "Read the top 3 stories on Hacker News and copy the first link" \
  --step "Open Settings and check the current storage usage" \
  --expect "JSON with top_stories array and storage_used string" \
  --until-output \
  --get-clipboard \
  --notifications \
  --screenshot ./artifacts/final_screen.png \
  --json
```

---

## Execution Modes: `--headless` vs `--watch`

1. **`--headless` (Default — Silent Background Mode for AI Agents)**:
   - Runs completely in the background with **zero GUI windows** (`scrcpy` and browsers are suppressed), muted device audio, disabled system animations (`0.0`), and auto-dismissed setup/error dialogs.
   - Always pass `--headless --json` when running autonomously so you receive a single structured JSON response.

2. **`--watch` (`-w` — Live Visual Mode for the User)**:
   - Pass `--watch` whenever the user asks to **see** or **watch** what the AI agent is doing on the Android device.
   - Automatically launches a live `scrcpy` window (or `--watch-web` for the Artemis Web Console stream at `http://127.0.0.1:8000`) and streams real-time step-by-step agent actions in the terminal.
   - Standalone live viewer: `agentdroid watch` (opens `scrcpy` + live stream) or `agentdroid watch --headless` (streams background JSONL telemetry).

---

## General-Purpose Capabilities Reference

| Task / Capability | Single-Call Command |
| :--- | :--- |
| **Do any general task on Android** | `agentdroid "Open Chrome, search for latest AI papers, and summarize the top result" --expect "summary" -u --json` |
| **Search F-Droid for tools/apps** | `agentdroid app search "qr scanner" --json` |
| **Install app on the fly (F-Droid, URL, or APK)** | `agentdroid -i "fdroid:termux" --launch -g "Run pkg update" --json` |
| **Push & pull files in a task** | `agentdroid --push ./doc.pdf --goal "Open doc.pdf in PDF viewer and export page 1" --pull /sdcard/Download/page1.png:./artifacts/ --json` |
| **Open web URLs or deep links (`tg://`, `mailto:`, etc.)** | `agentdroid --open-url "https://example.com" -g "Sign up and extract confirmation code" --notifications --json` |
| **Read notifications (2FA/OTP codes, messages)** | `agentdroid device notifications --json` *(or `--notifications` flag on `run`)* |
| **Read / write Android clipboard** | `agentdroid device clipboard "text to copy"` / `agentdroid device clipboard --json` |
| **Inspect screen UI in ~150 tokens (no LLM)** | `agentdroid ui dump --json` |
| **Run while showing live screen to user** | `agentdroid --watch -g "Open YouTube and play a lofi stream"` |
