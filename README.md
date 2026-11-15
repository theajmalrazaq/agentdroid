# AgentDroid

A silent, headless **Android computer for AI agents**, built on [Redroid](https://github.com/remote-android/redroid-doc) and [Google Artemis](https://github.com/google/artemis).

- **Local:** your coding agent (Claude Code, Antigravity, Codex, Cursor, …) drives it through the `agentdroid` CLI.
- **Cloud / web:** deploy **one central server** (TypeScript) and drive it from any app through the **Vercel AI SDK** tools or plain HTTP.

No LLM keys are needed anywhere. The model in your agent or app is the brain. AgentDroid provides the eyes (a compact ~150-token screen dump) and the hands (click, fill, scroll, install, open URL).

## Architecture

```
 Coding agent ──CLI──► agentdroid (Python) ──┐
                                             ├──► adb ──► Redroid Android (Docker)
 Your web app ──AI SDK tools / HTTP──► server (TypeScript, one process) ─┘
```

| Path | What it is |
| :--- | :--- |
| [`server/`](server/) | **The one central server**: HTTP API, AI SDK tools, typed client, security guardrails. Node ≥ 22.18, zero runtime dependencies. |
| [`agentdroid/`](agentdroid/) | Local CLI for coding agents (compound `run`, `watch`, `up`/`down`, `doctor`, …). |
| [`docker/`](docker/), [`docker-compose.yml`](docker-compose.yml) | Redroid device image and the 2-service stack (`redroid` + `server`). |
| [`scripts/provision-device.sh`](scripts/provision-device.sh) | Silent root ADB, dark theme, gesture nav, animations off. |
| [`skills/`](skills/), [`AGENTS.md`](AGENTS.md) | Skill and rules mounted into coding agents by `install.sh`. |

## Quick start (local, with your coding agent)

```bash
git clone https://github.com/theajmalrazaq/agentdroid.git && cd agentdroid
./install.sh          # host tools, kernel modules, `agentdroid` on PATH, agent skills, device up
```

Then just ask your agent: *"Use agentdroid to open Hacker News and summarize the top 5 stories."*

```bash
agentdroid --headless --open-url "https://news.ycombinator.com" \
  --do "scroll:down" --assert-text "Hacker News" --json
agentdroid --watch --launch com.android.settings    # floating iOS-Simulator-style phone window
```

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

Built on [Redroid](https://github.com/remote-android/redroid-doc) (Remote-Android team) for the Android-in-container runtime, and [Google Artemis](https://github.com/google/artemis) for the accessibility helper APK and agent design. Both are Apache-2.0; Redroid kernel modules are GPL-2.0. AgentDroid is Apache-2.0.
