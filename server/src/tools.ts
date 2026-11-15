import { tool } from "ai";
import { z } from "zod";
import { AgentDroidClient, type ClientOptions } from "./client.ts";

/**
 * Vercel AI SDK tools for AgentDroid. No LLM keys live on the server:
 * your app's model is the brain, these tools are its eyes and hands.
 *
 *   const { text } = await generateText({
 *     model, tools: createAgentDroidTools({ endpoint, apiKey }), stopWhen: stepCountIs(10), prompt,
 *   });
 */
export function createAgentDroidTools(options: ClientOptions | AgentDroidClient) {
  const c = options instanceof AgentDroidClient ? options : new AgentDroidClient(options);
  return {
    runAndroidWorkflow: tool({
      description:
        "Run a compound Android task in ONE call: install apps, open a URL, launch an app, run UI steps, read notifications, assert text. Returns a compact UI summary.",
      inputSchema: z.object({
        open_url: z.string().optional(),
        install: z.array(z.string()).optional().describe("e.g. ['fdroid:net.gsantner.markor']"),
        launch: z.string().optional().describe("Android package name"),
        do: z.array(z.string()).optional().describe("Steps: click:<text|#n>, fill:<sel>=<text>, scroll:down, scroll-to:<text>, key:BACK, tap:x,y, type:<text>, sleep:<s>"),
        assert_text: z.array(z.string()).optional(),
        notifications: z.boolean().optional(),
      }),
      execute: (input) => c.run(input),
    }),
    inspectScreenUI: tool({
      description: "Read the visible screen as a compact element list (~150 tokens).",
      inputSchema: z.object({ max_elements: z.number().int().min(1).max(200).optional() }),
      execute: ({ max_elements }) => c.ui(max_elements),
    }),
    performSemanticAction: tool({
      description: "Perform sequential UI steps (click:, fill:, scroll:, scroll-to:, key:, tap:, type:, sleep:).",
      inputSchema: z.object({ steps: z.array(z.string()).min(1) }),
      execute: ({ steps }) => c.do(steps),
    }),
    readNotifications: tool({
      description: "Read active Android notifications (messages, 2FA/OTP codes).",
      inputSchema: z.object({}),
      execute: () => c.notifications(),
    }),
    screenshot: tool({
      description: "Capture a screenshot as base64 PNG.",
      inputSchema: z.object({}),
      execute: () => c.screenshotBase64(),
    }),
  };
}
