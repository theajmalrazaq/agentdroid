/**
 * AgentDroid TypeScript Client SDK.
 *
 * Provides a lightweight HTTP client for communicating with self-hosted
 * AgentDroid instances on any cloud or local server.
 */

export interface AgentDroidClientOptions {
  /** Base URL of the AgentDroid server (e.g. http://your-cloud-ip:8080) */
  endpoint: string;
  /** Optional API Key for authentication (X-API-Key) */
  apiKey?: string;
  /** Request timeout in milliseconds (default: 120000) */
  timeoutMs?: number;
}

export interface RunWorkflowParams {
  open_url?: string;
  install?: string[];
  launch?: string;
  do?: string[];
  assert_text?: string[];
  notifications?: boolean;
  clipboard?: string;
  get_clipboard?: boolean;
  serial?: string;
}

export interface RunWorkflowReport {
  ok: boolean;
  mode: string;
  device: string;
  duration_sec: number;
  installed_apks?: Array<Record<string, unknown>>;
  opened_urls?: Array<Record<string, unknown>>;
  clipboard?: string | null;
  notifications?: Array<Record<string, unknown>>;
  ui_summary?: {
    element_count: number;
    elements: Array<{
      id: number;
      label: string;
      class: string;
      center: [number, number];
    }>;
  };
  errors?: string[];
}

export interface UiDumpResponse {
  ok: boolean;
  element_count: number;
  elements: Array<{
    id: number;
    label: string;
    class: string;
    center: [number, number];
    resource_id?: string;
  }>;
  foreground?: Record<string, unknown>;
}

export class AgentDroidClient {
  readonly endpoint: string;
  readonly apiKey?: string;
  readonly timeoutMs: number;

  constructor(options: AgentDroidClientOptions) {
    this.endpoint = options.endpoint.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 120_000;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const url = `${this.endpoint}${path}`;
    const headers = new Headers(init.headers);

    if (!headers.has("Content-Type") && init.body) {
      headers.set("Content-Type", "application/json");
    }
    if (this.apiKey && !headers.has("X-API-Key")) {
      headers.set("X-API-Key", this.apiKey);
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        ...init,
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(
          `AgentDroid API error (${response.status}): ${text || response.statusText}`
        );
      }

      return (await response.json()) as T;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /** Run a compound single-call Android workflow (install, open url, do, assert) */
  async run(params: RunWorkflowParams): Promise<RunWorkflowReport> {
    return this.request<RunWorkflowReport>("/api/v1/run", {
      method: "POST",
      body: JSON.stringify(params),
    });
  }

  /** Execute one or more sequential semantic UI actions (click, fill, scroll, key) */
  async do(actionOrActions: string | string[]): Promise<Record<string, unknown>> {
    const actions = Array.isArray(actionOrActions)
      ? actionOrActions
      : [actionOrActions];
    return this.request<Record<string, unknown>>("/api/v1/do", {
      method: "POST",
      body: JSON.stringify({ actions }),
    });
  }

  /** Inspect visible interactive elements in ~150 tokens */
  async dumpUI(maxElements = 60): Promise<UiDumpResponse> {
    return this.request<UiDumpResponse>(
      `/api/v1/ui/dump?max_elements=${maxElements}`
    );
  }

  /** Tap screen coordinates (x, y) */
  async tap(x: number, y: number): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/api/v1/ui/tap", {
      method: "POST",
      body: JSON.stringify({ x, y }),
    });
  }

  /** Type text into currently focused field */
  async type(text: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/api/v1/ui/type", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }

  /** Send hardware or global key (HOME, BACK, RECENTS, ENTER) */
  async key(key: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/api/v1/ui/key", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
  }

  /** Open web URL or deep link in Android */
  async openUrl(url: string, pkg?: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/api/v1/device/open-url", {
      method: "POST",
      body: JSON.stringify({ url, package: pkg }),
    });
  }

  /** Read active notifications (OTP / 2FA codes, messages) */
  async getNotifications(includeSystem = false): Promise<Array<Record<string, unknown>>> {
    const res = await this.request<{ notifications: Array<Record<string, unknown>> }>(
      `/api/v1/device/notifications?all=${includeSystem}`
    );
    return res.notifications || [];
  }

  /** Read device clipboard */
  async getClipboard(): Promise<string> {
    const res = await this.request<{ clipboard: string }>("/api/v1/device/clipboard");
    return res.clipboard || "";
  }

  /** Set device clipboard */
  async setClipboard(text: string): Promise<void> {
    await this.request("/api/v1/device/clipboard", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }
}
