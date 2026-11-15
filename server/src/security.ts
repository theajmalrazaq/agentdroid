import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { timingSafeEqual, createHash } from "node:crypto";
import path from "node:path";

export class SecurityError extends Error {
  status: number;
  constructor(message: string, status = 403) {
    super(message);
    this.status = status;
  }
}

const ALLOWED_SCHEMES = new Set(["http:", "https:", "market:", "geo:", "tel:", "mailto:"]);
const BLOCKED_HOSTS = new Set(["metadata.google.internal", "metadata", "localhost"]);

/** Constant-time string comparison (hashes first so lengths don't leak). */
export function safeEqual(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

export function isPrivateIp(ip: string): boolean {
  if (ip.startsWith("::ffff:")) ip = ip.slice(7);
  if (isIP(ip) === 4) {
    const [a, b] = ip.split(".").map(Number);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) ||
      a >= 224
    );
  }
  const l = ip.toLowerCase();
  return l === "::1" || l === "::" || l.startsWith("fe80") || l.startsWith("fc") || l.startsWith("fd");
}

export interface SecurityOptions {
  allowPrivateNetworks: boolean;
  rateLimitRpm: number;
  /** Directory that host-side file reads/writes are confined to. */
  dataDir: string;
  maxBodyBytes: number;
}

export function securityFromEnv(env = process.env): SecurityOptions {
  return {
    allowPrivateNetworks: env.AGENTDROID_ALLOW_PRIVATE_NETWORKS === "true",
    rateLimitRpm: Number(env.AGENTDROID_RATE_LIMIT_RPM ?? 120),
    dataDir: path.resolve(env.AGENTDROID_DATA_DIR ?? "./data"),
    maxBodyBytes: Number(env.AGENTDROID_MAX_BODY_BYTES ?? 1_000_000),
  };
}

export class Security {
  private hits = new Map<string, number[]>();
  readonly opts: SecurityOptions;
  constructor(opts: SecurityOptions) {
    this.opts = opts;
  }

  /**
   * Validate a URL that the server (or the device) will fetch.
   * Resolves DNS and rejects any private/link-local/metadata address.
   */
  async validateUrl(raw: string): Promise<URL> {
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      throw new SecurityError(`Invalid URL: ${raw}`, 400);
    }
    if (!ALLOWED_SCHEMES.has(url.protocol)) {
      throw new SecurityError(`URL scheme not allowed: ${url.protocol}`);
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return url;
    if (this.opts.allowPrivateNetworks) return url;

    const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (BLOCKED_HOSTS.has(host)) throw new SecurityError(`Host blocked: ${host}`);
    const addrs = isIP(host)
      ? [host]
      : (await lookup(host, { all: true }).catch(() => [])).map((r) => r.address);
    if (addrs.length === 0) throw new SecurityError(`Cannot resolve host: ${host}`, 400);
    for (const addr of addrs) {
      if (isPrivateIp(addr)) throw new SecurityError(`Private or metadata address blocked: ${host} -> ${addr}`);
    }
    return url;
  }

  /** Confine host paths to the data directory (allowlist, not blocklist). */
  resolveDataPath(p: string): string {
    const full = path.resolve(this.opts.dataDir, p);
    const rel = path.relative(this.opts.dataDir, full);
    if (rel.startsWith("..") || path.isAbsolute(rel)) {
      throw new SecurityError(`Path outside data directory (${this.opts.dataDir}): ${p}`);
    }
    return full;
  }

  rateLimit(clientId: string, now = Date.now()): void {
    const windowStart = now - 60_000;
    const hits = (this.hits.get(clientId) ?? []).filter((t) => t > windowStart);
    if (hits.length >= this.opts.rateLimitRpm) {
      this.hits.set(clientId, hits);
      throw new SecurityError("Rate limit exceeded", 429);
    }
    hits.push(now);
    this.hits.set(clientId, hits);
    if (this.hits.size > 10_000) this.hits.clear();
  }
}
