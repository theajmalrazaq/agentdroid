"""AgentDroid HTTP REST API & Web Playground Server.

Enables self-hosted cloud deployments on any Linux VPS/server (AWS, Hetzner,
DigitalOcean, GCP) so websites, web apps, SaaS backends, and remote AI agents
can control the silent Android device over HTTP/JSON with zero extra dependencies.
"""

from __future__ import annotations

import base64
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import urllib.parse

from agentdroid.adb import AdbDevice
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.pipeline import CompoundPipeline, PipelineSpec, parse_do_step


def _build_playground_html() -> str:
    """Generate the self-contained AgentDroid Web Playground & Developer Dashboard HTML."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AgentDroid — Cloud Android AI Computer</title>
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
      <h1>🤖 AgentDroid <span style="font-size: 0.8rem; font-weight: normal; color: #8b949e;">Cloud API</span></h1>
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
      <button class="tab-btn" onclick="switchTab('tab-code')">💻 Website Integration (JS/Python/cURL)</button>
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
        <h2>Talk to AgentDroid from your Website or Cloud App</h2>
        <p style="margin-bottom: 12px; font-size: 0.9rem;">
          Deploy AgentDroid on your server and connect any website, frontend, or backend over HTTP with simple REST calls:
        </p>

        <h3 style="font-size: 0.9rem; margin: 16px 0 8px; color: var(--primary);">JavaScript / TypeScript (Fetch from Website Frontend or Node.js)</h3>
        <pre id="code-js"></pre>

        <h3 style="font-size: 0.9rem; margin: 16px 0 8px; color: var(--primary);">Python (Requests / HTTPX)</h3>
        <pre id="code-python"></pre>

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
        const res = await fetch(`${API_BASE}/health`, { headers: getHeaders() });
        const data = await res.json();
        if (data.ok) {
          badge.textContent = `Online (${data.device || 'Android'})`;
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
      if (tabId === 'tab-ui-tree') loadUiInspector();
    }

    async function openUrl() {
      const url = document.getElementById("open-url-input").value.trim();
      setStatus("Opening " + url + "...");
      const res = await fetch(`${API_BASE}/api/v1/device/open-url`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ url })
      });
      const data = await res.json();
      displayOutput(data);
      refreshUiTree();
    }

    async function runDoAction() {
      const act = document.getElementById("do-input").value.trim();
      setStatus("Executing " + act + "...");
      const res = await fetch(`${API_BASE}/api/v1/do`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ action: act })
      });
      const data = await res.json();
      displayOutput(data);
      refreshUiTree();
    }

    async function sendKey(key) {
      setStatus("Sending key " + key + "...");
      const res = await fetch(`${API_BASE}/api/v1/ui/key`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ key })
      });
      const data = await res.json();
      displayOutput(data);
      refreshUiTree();
    }

    async function getClipboard() {
      setStatus("Fetching clipboard...");
      const res = await fetch(`${API_BASE}/api/v1/device/clipboard`, { headers: getHeaders() });
      const data = await res.json();
      document.getElementById("clipboard-input").value = data.clipboard || "";
      displayOutput(data);
    }

    async function setClipboard() {
      const text = document.getElementById("clipboard-input").value;
      setStatus("Setting clipboard...");
      const res = await fetch(`${API_BASE}/api/v1/device/clipboard`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ text })
      });
      const data = await res.json();
      displayOutput(data);
    }

    async function fetchNotifications() {
      setStatus("Fetching active notifications...");
      const res = await fetch(`${API_BASE}/api/v1/device/notifications`, { headers: getHeaders() });
      const data = await res.json();
      displayOutput(data);
    }

    async function refreshUiTree() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/ui/dump`, { headers: getHeaders() });
        const data = await res.json();
        setStatus(`Screen updated: ${data.element_count || 0} visible elements`);
      } catch (e) {
        setStatus("Could not fetch UI tree: " + e.message);
      }
    }

    async function loadUiInspector() {
      const container = document.getElementById("ui-elements-list");
      container.innerHTML = '<div style="padding: 16px;">Loading visible elements...</div>';
      try {
        const res = await fetch(`${API_BASE}/api/v1/ui/dump`, { headers: getHeaders() });
        const data = await res.json();
        const elements = data.elements || [];
        if (elements.length === 0) {
          container.innerHTML = '<div style="padding: 16px; color: #8b949e;">No interactive elements found on current screen.</div>';
          return;
        }
        let html = '';
        for (const el of elements) {
          html += `
            <div class="ui-element-item">
              <div>
                <strong>${escapeHtml(el.label || el.desc || '(unlabelled)')}</strong>
                <span class="ui-tag">${escapeHtml(el.class || '')}</span>
                <span style="font-size: 0.75rem; color: #8b949e;">@ [${el.center ? el.center.join(', ') : ''}]</span>
              </div>
              <div>
                <button class="btn" style="padding: 2px 8px; font-size: 0.75rem;" onclick="tapElement('${escapeHtml(el.id)}')">Tap #${el.id}</button>
              </div>
            </div>
          `;
        }
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = `<div style="padding: 16px; color: #f85149;">Error: ${escapeHtml(e.message)}</div>`;
      }
    }

    async function tapElement(id) {
      setStatus("Tapping element #" + id + "...");
      const res = await fetch(`${API_BASE}/api/v1/do`, {
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
        do: [
          "scroll:down",
          "click:Past"
        ],
        assert_text: ["Hacker News"],
        notifications: true,
        clipboard: true
      },
      fdroid: {
        install: ["fdroid:net.gsantner.markor"],
        launch: "auto",
        do: [
          "click:QuickNote",
          "type:Hello from Cloud AgentDroid!"
        ],
        notifications: true
      },
      settings: {
        launch: "com.android.settings",
        do: [
          "scroll-to:About",
          "click:About",
          "scroll-to:Android version"
        ],
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
        const res = await fetch(`${API_BASE}/api/v1/run`, {
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
      document.getElementById("code-js").textContent = `// Execute any Android workflow from your website backend or frontend
const response = await fetch("${origin}/api/v1/run", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    // "X-API-Key": "YOUR_OPTIONAL_API_KEY"
  },
  body: JSON.stringify({
    open_url: "https://news.ycombinator.com",
    do: ["scroll:down", "click:Past"],
    assert_text: ["Hacker News"],
    notifications: true
  })
});
const result = await response.json();
console.log("Device output:", result);`;

      document.getElementById("code-python").textContent = `import httpx

response = httpx.post(
    "${origin}/api/v1/run",
    json={
        "open_url": "https://news.ycombinator.com",
        "do": ["scroll:down", "click:Past"],
        "assert_text": ["Hacker News"],
    },
    timeout=60.0,
)
print(response.json())`;

      document.getElementById("code-curl").textContent = `curl -X POST "${origin}/api/v1/run" \\
  -H "Content-Type: application/json" \\
  -d '{
    "open_url": "https://news.ycombinator.com",
    "do": ["scroll:down", "click:Past"],
    "assert_text": ["Hacker News"]
  }'`;
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
</html>
"""


