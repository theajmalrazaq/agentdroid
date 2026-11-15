import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { AgentDroidServer, parseUiXml, findElement, isPrivateIp, Security, securityFromEnv, SecurityError } from "../src/index.ts";
import { createAgentDroidTools } from "../src/tools.ts";

const XML = `<hierarchy><node text="Settings" class="android.widget.TextView" resource-id="a:id/t" clickable="true" bounds="[0,100][200,300]" />
<node text="" content-desc="Search" class="android.widget.ImageButton" clickable="true" bounds="[300,0][400,100]" /></hierarchy>`;

function fakeAdb() {
  const dir = mkdtempSync(path.join(tmpdir(), "fakeadb-"));
  const log = path.join(dir, "log");
  const bin = path.join(dir, "adb");
  writeFileSync(bin, `#!/usr/bin/env bash
echo "$@" >> ${log}
cmd="\${@: -1}"
case "$cmd" in
  "echo ok") echo ok;;
  uiautomator*) cat <<'EOF'
${XML}
EOF
;;
  "dumpsys window"*) echo "mCurrentFocus=Window{1 u0 com.android.settings/com.android.settings.Main}";;
esac
`);
  chmodSync(bin, 0o755);
  return { bin, log };
}

async function start(opts: Record<string, unknown> = {}) {
  const f = fakeAdb();
  process.env.AGENTDROID_ADB = f.bin;
  const s = new AgentDroidServer({ port: 0, serial: "dev1", ...opts });
  const port = await s.listen();
  return { s, f, base: `http://127.0.0.1:${port}` };
}

test("parseUiXml / findElement", () => {
  const els = parseUiXml(XML);
  assert.equal(els.length, 2);
  assert.deepEqual(els[0].center, [100, 200]);
  assert.equal(findElement(els, "search")?.id, 1);
  assert.equal(findElement(els, "#0")?.label, "Settings");
});

test("private IP detection", () => {
  for (const ip of ["127.0.0.1", "10.1.1.1", "169.254.169.254", "192.168.0.5", "172.20.0.1", "::1", "fd00::1", "::ffff:127.0.0.1"]) assert.ok(isPrivateIp(ip), ip);
  assert.ok(!isPrivateIp("8.8.8.8"));
});

test("security: SSRF, path confinement, rate limit", async () => {
  const sec = new Security({ ...securityFromEnv(), dataDir: "/tmp/ad-data", rateLimitRpm: 2 });
  await assert.rejects(sec.validateUrl("http://169.254.169.254/latest"), SecurityError);
  await assert.rejects(sec.validateUrl("http://localhost:8080"), SecurityError);
  await assert.rejects(sec.validateUrl("file:///etc/passwd"), SecurityError);
  await sec.validateUrl("tel:123");
  assert.throws(() => sec.resolveDataPath("../../etc/passwd"), SecurityError);
  assert.throws(() => sec.resolveDataPath("/etc/passwd"), SecurityError);
  assert.equal(sec.resolveDataPath("a/b.apk"), "/tmp/ad-data/a/b.apk");
  sec.rateLimit("x"); sec.rateLimit("x");
  assert.throws(() => sec.rateLimit("x"), /Rate limit/);
});

test("rejects weak API keys", () => {
  assert.throws(() => new AgentDroidServer({ port: 0, apiKey: "change-me-to-a-long-random-string" }), /too weak/);
  assert.throws(() => new AgentDroidServer({ port: 0, apiKey: "short" }), /too weak/);
});

test("refuses non-loopback bind without API key", () => {
  assert.throws(() => new AgentDroidServer({ host: "0.0.0.0", port: 0 }), /Refusing/);
  new AgentDroidServer({ host: "0.0.0.0", port: 0, apiKey: "k".repeat(20) });
});

test("HTTP: auth, ui dump, do, run, SSRF block, body limit", async () => {
  const { s, f, base } = await start({ apiKey: "secret-secret-secret" });
  try {
    assert.equal((await fetch(`${base}/health`)).status, 200);
    assert.equal((await fetch(`${base}/api/v1/ui/dump`)).status, 401);
    assert.equal((await fetch(`${base}/api/v1/ui/dump?api_key=secret-secret-secret`)).status, 401, "query keys must not work");
    const h = { "X-API-Key": "secret-secret-secret", "Content-Type": "application/json" };

    const dump = await (await fetch(`${base}/api/v1/ui/dump`, { headers: h })).json() as any;
    assert.equal(dump.element_count, 2);
    assert.equal(dump.foreground, "com.android.settings");

    const doRes = await fetch(`${base}/api/v1/do`, { method: "POST", headers: h, body: JSON.stringify({ steps: ["click:Settings", "key:BACK", "type:hello world"] }) });
    assert.equal(doRes.status, 200);
    const log = readFileSync(f.log, "utf8");
    assert.match(log, /input tap 100 200/);
    assert.match(log, /input keyevent KEYCODE_BACK/);
    assert.match(log, /input text 'hello%sworld'/);

    const shell = await fetch(`${base}/api/v1/do`, { method: "POST", headers: h, body: JSON.stringify({ steps: ["shell:rm -rf /"] }) });
    assert.equal(shell.status, 400);

    const ssrf = await fetch(`${base}/api/v1/device/open-url`, { method: "POST", headers: h, body: JSON.stringify({ url: "http://169.254.169.254/" }) });
    assert.equal(ssrf.status, 403);

    const run = await (await fetch(`${base}/api/v1/run`, { method: "POST", headers: h, body: JSON.stringify({ open_url: "tel:123", do: ["click:Search"], assert_text: ["Settings", "Nope"] }) })).json() as any;
    assert.equal(run.ok, false);
    assert.deepEqual(run.errors, ["assert_text failed: Nope"]);
    assert.ok(run.opened && run.steps.length === 1);

    const big = await fetch(`${base}/api/v1/do`, { method: "POST", headers: h, body: JSON.stringify({ steps: ["type:" + "a".repeat(2_000_000)] }) });
    assert.equal(big.status, 413);
    assert.ok(existsSync(f.log));
  } finally { await s.close(); }
});

test("AI SDK tools execute against the server", async () => {
  const { s, base } = await start();
  try {
    const tools = createAgentDroidTools({ endpoint: base });
    assert.deepEqual(Object.keys(tools).sort(), ["inspectScreenUI", "performSemanticAction", "readNotifications", "runAndroidWorkflow", "screenshot"]);
    const out = await (tools.inspectScreenUI.execute as any)({}, { toolCallId: "1", messages: [] });
    assert.equal(out.element_count, 2);
  } finally { await s.close(); }
});
