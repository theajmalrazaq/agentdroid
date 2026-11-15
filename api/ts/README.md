# AgentDroid TypeScript & Vercel AI SDK Integration (`@agentdroid/sdk`)

Drive your self-hosted **AgentDroid** cloud Android computer directly from **Next.js**, **React**, or any **Node.js** web application using the **Vercel AI SDK** (`ai`).

> **Zero Secondary LLM Keys or `.env` Required on AgentDroid**:
> Your web application's AI model (GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro) **is already the brain**!
> You don't need to configure LLM API keys inside AgentDroid. Just point your Vercel AI SDK tools to your AgentDroid cloud URL.

---

## Quickstart

### 1. Installation

```bash
npm install ai zod
```

### 2. Autonomous Android Agent in Next.js / Node.js

```typescript
import { generateText, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { createAgentDroidTools } from "@agentdroid/sdk";

// 1. Point to your self-hosted AgentDroid instance
const agentdroid = createAgentDroidTools({
  endpoint: process.env.AGENTDROID_URL || "http://your-server-ip:8080",
  apiKey: process.env.AGENTDROID_API_KEY, // optional
});

// 2. Drive Android autonomously using your LLM!
const { text } = await generateText({
  model: openai("gpt-4o"),
  prompt: "Open Hacker News on Android, scroll down, click Past, and tell me the top story.",
  tools: {
    runAndroidWorkflow: tool(agentdroid.runAndroidWorkflow),
    inspectScreenUI: tool(agentdroid.inspectScreenUI),
    performSemanticAction: tool(agentdroid.performSemanticAction),
    readNotifications: tool(agentdroid.readNotifications),
  },
  maxSteps: 5,
});

console.log(text);
```

---

## Available Vercel AI SDK Tools

| Tool | Description |
| :--- | :--- |
| `runAndroidWorkflow` | Compound single-call Android task execution (open URLs, install apps, semantic actions, assertions) |
| `inspectScreenUI` | Inspect the visible screen elements in ~150 tokens (~30ms) |
| `performSemanticAction` | Step-by-step UI actions (`click:<text>`, `fill:<sel>=<txt>`, `scroll:down`, `key:HOME`) |
| `readNotifications` | Read incoming OTP / 2FA codes, SMS, and app notifications |
| `manageClipboard` | Read or write text to the Android device clipboard |
