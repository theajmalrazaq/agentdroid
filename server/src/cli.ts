#!/usr/bin/env node
import { AgentDroidServer } from "./server.ts";

const env = process.env;
const host = env.AGENTDROID_HOST ?? "127.0.0.1";
const port = Number(env.AGENTDROID_PORT ?? 8080);

try {
  const server = new AgentDroidServer({
    host,
    port,
    apiKey: env.AGENTDROID_API_KEY,
    serial: env.REDROID_ADDR ?? "127.0.0.1:5555",
    insecure: env.AGENTDROID_INSECURE === "true",
    trustProxy: env.AGENTDROID_TRUST_PROXY === "true",
    corsOrigin: env.AGENTDROID_CORS_ORIGIN,
  });
  const p = await server.listen();
  console.log(`agentdroid-server listening on http://${host}:${p} (auth ${env.AGENTDROID_API_KEY ? "on" : "off"})`);
  for (const sig of ["SIGINT", "SIGTERM"] as const) process.on(sig, () => void server.close().then(() => process.exit(0)));
} catch (e) {
  console.error((e as Error).message);
  process.exit(1);
}
