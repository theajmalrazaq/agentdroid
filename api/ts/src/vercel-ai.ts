/**
 * Vercel AI SDK Tool Definitions for AgentDroid.
 *
 * Allows any Vercel AI SDK (generateText, streamText) agent in Next.js, Node.js,
 * or React to use AgentDroid as an autonomous Android computer.
 *
 * NO secondary LLM keys or .env are required on AgentDroid:
 * the host AI model in your web app IS the brain!
 */

import { AgentDroidClient, AgentDroidClientOptions, RunWorkflowParams } from "./client";

export interface AgentDroidToolDefinition<P = unknown, R = unknown> {
  description: string;
  parameters: Record<string, unknown>;
  execute: (params: P) => Promise<R>;
}

/**
 * Creates ready-to-use Vercel AI SDK tool definitions.
 *
 * Compatible with `tool(...)` from the `ai` package:
 * ```typescript
 * import { generateText, tool } from 'ai';
 * import { openai } from '@ai-sdk/openai';
 * import { createAgentDroidTools } from '@agentdroid/sdk';
 *
 * const tools = createAgentDroidTools({ endpoint: 'http://cloud-ip:8080' });
 * const { text } = await generateText({
 *   model: openai('gpt-4o'),
 *   prompt: 'Open Hacker News on Android and extract the top story',
 *   tools: {
 *     runAndroidWorkflow: tool(tools.runAndroidWorkflow),
 *     inspectScreenUI: tool(tools.inspectScreenUI),
 *     performSemanticAction: tool(tools.performSemanticAction),
 *   },
 * });
 * ```
 */
export function createAgentDroidTools(options: AgentDroidClientOptions | AgentDroidClient) {
  const client =
    options instanceof AgentDroidClient ? options : new AgentDroidClient(options);

  return {
    client,

    /** Tool 1: Execute complete compound Android workflows */
    runAndroidWorkflow: {
      description:
        "Execute a complete compound Android task (open URLs, install apps from F-Droid/APK, perform UI clicks/fills, assert text) in a single call.",
      parameters: {
        type: "object",
        properties: {
          open_url: {
            type: "string",
            description: "Web URL or deep link to open in the Android browser",
          },
          install: {
            type: "array",
            items: { type: "string" },
            description: "Apps to install (e.g. ['fdroid:net.gsantner.markor'])",
          },
          launch: {
            type: "string",
            description: "Package name or 'auto' to launch the installed app",
          },
          do: {
            type: "array",
            items: { type: "string" },
            description:
              "Sequential semantic UI actions, e.g. ['click:About', 'fill:Search=Android', 'key:ENTER', 'scroll:down']",
          },
          assert_text: {
            type: "array",
            items: { type: "string" },
            description: "Text strings to verify are present on screen",
          },
          notifications: {
            type: "boolean",
            description: "Whether to return active Android notifications",
          },
          clipboard: {
            type: "string",
            description: "Optional text to copy into device clipboard",
          },
        },
      },
      execute: async (params: RunWorkflowParams) => {
        return await client.run(params);
      },
    },

    /** Tool 2: Fast ~150-token screen perception */
    inspectScreenUI: {
      description:
        "Inspect the current Android screen in ~150 tokens. Returns all visible interactive elements, labels, and coordinates.",
      parameters: {
        type: "object",
        properties: {
          max_elements: {
            type: "number",
            description: "Maximum number of visible elements to return (default: 60)",
          },
        },
      },
      execute: async (params: { max_elements?: number } = {}) => {
        return await client.dumpUI(params.max_elements);
      },
    },

    /** Tool 3: Step-by-step semantic UI actions */
    performSemanticAction: {
      description:
        "Perform a single semantic UI action on Android screen: click:<text_or_#id>, fill:<selector>=<text>, scroll:down|up, scroll-to:<text>, key:HOME|BACK|ENTER, or tap:x,y",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "Semantic action string, e.g. 'click:Login', 'fill:Email=test@example.com', 'key:BACK'",
          },
        },
        required: ["action"],
      },
      execute: async (params: { action: string }) => {
        return await client.do(params.action);
      },
    },

    /** Tool 4: Read 2FA / OTP codes and active notifications */
    readNotifications: {
      description:
        "Read incoming device notifications (useful for extracting 2FA verification codes, SMS, OTPs, or app alerts).",
      parameters: {
        type: "object",
        properties: {
          include_system: {
            type: "boolean",
            description: "Whether to include system notifications",
          },
        },
      },
      execute: async (params: { include_system?: boolean } = {}) => {
        return await client.getNotifications(params.include_system);
      },
    },

    /** Tool 5: Read and write Android clipboard */
    manageClipboard: {
      description: "Read or write text to the Android device clipboard.",
      parameters: {
        type: "object",
        properties: {
          text_to_copy: {
            type: "string",
            description: "If provided, copies this text to the Android clipboard. If omitted, reads the clipboard.",
          },
        },
      },
      execute: async (params: { text_to_copy?: string } = {}) => {
        if (params.text_to_copy !== undefined) {
          await client.setClipboard(params.text_to_copy);
          return { ok: true, action: "set_clipboard", text: params.text_to_copy };
        }
        const current = await client.getClipboard();
        return { ok: true, action: "get_clipboard", text: current };
      },
    },
  };
}
