import http from "node:http";
import { Adb } from "./adb.ts";
import { Device } from "./device.ts";
import { Security, SecurityError, safeEqual, securityFromEnv, type SecurityOptions } from "./security.ts";

export interface ServerOptions {
  host?: string;
  port?: number;
  apiKey?: string;
  serial?: string;
  /** Allow binding a non-loopback address with no API key. Dangerous. */
  insecure?: boolean;
  /** Trust X-Forwarded-For for rate limiting (only behind your own proxy). */
  trustProxy?: boolean;
  /** Allowed CORS origin; omit to send no CORS headers. */
  corsOrigin?: string;
  security?: Partial<SecurityOptions>;
}

const isLoopback = (h: string) => h === "127.0.0.1" || h === "::1" || h === "localhost";

export interface RunRequest {
  open_url?: string;
  install?: string[];
  launch?: string;
  do?: string[];
  assert_text?: string[];
  notifications?: boolean;
}

export class AgentDroidServer {
  readonly device: Device;
  readonly security: Security;
  readonly server: http.Server;
  private readonly host: string;
  private readonly port: number;
  private readonly apiKey?: string;
  private readonly trustProxy: boolean;
  private readonly corsOrigin?: string;
  private lock: Promise<unknown> = Promise.resolve();

  constructor(opts: ServerOptions = {}) {
    this.host = opts.host ?? "127.0.0.1";
    this.port = opts.port ?? 8080;
    this.apiKey = opts.apiKey || undefined;
    this.trustProxy = opts.trustProxy ?? false;
    this.corsOrigin = opts.corsOrigin;
    if (!this.apiKey && !isLoopback(this.host) && !opts.insecure) {
      throw new Error(
        `Refusing to listen on ${this.host} without AGENTDROID_API_KEY. Set a key (or AGENTDROID_INSECURE=true to override).`,
      );
    }
    if (this.apiKey && (this.apiKey.length < 16 || this.apiKey.startsWith("change-me"))) {
      throw new Error("AGENTDROID_API_KEY is too weak: use at least 16 random characters (e.g. openssl rand -hex 24).");
    }
    this.security = new Security({ ...securityFromEnv(), ...opts.security });
    this.device = new Device(new Adb(opts.serial), this.security);
    this.server = http.createServer((req, res) => void this.handle(req, res));
  }

  listen(): Promise<number> {
    return new Promise((resolve) =>
      this.server.listen(this.port, this.host, () => resolve((this.server.address() as { port: number }).port)),
    );
  }

  close(): Promise<void> {
    return new Promise((resolve) => this.server.close(() => resolve()));
  }

