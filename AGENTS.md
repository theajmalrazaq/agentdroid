# AgentDroid (`agentdroid`) — AI Agent Operating Rules

This repository provides a **silent, general-purpose Android computer** (powered by **Redroid** + **Google Artemis**) that AI agents can drive for **any task**.

> **No Separate LLM API Keys or `.env` Required**:
> **You (the host AI agent — Claude Code, Antigravity, Codex, Cursor, etc.) are already the brain!**
> You don't need a secondary API key to run tasks. `agentdroid` lets you perceive the screen (in ~150 tokens) and chain compound actions directly in single CLI calls.

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
  --launch \
  --click "Open from storage" \
  --click "draft.md" \
  --click "Edit" \
  --type "Completed by AI Agent" \
  --click "Save" \
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
| **Cloud server (HTTP + AI SDK tools)** | `cd server && npm start` / `docker compose up -d` |

---

## Cloud Deployment & Vercel AI SDK Integration

There is ONE central server: [`server/`](server/) (TypeScript). Deploy with `docker compose up -d` (needs a strong `AGENTDROID_API_KEY`). Web apps use the Vercel AI SDK tools; no LLM keys live on the server:

```typescript
import { generateText, stepCountIs } from "ai";
import { openai } from "@ai-sdk/openai";
import { createAgentDroidTools } from "@agentdroid/server/tools";

const { text } = await generateText({
  model: openai("gpt-4o"),
  tools: createAgentDroidTools({ endpoint: "https://your-host", apiKey: process.env.AGENTDROID_API_KEY }),
  stopWhen: stepCountIs(10),
  prompt: "Open Hacker News on Android and summarize the top stories",
});
```

## Server Security Guardrails

- Refuses to start off-loopback without a strong API key; keys only via `X-API-Key` / Bearer.
- SSRF: DNS-resolved URL checks block private, loopback, link-local and metadata addresses, including across redirects.
- No shell execution exists in the server. Host files are confined to `AGENTDROID_DATA_DIR`.
- Rate limit, 1 MB body limit, and one device operation at a time.
- The local `agentdroid` CLI is unrestricted; the server is not.
