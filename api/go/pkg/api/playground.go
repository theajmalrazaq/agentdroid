package api

import (
	"net/http"
)

const playgroundHTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AgentDroid — Cloud Android AI Computer (Go Server)</title>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --heading: #f0f6fc;
      --accent: #238636;
      --accent-hover: #2ea043;
      --primary: #58a6ff;
      --danger: #f85149;
      --code-bg: #0b0e14;
      --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.5;
      padding-bottom: 40px;
    }
    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand h1 {
      font-size: 1.25rem;
      color: var(--heading);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .badge {
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .badge-online { background: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid #238636; }
    .badge-offline { background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid #da3633; }
    .auth-input-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .auth-input-group input {
      background: var(--code-bg);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.85rem;
      width: 220px;
    }
    .btn {
      background: var(--card-bg);
      color: var(--heading);
      border: 1px solid var(--border);
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .btn:hover { background: #21262d; border-color: #8b949e; }
    .btn-primary { background: var(--accent); border-color: rgba(240, 246, 252, 0.1); color: #fff; }
    .btn-primary:hover { background: var(--accent-hover); }
    .container {
      max-width: 1280px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .nav-tabs {
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 20px;
    }
    .tab-btn {
      background: transparent;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text);
      padding: 8px 16px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
    }
    .tab-btn.active {
      color: var(--primary);
      border-bottom-color: var(--primary);
    }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .grid {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 20px;
    }
    @media (max-width: 860px) {
      .grid { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .card h2 {
      font-size: 1rem;
      color: var(--heading);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .form-group {
      margin-bottom: 12px;
    }
    .form-group label {
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      margin-bottom: 4px;
      color: var(--text);
    }
    .form-group input, .form-group textarea, .form-group select {
      width: 100%;
      background: var(--code-bg);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 10px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-family: inherit;
    }
    .form-group textarea {
      font-family: var(--font-mono);
      resize: vertical;
      min-height: 80px;
    }
    .keypad-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }
    pre {
      background: var(--code-bg);
      border: 1px solid var(--border);
      padding: 12px;
      border-radius: 6px;
      font-family: var(--font-mono);
      font-size: 0.82rem;
      overflow-x: auto;
      max-height: 480px;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .ui-element-item {
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      font-size: 0.85rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .ui-element-item:hover { background: rgba(88, 166, 255, 0.08); }
    .ui-tag {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      background: rgba(110, 118, 129, 0.2);
      padding: 1px 6px;
      border-radius: 4px;
      color: var(--primary);
    }
    .flex-row {
      display: flex;
      gap: 8px;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>🤖 AgentDroid <span style="font-size: 0.8rem; font-weight: normal; color: #8b949e;">Modular Go API</span></h1>
      <span id="status-badge" class="badge badge-online">Connecting...</span>
    </div>
    <div class="auth-input-group">
      <input type="password" id="api-key-input" placeholder="Optional API Key (X-API-Key)" />
      <button class="btn" onclick="saveApiKey()">Save Key</button>
    </div>
  </header>

  <div class="container">
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('tab-control')">📱 Live Device Control</button>
      <button class="tab-btn" onclick="switchTab('tab-pipeline')">🚀 Compound Pipeline Runner</button>
      <button class="tab-btn" onclick="switchTab('tab-ui-tree')">🌲 UI Element Inspector (~150 Tokens)</button>
      <button class="tab-btn" onclick="switchTab('tab-code')">💻 Website Integration (Vercel AI SDK & JS)</button>
    </div>

    <!-- TAB 1: Live Control -->
    <div id="tab-control" class="tab-pane active">
      <div class="grid">
        <div>
          <div class="card">
            <h2>Quick Actions</h2>
            <div class="form-group">
              <label>Open Web URL or Deep Link</label>
              <div class="flex-row">
                <input type="text" id="open-url-input" value="https://news.ycombinator.com" />
                <button class="btn btn-primary" onclick="openUrl()">Open</button>
              </div>
            </div>
            <div class="form-group">
              <label>Run Semantic Action (--do)</label>
              <div class="flex-row">
                <input type="text" id="do-input" placeholder="click:Login or fill:User=test" />
                <button class="btn btn-primary" onclick="runDoAction()">Do</button>
              </div>
              <small style="color: #8b949e; font-size: 0.75rem;">Supports click:&lt;text&gt;, fill:&lt;sel&gt;=&lt;text&gt;, scroll:down, key:HOME</small>
            </div>
            <div class="form-group">
              <label>Send Global Hardware Key</label>
              <div class="keypad-grid">
                <button class="btn" onclick="sendKey('BACK')">◀ Back</button>
                <button class="btn" onclick="sendKey('HOME')">● Home</button>
                <button class="btn" onclick="sendKey('RECENTS')">■ Recents</button>
                <button class="btn" onclick="sendKey('ENTER')">↵ Enter</button>
                <button class="btn" onclick="sendKey('UP')">▲ Up</button>
                <button class="btn" onclick="sendKey('DOWN')">▼ Down</button>
              </div>
            </div>
          </div>

          <div class="card">
            <h2>Device Clipboard & Notifications</h2>
            <div class="form-group">
              <label>Clipboard Text</label>
              <div class="flex-row">
                <input type="text" id="clipboard-input" placeholder="Text to paste into phone" />
                <button class="btn" onclick="setClipboard()">Set</button>
                <button class="btn" onclick="getClipboard()">Get</button>
              </div>
            </div>
            <div class="form-group">
              <button class="btn" style="width: 100%;" onclick="fetchNotifications()">🔔 Read Active Notifications</button>
            </div>
          </div>
        </div>

        <div>
          <div class="card">
            <h2>
              Live Screen / Output
              <button class="btn" onclick="refreshUiTree()">🔄 Refresh UI</button>
            </h2>
            <div id="action-status" style="font-size: 0.85rem; margin-bottom: 8px; color: var(--primary);">Ready</div>
            <pre id="output-box">{ "status": "Ready to execute commands on cloud Android" }</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 2: Compound Pipeline Runner -->
    <div id="tab-pipeline" class="tab-pane">
      <div class="grid">
        <div>
          <div class="card">
            <h2>Compound JSON Task Spec</h2>
            <div class="form-group">
              <label>Preset Templates</label>
              <select id="preset-selector" onchange="loadPreset()">
                <option value="web">Web Research & Navigation</option>
                <option value="fdroid">Install F-Droid App & Execute</option>
                <option value="settings">Navigate Android 16 Settings</option>
              </select>
            </div>
            <div class="form-group">
              <label>Pipeline JSON Payload</label>
              <textarea id="pipeline-payload" style="height: 320px;"></textarea>
            </div>
            <button class="btn btn-primary" style="width: 100%;" onclick="executePipeline()">🚀 Run Compound Pipeline</button>
          </div>
        </div>
        <div>
          <div class="card">
            <h2>Execution Result Report</h2>
            <pre id="pipeline-result-box">// Results will appear here...</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 3: UI Inspector -->
    <div id="tab-ui-tree" class="tab-pane">
      <div class="card">
        <h2>
          <span>Compact Labelled Elements (~150 Tokens)</span>
          <button class="btn btn-primary" onclick="loadUiInspector()">Refresh Inspector</button>
        </h2>
        <div id="ui-elements-list" style="max-height: 520px; overflow-y: auto;">
          <div style="padding: 16px; color: #8b949e;">Click "Refresh Inspector" to dump current screen elements.</div>
        </div>
      </div>
    </div>

    <!-- TAB 4: Website Integration -->
    <div id="tab-code" class="tab-pane">
      <div class="card">
        <h2>Talk to AgentDroid from Vercel AI SDK or Your Website</h2>
        <p style="margin-bottom: 12px; font-size: 0.9rem;">
          Deploy AgentDroid on cloud and connect with Vercel AI SDK (zero API keys needed on AgentDroid):
        </p>

        <h3 style="font-size: 0.9rem; margin: 16px 0 8px; color: var(--primary);">Vercel AI SDK (Tool Calling in Next.js / TypeScript)</h3>
        <pre id="code-vercel"></pre>

        <h3 style="font-size: 0.9rem; margin: 16px 0 8px; color: var(--primary);">Go Client (High Performance SDK)</h3>
        <pre id="code-go"></pre>

        <h3 style="font-size: 0.9rem; margin: 16px 0 8px; color: var(--primary);">cURL Command</h3>
        <pre id="code-curl"></pre>
      </div>
    </div>
  </div>

  <script>
    const API_BASE = window.location.origin;

    function getApiKey() {
      return localStorage.getItem("agentdroid_api_key") || "";
    }

    function saveApiKey() {
      const key = document.getElementById("api-key-input").value.trim();
      localStorage.setItem("agentdroid_api_key", key);
      alert("API Key saved locally!");
      checkHealth();
    }

    function getHeaders() {
      const h = { "Content-Type": "application/json" };
      const k = getApiKey();
      if (k) h["X-API-Key"] = k;
      return h;
    }

    async function checkHealth() {
      const badge = document.getElementById("status-badge");
      try {
        const res = await fetch(API_BASE + "/health", { headers: getHeaders() });
        const data = await res.json();
        if (data.ok) {
          badge.textContent = "Online (" + (data.device || "Android") + ")";
          badge.className = "badge badge-online";
        } else {
          badge.textContent = "Error";
          badge.className = "badge badge-offline";
        }
      } catch (e) {
        badge.textContent = "Offline";
        badge.className = "badge badge-offline";
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.getElementById(tabId).classList.add("active");
      event.target.classList.add("active");
      if (tabId === "tab-ui-tree") loadUiInspector();
    }

    async function openUrl() {
      const url = document.getElementById("open-url-input").value.trim();
      setStatus("Opening " + url + "...");
      const res = await fetch(API_BASE + "/api/v1/device/open-url", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ url: url })
      });
      const data = await res.json();
      displayOutput(data);
    }

    async function runDoAction() {
      const act = document.getElementById("do-input").value.trim();
      setStatus("Executing " + act + "...");
      const res = await fetch(API_BASE + "/api/v1/do", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ action: act })
      });
      const data = await res.json();
      displayOutput(data);
    }

    async function sendKey(key) {
      setStatus("Sending key " + key + "...");
      const res = await fetch(API_BASE + "/api/v1/ui/key", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ key: key })
      });
      const data = await res.json();
      displayOutput(data);
    }

    async function getClipboard() {
      setStatus("Fetching clipboard...");
      const res = await fetch(API_BASE + "/api/v1/device/clipboard", { headers: getHeaders() });
      const data = await res.json();
      document.getElementById("clipboard-input").value = data.clipboard || "";
      displayOutput(data);
    }

    async function setClipboard() {
      const text = document.getElementById("clipboard-input").value;
      setStatus("Setting clipboard...");
      const res = await fetch(API_BASE + "/api/v1/device/clipboard", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ text: text })
      });
      const data = await res.json();
      displayOutput(data);
    }

    async function fetchNotifications() {
      setStatus("Fetching active notifications...");
      const res = await fetch(API_BASE + "/api/v1/device/notifications", { headers: getHeaders() });
      const data = await res.json();
      displayOutput(data);
    }

    async function refreshUiTree() {
      try {
        const res = await fetch(API_BASE + "/api/v1/ui/dump", { headers: getHeaders() });
        const data = await res.json();
        setStatus("Screen updated: " + (data.element_count || 0) + " visible elements");
      } catch (e) {
        setStatus("Could not fetch UI tree: " + e.message);
      }
    }

    async function loadUiInspector() {
      const container = document.getElementById("ui-elements-list");
      container.innerHTML = '<div style="padding: 16px;">Loading visible elements...</div>';
      try {
        const res = await fetch(API_BASE + "/api/v1/ui/dump", { headers: getHeaders() });
        const data = await res.json();
        const elements = data.elements || [];
        if (elements.length === 0) {
          container.innerHTML = '<div style="padding: 16px; color: #8b949e;">No interactive elements found on current screen.</div>';
          return;
        }
        let html = "";
        for (const el of elements) {
          html += '<div class="ui-element-item">' +
            '<div>' +
              '<strong>' + escapeHtml(el.label || el.desc || "(unlabelled)") + '</strong> ' +
              '<span class="ui-tag">' + escapeHtml(el.class || "") + '</span> ' +
              '<span style="font-size: 0.75rem; color: #8b949e;">@ [' + (el.center ? el.center.join(", ") : "") + ']</span>' +
            '</div>' +
            '<div>' +
              '<button class="btn" style="padding: 2px 8px; font-size: 0.75rem;" onclick="tapElement(' + el.id + ')">Tap #' + el.id + '</button>' +
            '</div>' +
          '</div>';
        }
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = '<div style="padding: 16px; color: #f85149;">Error: ' + escapeHtml(e.message) + '</div>';
      }
    }

    async function tapElement(id) {
      setStatus("Tapping element #" + id + "...");
      const res = await fetch(API_BASE + "/api/v1/do", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ action: "click:#" + id })
      });
      const data = await res.json();
      displayOutput(data);
      loadUiInspector();
    }

    const PRESETS = {
      web: {
        open_url: "https://news.ycombinator.com",
        do: ["scroll:down", "click:Past"],
        assert_text: ["Hacker News"],
        notifications: true
      },
      fdroid: {
        install: ["fdroid:net.gsantner.markor"],
        launch: "auto",
        do: ["click:QuickNote", "type:Hello from Cloud AgentDroid!"],
        notifications: true
      },
      settings: {
        launch: "com.android.settings",
        do: ["scroll-to:About", "click:About"],
        assert_text: ["Android"]
      }
    };

    function loadPreset() {
      const key = document.getElementById("preset-selector").value;
      document.getElementById("pipeline-payload").value = JSON.stringify(PRESETS[key] || PRESETS.web, null, 2);
    }

    async function executePipeline() {
      const box = document.getElementById("pipeline-result-box");
      box.textContent = "Executing compound pipeline on Android...";
      try {
        const payload = JSON.parse(document.getElementById("pipeline-payload").value);
        const res = await fetch(API_BASE + "/api/v1/run", {
          method: "POST",
          headers: getHeaders(),
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        box.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        box.textContent = "Execution Error: " + e.message;
      }
    }

    function setStatus(msg) {
      document.getElementById("action-status").textContent = msg;
    }

    function displayOutput(data) {
      document.getElementById("output-box").textContent = JSON.stringify(data, null, 2);
    }

    function escapeHtml(str) {
      if (!str) return "";
      return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function updateCodeSnippets() {
      const origin = window.location.origin;
      document.getElementById("code-vercel").textContent = '// Vercel AI SDK (Next.js / TypeScript) - ZERO secondary API keys on AgentDroid!\n' +
        'import { generateText, tool } from "ai";\n' +
        'import { openai } from "@ai-sdk/openai";\n' +
        'import { z } from "zod";\n' +
        'import { createAgentDroidTools } from "@agentdroid/sdk";\n\n' +
        'const { runAndroidWorkflow, inspectScreenUI } = createAgentDroidTools({\n' +
        '  endpoint: "' + origin + '",\n' +
        '});\n\n' +
        'const { text } = await generateText({\n' +
        '  model: openai("gpt-4o"),\n' +
        '  prompt: "Open Hacker News on Android, read top stories and tell me what is #1",\n' +
        '  tools: { runAndroidWorkflow, inspectScreenUI },\n' +
        '  maxSteps: 5,\n' +
        '});';

      document.getElementById("code-go").textContent = 'package main\n\n' +
        'import (\n' +
        '\t"context"\n' +
        '\t"fmt"\n' +
        '\t"github.com/theajmalrazaq/agentdroid/api/go/pkg/client"\n' +
        ')\n\n' +
        'func main() {\n' +
        '\tc := client.NewClient("' + origin + '", "")\n' +
        '\tresult, err := c.Run(context.Background(), &client.RunRequest{\n' +
        '\t\tOpenURL: "https://news.ycombinator.com",\n' +
        '\t\tDo: []string{"scroll:down", "click:Past"},\n' +
        '\t})\n' +
        '\tif err != nil { panic(err) }\n' +
        '\tfmt.Println("Success:", result.OK)\n' +
        '}';

      document.getElementById("code-curl").textContent = 'curl -X POST "' + origin + '/api/v1/run" \\\n' +
        '  -H "Content-Type: application/json" \\\n' +
        '  -d \'{\n' +
        '    "open_url": "https://news.ycombinator.com",\n' +
        '    "do": ["scroll:down", "click:Past"],\n' +
        '    "assert_text": ["Hacker News"]\n' +
        '  }\'';
    }

    window.addEventListener("DOMContentLoaded", () => {
      document.getElementById("api-key-input").value = getApiKey();
      loadPreset();
      checkHealth();
      updateCodeSnippets();
      setInterval(checkHealth, 10000);
    });
  </script>
</body>
</html>`

func (r *Router) handlePlayground(w http.ResponseWriter, req *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(playgroundHTML))
}