class AgentDroidRequestHandler(BaseHTTPRequestHandler):
    """Multi-threaded REST API and static Web Playground handler."""

    server_version = "AgentDroid/0.2.0"

    @property
    def server_instance(self) -> AgentDroidServer:
        return self.server  # type: ignore[return-value]

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.server_instance.cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-API-Key, Accept, Origin",
        )

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def _is_authorized(self) -> bool:
        required_key = self.server_instance.api_key
        if not required_key:
            return True

        # 1. Check Header: X-API-Key
        x_key = self.headers.get("X-API-Key", "").strip()
        if x_key and x_key == required_key:
            return True

        # 2. Check Header: Authorization: Bearer <key>
        auth = self.headers.get("Authorization", "").strip()
        if auth.startswith("Bearer "):
            bearer = auth[7:].strip()
            if bearer == required_key:
                return True

        # 3. Check Query Param: ?api_key=<key>
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        query_key = qs.get("api_key", [""])[0].strip()
        if query_key and query_key == required_key:
            return True

        return False

    def _send_json(self, data: Any, status: int = 200) -> None:
        raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if not length_header:
            return {}
        try:
            length = int(length_header)
            raw = self.rfile.read(length).decode("utf-8")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {"_raw": parsed}
            return parsed
        except Exception as e:
            raise ValueError(f"Invalid JSON request body: {e}") from e

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        # Public endpoints (Playground and Health check)
        if path in ("/", "/playground"):
            content = _build_playground_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        if path in ("/health", "/api/v1/health"):
            adb = self.server_instance.get_adb()
            connected = adb.is_connected()
            self._send_json(
                {
                    "ok": True,
                    "status": "online",
                    "service": "agentdroid",
                    "version": "0.2.0",
                    "device": adb.serial,
                    "device_connected": connected,
                    "timestamp": time.time(),
                }
            )
            return

        # Check authorization for API endpoints
        if not self._is_authorized():
            self._send_error_json("Unauthorized: missing or invalid API key", status=401)
            return

        if path in ("/api/v1/info", "/api/v1/device/info"):
            adb = self.server_instance.get_adb()
            info = adb.get_device_info()
            self._send_json({"ok": True, "device": info})
            return

        if path == "/api/v1/doctor":
            from agentdroid.cli import _run_doctor_checks

            report = _run_doctor_checks(
                serial=self.server_instance.serial,
                artemis_url=self.server_instance.artemis_url,
            )
            self._send_json(report)
            return

        if path == "/api/v1/ui/dump":
            helper = self.server_instance.get_helper()
            qs = urllib.parse.parse_qs(parsed.query)
            max_el = int(qs.get("max_elements", [80])[0])
            dump = helper.dump_compact_ui(max_elements=max_el)
            self._send_json(dump)
            return

        if path == "/api/v1/ui/screenshot":
            adb = self.server_instance.get_adb()
            qs = urllib.parse.parse_qs(parsed.query)
            as_b64 = qs.get("format", ["binary"])[0] == "base64"
            png_bytes = adb.screenshot_png_bytes()
            if not png_bytes:
                self._send_error_json("Failed to capture screenshot from device", status=500)
                return
            if as_b64:
                self._send_json(
                    {
                        "ok": True,
                        "format": "base64",
                        "image_base64": base64.b64encode(png_bytes).decode("ascii"),
                    }
                )
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(png_bytes)
            return

        if path == "/api/v1/device/notifications":
            adb = self.server_instance.get_adb()
            qs = urllib.parse.parse_qs(parsed.query)
            inc_sys = qs.get("all", ["false"])[0].lower() in ("true", "1")
            notifs = adb.get_active_notifications(include_system=inc_sys)
            self._send_json({"ok": True, "notifications": notifs, "count": len(notifs)})
            return

        if path == "/api/v1/device/clipboard":
            adb = self.server_instance.get_adb()
            text = adb.get_clipboard()
            self._send_json({"ok": True, "clipboard": text})
            return

        if path == "/api/v1/apps":
            adb = self.server_instance.get_adb()
            pkgs = adb.list_installed_packages(third_party_only=True)
            self._send_json({"ok": True, "packages": pkgs, "count": len(pkgs)})
            return

        self._send_error_json(f"Endpoint not found: {path}", status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not self._is_authorized():
            self._send_error_json("Unauthorized: missing or invalid API key", status=401)
            return

        try:
            body = self._read_json_body()
        except ValueError as e:
            self._send_error_json(str(e), status=400)
            return

        # 1. Full Compound Pipeline Execution
        if path == "/api/v1/run":
            spec_dict = dict(body)
            if not spec_dict.get("serial"):
                spec_dict["serial"] = self.server_instance.serial
            if not spec_dict.get("artemis_url"):
                spec_dict["artemis_url"] = self.server_instance.artemis_url

            spec = PipelineSpec.from_dict(spec_dict)
            pipeline = CompoundPipeline(spec)
            report = pipeline.run()
            status_code = 200 if report.get("ok") else 500
            self._send_json(report, status=status_code)
            return

        # 2. Sequential Semantic UI Actions (--do)
        if path == "/api/v1/do":
            helper = self.server_instance.get_helper()
            actions: list[Any] = []
            if "actions" in body:
                actions = list(body["actions"])
            elif "action" in body:
                actions = [body["action"]]
            elif "do" in body:
                actions = [body["do"]] if isinstance(body["do"], str) else list(body["do"])

            results: list[dict[str, Any]] = []
            for item in actions:
                step = parse_do_step(item) if isinstance(item, str) else item
                stype = step.get("type", "click")
                if stype == "click":
                    res = helper.tap_element(step.get("selector", ""))
                elif stype == "fill":
                    res = helper.fill_element(step.get("selector", ""), step.get("text", ""))
                elif stype == "type":
                    res = helper.action("type", text=step.get("text", ""))
                elif stype == "tap":
                    res = helper.action("tap", x=step.get("x", 0), y=step.get("y", 0))
                elif stype == "scroll":
                    res = helper.action("scroll", direction=step.get("direction", "down"))
                elif stype == "scroll_to":
                    res = helper.scroll_to_element(step.get("text", ""))
                elif stype == "key":
                    res = helper.action("global", action=step.get("key", "BACK"))
                elif stype == "sleep":
                    time.sleep(float(step.get("seconds", 1.0)))
                    res = {"success": True, "action": "sleep"}
                else:
                    res = {"success": False, "error": f"Unknown action type: {stype}"}
                results.append(res)

            ui = helper.dump_compact_ui()
            self._send_json({"ok": True, "steps": results, "ui_summary": ui})
            return

        # 3. Direct Primitive UI Gestures
        if path == "/api/v1/ui/tap":
            helper = self.server_instance.get_helper()
            x = float(body.get("x", 0))
            y = float(body.get("y", 0))
            res = helper.action("tap", x=x, y=y)
            self._send_json({"ok": bool(res.get("success", True)), "result": res})
            return

        if path == "/api/v1/ui/type":
            helper = self.server_instance.get_helper()
            text = str(body.get("text", ""))
            res = helper.action("type", text=text)
            self._send_json({"ok": bool(res.get("success", True)), "result": res})
            return

        if path == "/api/v1/ui/key":
            helper = self.server_instance.get_helper()
            key = str(body.get("key", "BACK"))
            res = helper.action("global", action=key)
            self._send_json({"ok": bool(res.get("success", True)), "result": res})
            return

        # 4. Device State Management
        if path == "/api/v1/device/clipboard":
            adb = self.server_instance.get_adb()
            text = str(body.get("text", ""))
            ok = adb.set_clipboard(text)
            self._send_json({"ok": ok, "clipboard": text})
            return

        if path == "/api/v1/device/open-url":
            adb = self.server_instance.get_adb()
            target_url = str(body.get("url") or body.get("uri") or "")
            if not target_url:
                self._send_error_json("Missing 'url' or 'uri' in body", status=400)
                return
            res = adb.open_uri(target_url, package=body.get("package"))
            self._send_json({"ok": bool(res.get("opened")), "result": res})
            return

        # 5. App Installation & Management
        if path == "/api/v1/app/install":
            adb = self.server_instance.get_adb()
            source = str(body.get("source") or body.get("apk") or "")
            if not source:
                self._send_error_json("Missing 'source' in body (path, URL, or fdroid:<query>)", status=400)
                return
            info = adb.install_apk(
                source,
                grant_permissions=bool(body.get("grant_permissions", True)),
                clear_data=bool(body.get("clear_data", False)),
            )
            launched = None
            if body.get("launch") and info.package:
                launched = adb.launch_app(info.package)
            self._send_json(
                {
                    "ok": True,
                    "installed": info.to_dict(),
                    "launched": launched,
                }
            )
            return

        self._send_error_json(f"Endpoint not found: {path}", status=404)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep background server logs concise
        if os.environ.get("AGENTDROID_VERBOSE"):
            sys.stderr.write(f"[agentdroid:server] {self.address_string()} - {format % args}\n")


class AgentDroidServer(ThreadingHTTPServer):
    """Threaded HTTP server for AgentDroid cloud API & Web Playground."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        api_key: str | None = None,
        serial: str | None = None,
        artemis_url: str | None = None,
        cors_origin: str = "*",
    ) -> None:
        self.host = host
        self.port = port
        self.api_key = (api_key or os.environ.get("AGENTDROID_API_KEY") or "").strip() or None
        self.serial = serial or os.environ.get("REDROID_ADDR") or "127.0.0.1:5555"
        self.artemis_url = artemis_url or os.environ.get("ARTEMIS_BASE_URL") or "http://127.0.0.1:8000"
        self.cors_origin = cors_origin

        self._adb = AdbDevice(serial=self.serial)
        self._helper = AccessibilityHelperClient(self._adb)

        super().__init__((host, port), AgentDroidRequestHandler)

    def get_adb(self) -> AdbDevice:
        return self._adb

    def get_helper(self) -> AccessibilityHelperClient:
        return self._helper

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        auth_note = "enabled (X-API-Key required)" if self.api_key else "disabled (open access)"
        print(
            f"🚀 [agentdroid:server] AgentDroid Cloud REST API & Web Playground listening at http://{self.host}:{self.port}\n"
            f"   • Device target:    {self.serial}\n"
            f"   • Authentication:   {auth_note}\n"
            f"   • Web Playground:   http://{self.host}:{self.port}/playground\n"
            f"   • REST Health:      http://{self.host}:{self.port}/health\n"
            f"   • Compound Runner:  POST http://{self.host}:{self.port}/api/v1/run",
            file=sys.stderr,
        )
        super().serve_forever(poll_interval=poll_interval)