  /** The phone is a single shared resource: serialize device operations. */
  private withLock<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.lock.then(fn, fn);
    this.lock = run.catch(() => undefined);
    return run;
  }

  private send(res: http.ServerResponse, status: number, body: unknown, type = "application/json") {
    const data = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
    res.writeHead(status, { "Content-Type": type, "Content-Length": data.length, "Cache-Control": "no-store" });
    res.end(data);
  }

  private authorized(req: http.IncomingMessage): boolean {
    if (!this.apiKey) return true;
    const bearer = /^Bearer (.+)$/.exec(req.headers.authorization ?? "")?.[1];
    const key = (req.headers["x-api-key"] as string | undefined) ?? bearer ?? "";
    return safeEqual(key, this.apiKey);
  }

  private clientId(req: http.IncomingMessage): string {
    if (this.trustProxy) {
      const xff = (req.headers["x-forwarded-for"] as string | undefined)?.split(",")[0]?.trim();
      if (xff) return xff;
    }
    return req.socket.remoteAddress ?? "unknown";
  }

  private async readJson(req: http.IncomingMessage): Promise<any> {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const c of req) {
      size += (c as Buffer).length;
      if (size > this.security.opts.maxBodyBytes) throw new SecurityError("Request body too large", 413);
      chunks.push(c as Buffer);
    }
    if (size === 0) return {};
    try {
      return JSON.parse(Buffer.concat(chunks).toString("utf8"));
    } catch {
      throw new SecurityError("Invalid JSON body", 400);
    }
  }

  async run(r: RunRequest) {
    const started = Date.now();
    const report: Record<string, unknown> = { ok: true, device: this.device.adb.serial };
    const errors: string[] = [];
    const step = async (name: string, fn: () => Promise<unknown>) => {
      if (errors.length) return;
      try { return await fn(); } catch (e) { errors.push(`${name}: ${(e as Error).message}`); }
    };
    if (r.install?.length) {
      report.installed = [];
      for (const src of r.install) await step(`install ${src}`, async () => (report.installed as unknown[]).push(await this.device.installApp(src)));
    }
    if (r.open_url) await step("open_url", async () => (report.opened = await this.device.openUrl(r.open_url!)));
    if (r.launch) await step("launch", () => this.device.launch(r.launch!));
    if (r.do?.length) {
      report.steps = [];
      for (const s of r.do) await step(s, async () => (report.steps as unknown[]).push(await this.device.doStep(s)));
    }
    if (r.notifications) await step("notifications", async () => (report.notifications = await this.device.notifications()));
    const ui = await this.device.dumpUi().catch(() => null);
    if (ui) report.ui = ui;
    if (r.assert_text?.length) {
      const text = (ui?.elements ?? []).map((e) => e.label.toLowerCase()).join("\n");
      report.assertions = r.assert_text.map((t) => ({ text: t, found: text.includes(t.toLowerCase()) }));
      for (const a of report.assertions as Array<{ text: string; found: boolean }>) {
        if (!a.found) errors.push(`assert_text failed: ${a.text}`);
      }
    }
    report.ok = errors.length === 0;
    if (errors.length) report.errors = errors;
    report.duration_sec = (Date.now() - started) / 1000;
    return report;
  }

  private async route(req: http.IncomingMessage, res: http.ServerResponse, url: URL) {
    const key = `${req.method} ${url.pathname.replace(/\/$/, "")}`;
    const dev = this.device;
    const locked = <T>(fn: () => Promise<T>) => this.withLock(fn);

    if (key === "GET /health" || key === "GET /api/v1/health") {
      return this.send(res, 200, { ok: true, device_online: await dev.adb.isOnline(), device: dev.adb.serial });
    }
    if (!this.authorized(req)) return this.send(res, 401, { ok: false, error: "Unauthorized" });

    const body = req.method === "POST" ? await this.readJson(req) : {};
    switch (key) {
      case "POST /api/v1/run": return this.send(res, 200, await locked(() => this.run(body)));
      case "POST /api/v1/do": {
        const steps: string[] = body.steps ?? [];
        if (!Array.isArray(steps) || steps.length === 0) throw new SecurityError("steps[] required", 400);
        return this.send(res, 200, { ok: true, results: await locked(async () => { const o = []; for (const s of steps) o.push(await dev.doStep(s)); return o; }) });
      }
      case "GET /api/v1/ui/dump": return this.send(res, 200, { ok: true, ...(await locked(() => dev.dumpUi(Number(url.searchParams.get("max")) || 80))) });
      case "POST /api/v1/ui/tap": await locked(() => dev.tap(Number(body.x), Number(body.y))); return this.send(res, 200, { ok: true });
      case "POST /api/v1/ui/type": await locked(() => dev.type(String(body.text ?? ""))); return this.send(res, 200, { ok: true });
      case "POST /api/v1/ui/key": await locked(() => dev.key(String(body.key ?? ""))); return this.send(res, 200, { ok: true });
      case "GET /api/v1/ui/screenshot": {
        const png = await locked(() => dev.adb.screenshotPng());
        return url.searchParams.get("format") === "base64"
          ? this.send(res, 200, { ok: true, mime: "image/png", data: png.toString("base64") })
          : this.send(res, 200, png, "image/png");
      }
      case "GET /api/v1/device/notifications": return this.send(res, 200, { ok: true, notifications: await locked(() => dev.notifications()) });
      case "POST /api/v1/device/open-url": return this.send(res, 200, { ok: true, ...(await locked(() => dev.openUrl(String(body.url ?? "")))) });
      case "GET /api/v1/apps": return this.send(res, 200, { ok: true, apps: await locked(() => dev.listApps()) });
      case "POST /api/v1/app/install": return this.send(res, 200, { ok: true, ...(await locked(() => dev.installApp(String(body.source ?? "")))) });
      default: return this.send(res, 404, { ok: false, error: "Not found" });
    }
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse) {
    try {
      if (this.corsOrigin) {
        res.setHeader("Access-Control-Allow-Origin", this.corsOrigin);
        res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key");
        res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      }
      if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }
      this.security.rateLimit(this.clientId(req));
      await this.route(req, res, new URL(req.url ?? "/", "http://localhost"));
    } catch (e) {
      const status = e instanceof SecurityError ? e.status : 500;
      this.send(res, status, { ok: false, error: (e as Error).message });
    }
  }
}
