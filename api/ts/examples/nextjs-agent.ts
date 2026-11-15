/**
 * Complete Example: Autonomous Android AI Agent with Vercel AI SDK.
 *
 * This agent runs in your Next.js app or Node.js backend.
 * Notice: AgentDroid requires ZERO secondary LLM keys or .env!
 * The AI model (OpenAI, Anthropic, Gemini) running in your app drives AgentDroid.
 */

import { generateText, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { createAgentDroidTools } from "../src/vercel-ai";

async function main() {
  // Connect to your self-hosted AgentDroid cloud instance
  const agentdroid = createAgentDroidTools({
    endpoint: process.env.AGENTDROID_URL || "http://127.0.0.1:8080",
    apiKey: process.env.AGENTDROID_API_KEY,
  });

  console.log("🤖 Running autonomous Android AI agent via Vercel AI SDK...");

  const { text, steps } = await generateText({
    model: openai("gpt-4o"),
    prompt:
      "Open Hacker News on Android, scroll down, click the 'Past' link, and tell me what the top discussion is about.",
    tools: {
      runAndroidWorkflow: tool(agentdroid.runAndroidWorkflow),
      inspectScreenUI: tool(agentdroid.inspectScreenUI),
      performSemanticAction: tool(agentdroid.performSemanticAction),
      readNotifications: tool(agentdroid.readNotifications),
    },
    maxSteps: 5,
  });

  console.log("\n📋 Final AI Answer:\n", text);
  console.log(`\n✅ Completed in ${steps.length} tool execution steps.`);
}

if (require.main === module) {
  main().catch(console.error);
}
