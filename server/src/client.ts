export interface ClientOptions {
  endpoint: string;
  apiKey?: string;
  timeoutMs?: number;
}

/** Minimal typed HTTP client for an AgentDroid server. */
export class AgentDroidClient {
  private readonly opts: ClientOptions;
  constructor(opts: ClientOptions) {
    this.opts = opts;
  }

  async request<T = any>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const res = await fetch(this.opts.endpoint.replace(/\/$/, "") + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(this.opts.apiKey ? { "X-API-Key": this.opts.apiKey } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(this.opts.timeoutMs ?? 120_000),
    });
    const json = (await res.json()) as any;
    if (!res.ok) throw new Error(json?.error ?? `HTTP ${res.status}`);
    return json as T;
  }

  run(req: Record<string, unknown>) { return this.request("POST", "/api/v1/run", req); }
  do(steps: string[]) { return this.request("POST", "/api/v1/do", { steps }); }
  ui(max = 80) { return this.request("GET", `/api/v1/ui/dump?max=${max}`); }
  notifications() { return this.request("GET", "/api/v1/device/notifications"); }
  openUrl(url: string) { return this.request("POST", "/api/v1/device/open-url", { url }); }
  install(source: string) { return this.request("POST", "/api/v1/app/install", { source }); }
  screenshotBase64() { return this.request("GET", "/api/v1/ui/screenshot?format=base64"); }
}
