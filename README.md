# AgentDroid

A silent, headless **Android computer for AI agents**, built on [Redroid](https://github.com/remote-android/redroid-doc), powered by the **Google Artemis mobile driving engine**.

- **Local AI Agents (Claude Code, Antigravity, Codex, Cursor):** Drive Android directly via **native Model Context Protocol (MCP)** or compound CLI calls.
- **Cloud / Web:** Deploy **one central server** (TypeScript) and drive it from web apps through the **Vercel AI SDK** tools or plain HTTP.

**No secondary LLM keys, no `.env`, no external agent daemon.** Claude Code, Codex, Antigravity and Cursor use the Android device directly. AgentDroid embeds Artemis's driving engine (numbered indexed perception `[#1]`, action bursts, dynamic-first coordinate fallback, and system dialog auto-dismissal) so your coding agent has total control over Android.

## Architecture

```
 Claude / Codex / Antigravity ──MCP (stdio) / CLI──► agentdroid (Python) ──┐
                                                                           ├──► adb ──► Redroid Android
 Your web app ─────────────AI SDK tools / HTTP──────────► server (Node) ───┘
```

| Path | What it is |
| :--- | :--- |
| [`agentdroid/`](agentdroid/) | Local automation engine, Artemis driving core, and native Model Context Protocol (MCP) server. |
| [`server/`](server/) | **The one central cloud server**: HTTP API, AI SDK tools, typed client, security guardrails. Node ≥ 22.18, zero runtime dependencies. |
| [`docker/`](docker/), [`docker-compose.yml`](docker-compose.yml) | Redroid device image and the 2-service stack (`redroid` + `server`). |
| [`scripts/provision-device.sh`](scripts/provision-device.sh) | Silent root ADB, dark theme, gesture nav, animations off. |
| [`skills/`](skills/), [`AGENTS.md`](AGENTS.md) | Skill and rules mounted into coding assistants by `install.sh`. |

## Quick start (local, with your AI coding agent)

```bash
git clone https://github.com/theajmalrazaq/agentdroid.git && cd agentdroid
./install.sh          # host tools, kernel modules, `agentdroid` on PATH, agent skills, device up
```

### 1. Drive via Model Context Protocol (MCP) in Claude Code / Codex / Antigravity / Cursor
```bash
agentdroid mcp --install   # automatically configures Claude, Codex, Antigravity, and Cursor
```
Your agent gets native mobile tools (`mobile_get_device_state`, `mobile_perform_action`, `mobile_action_burst`, `mobile_auto_dismiss_dialogs`, etc.).

### 2. Drive via Terminal CLI
Ask your agent: *"Use agentdroid to open Hacker News and summarize the top 5 stories."*

```bash
# Silent background mode (inspects screen in ~150 tokens, chains clicks/fills):
agentdroid --headless --open-url "https://news.ycombinator.com" \
  --do "scroll:down" --assert-text "Hacker News" --json

# Floating iOS-Simulator-style phone window to watch in real time:
agentdroid --watch --launch com.android.settings

## Deploy to the cloud (one server)

```bash
cp .env.example .env
# set a strong key:  AGENTDROID_API_KEY=$(openssl rand -hex 24)
docker compose up -d        # redroid + server on :8080
```

The server **refuses to start** on a non-loopback address without a strong `AGENTDROID_API_KEY`. Put it behind HTTPS (Caddy, nginx, or a cloud load balancer).

Run it without Docker next to an existing ADB device:

```bash
cd server && npm install && AGENTDROID_API_KEY=... npm start
```

## Use it from an AI SDK app

```ts
import { generateText, stepCountIs } from "ai";
import { openai } from "@ai-sdk/openai";
import { createAgentDroidTools } from "@agentdroid/server/tools";

const { text } = await generateText({
  model: openai("gpt-4o"),
  tools: createAgentDroidTools({ endpoint: process.env.AGENTDROID_URL!, apiKey: process.env.AGENTDROID_API_KEY }),
  stopWhen: stepCountIs(10),
  prompt: "Open Hacker News on Android, scroll down, and tell me the top story.",
});
```

Tools: `runAndroidWorkflow`, `inspectScreenUI`, `performSemanticAction`, `readNotifications`, `screenshot`. Requires `ai` ≥ 5 and `zod`. The server itself holds no model credentials.

## HTTP API

All routes except `/health` need `X-API-Key: <key>` or `Authorization: Bearer <key>`. Keys in query strings are rejected.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/health` | Server and device status |
| `POST` | `/api/v1/run` | Compound call: `install[]`, `open_url`, `launch`, `do[]`, `assert_text[]`, `notifications` |
| `POST` | `/api/v1/do` | `{ "steps": ["click:Login", "fill:Email=a@b.c", "scroll-to:About", "key:BACK"] }` |
| `GET` | `/api/v1/ui/dump?max=80` | Compact element list and foreground package |
| `POST` | `/api/v1/ui/tap` · `/ui/type` · `/ui/key` | Direct input |
| `GET` | `/api/v1/ui/screenshot[?format=base64]` | PNG screenshot |
| `GET` | `/api/v1/device/notifications` | Notifications (OTP, messages) |
| `POST` | `/api/v1/device/open-url` | Open URL or deep link |
| `GET` | `/api/v1/apps` | Installed third-party apps |
| `POST` | `/api/v1/app/install` | `{ "source": "fdroid:<pkg>" \| "https://…apk" \| "<file in data dir>" }` |

Step verbs: `click`, `fill`, `scroll`, `scroll-to`, `key`, `tap`, `type`, `sleep`. Arbitrary shell steps do not exist in the server.

## Security (server)

- **Auth required off-loopback**; weak keys rejected; constant-time comparison; no query-string keys.
- **SSRF:** URLs are DNS-resolved and rejected if they point to private, loopback, link-local or cloud-metadata addresses. Downloads re-check every redirect hop. Only `http(s)`, `market`, `geo`, `tel` and `mailto` are allowed. `AGENTDROID_ALLOW_PRIVATE_NETWORKS=true` opts out.
- **No shell:** there is no shell execution endpoint or step. This is the real protection, not a blocklist.
- **Filesystem allowlist:** host files used for installs are confined to `AGENTDROID_DATA_DIR` (`./data`).
- **Abuse limits:** per-client rate limit (`AGENTDROID_RATE_LIMIT_RPM`, default 120), 1 MB body limit, and one device operation at a time (the phone is serialized).
- **CORS** is off unless `AGENTDROID_CORS_ORIGIN` is set. `X-Forwarded-For` is trusted only with `AGENTDROID_TRUST_PROXY=true`.
- Keep the Redroid ADB port on loopback (the compose file does). The device is rooted and must never be exposed.
- For stronger isolation, add an egress firewall for the device container; Android makes its own network requests.

## Why Redroid instead of the Android Studio emulator?

Redroid runs Android as a container on the host kernel (no QEMU VM), so it typically needs far less RAM and boots in seconds. Figures vary by host; measure on yours.

## Troubleshooting

`agentdroid doctor` checks adb, binder, device and helper status. Logs: `docker compose logs redroid server`.

## Credits

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, and [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK (only the APK; none of its LLM agent is used). Both are Apache-2.0; Redroid kernel modules are GPL-2.0. AgentDroid is Apache-2.0.
