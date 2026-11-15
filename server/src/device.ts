import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { Adb, shq } from "./adb.ts";
import { Security, SecurityError } from "./security.ts";

export interface UiElement {
  id: number;
  label: string;
  class: string;
  resource_id: string;
  clickable: boolean;
  center: [number, number];
}

/** Parse `uiautomator dump` XML into a compact, token-efficient element list. */
export function parseUiXml(xml: string, maxElements = 80): UiElement[] {
  const out: UiElement[] = [];
  const nodeRe = /<node\b([^>]*?)\/?>/g;
  const attr = (s: string, name: string) =>
    new RegExp(`\\b${name}="([^"]*)"`).exec(s)?.[1]
      ?.replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&") ?? "";
  let m: RegExpExecArray | null;
  while ((m = nodeRe.exec(xml)) && out.length < maxElements) {
    const a = m[1];
    const label = attr(a, "text") || attr(a, "content-desc");
    const clickable = attr(a, "clickable") === "true";
    if (!label && !clickable) continue;
    const b = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/.exec(attr(a, "bounds"));
    if (!b) continue;
    const [x1, y1, x2, y2] = b.slice(1).map(Number);
    if (x2 <= x1 || y2 <= y1) continue;
    out.push({
      id: out.length,
      label,
      class: attr(a, "class").split(".").pop() ?? "",
      resource_id: attr(a, "resource-id"),
      clickable,
      center: [Math.round((x1 + x2) / 2), Math.round((y1 + y2) / 2)],
    });
  }
  return out;
}

export function findElement(els: UiElement[], selector: string): UiElement | undefined {
  const idx = /^#(\d+)$/.exec(selector);
  if (idx) return els[Number(idx[1])];
  const s = selector.toLowerCase();
  return (
    els.find((e) => e.label.toLowerCase() === s || e.resource_id === selector || e.resource_id.endsWith(`:id/${selector}`)) ??
    els.find((e) => e.label.toLowerCase().includes(s))
  );
}

export interface DoStep {
  verb: string;
  arg: string;
}

export function parseDoStep(step: string): DoStep {
  const i = step.indexOf(":");
  if (i < 0) throw new SecurityError(`Invalid step (expected verb:arg): ${step}`, 400);
  return { verb: step.slice(0, i).trim().toLowerCase(), arg: step.slice(i + 1) };
}

const KEYS: Record<string, string> = {
  HOME: "KEYCODE_HOME", BACK: "KEYCODE_BACK", ENTER: "KEYCODE_ENTER", TAB: "KEYCODE_TAB",
  RECENTS: "KEYCODE_APP_SWITCH", MENU: "KEYCODE_MENU", POWER: "KEYCODE_POWER",
  DELETE: "KEYCODE_DEL", UP: "KEYCODE_DPAD_UP", DOWN: "KEYCODE_DPAD_DOWN",
  LEFT: "KEYCODE_DPAD_LEFT", RIGHT: "KEYCODE_DPAD_RIGHT", VOLUME_UP: "KEYCODE_VOLUME_UP", VOLUME_DOWN: "KEYCODE_VOLUME_DOWN",
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** High-level device operations used by the HTTP API and the AI SDK tools. */
export class Device {
  readonly adb: Adb;
  readonly security: Security;
  constructor(adb: Adb, security: Security) {
    this.adb = adb;
    this.security = security;
  }

  async dumpUi(maxElements = 80): Promise<{ element_count: number; elements: UiElement[]; foreground: string }> {
    const xml = await this.adb.shell("uiautomator dump /dev/tty 2>/dev/null || (uiautomator dump /sdcard/.ad.xml >/dev/null && cat /sdcard/.ad.xml)", 20_000);
    const elements = parseUiXml(xml, maxElements);
    const foreground = await this.foregroundPackage();
    return { element_count: elements.length, elements, foreground };
  }

  async foregroundPackage(): Promise<string> {
    const out = await this.adb.shell("dumpsys window | grep -m1 mCurrentFocus").catch(() => "");
    return /([\w.]+)\/[\w.$]+/.exec(out)?.[1] ?? "";
  }

  tap(x: number, y: number) {
    return this.adb.shell(`input tap ${Math.round(x)} ${Math.round(y)}`);
  }

  async type(text: string) {
    // `input text` needs %s for spaces; quote for the device shell.
    await this.adb.shell(`input text ${shq(text.replace(/ /g, "%s"))}`);
  }

  async key(name: string) {
    const code = KEYS[name.toUpperCase()] ?? (/^KEYCODE_\w+$/.test(name) ? name : null);
    if (!code) throw new SecurityError(`Unknown key: ${name}`, 400);
    await this.adb.shell(`input keyevent ${code}`);
  }

  async scroll(direction: "down" | "up") {
    const [from, to] = direction === "down" ? [1700, 600] : [600, 1700];
    await this.adb.shell(`input swipe 540 ${from} 540 ${to} 300`);
  }

  async click(selector: string) {
    const { elements } = await this.dumpUi(150);
    const el = findElement(elements, selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    await this.tap(...el.center);
    return el;
  }

  async scrollTo(text: string, maxScrolls = 8) {
    for (let i = 0; i <= maxScrolls; i++) {
      const { elements } = await this.dumpUi(150);
      const el = findElement(elements, text);
      if (el) return el;
      await this.scroll("down");
      await sleep(250);
    }
    throw new Error(`Text not found after scrolling: ${text}`);
  }

  async openUrl(raw: string) {
    const url = await this.security.validateUrl(raw);
    await this.adb.shell(`am start -a android.intent.action.VIEW -d ${shq(url.toString())}`);
    return { url: url.toString() };
  }

  async launch(pkg: string) {
    if (!/^[\w.]+$/.test(pkg)) throw new SecurityError(`Invalid package: ${pkg}`, 400);
    await this.adb.shell(`monkey -p ${pkg} -c android.intent.category.LAUNCHER 1`);
  }

  async listApps(): Promise<string[]> {
    const out = await this.adb.shell("pm list packages -3");
    return out.split("\n").map((l) => l.replace("package:", "").trim()).filter(Boolean);
  }

  async notifications(): Promise<Array<{ package: string; title: string; text: string }>> {
    const out = await this.adb.shell("dumpsys notification --noredact");
    const res: Array<{ package: string; title: string; text: string }> = [];
    for (const rec of out.split(/\n\s*NotificationRecord/).slice(1)) {
      const pkg = /pkg=([\w.]+)/.exec(rec)?.[1] ?? "";
      const title = /android\.title=(?:String \()?(.*?)\)?\s*$/m.exec(rec)?.[1] ?? "";
      const text = /android\.text=(?:String \()?(.*?)\)?\s*$/m.exec(rec)?.[1] ?? "";
      if (title || text) res.push({ package: pkg, title, text });
    }
    return res;
  }

  /** Execute one semantic step: click, fill, scroll, scroll-to, key, tap, type, sleep. */
  async doStep(step: string): Promise<Record<string, unknown>> {
    const { verb, arg } = parseDoStep(step);
    switch (verb) {
      case "click": return { step, element: await this.click(arg) };
      case "fill": {
        const eq = arg.indexOf("=");
        if (eq < 0) throw new SecurityError("fill needs selector=text", 400);
        const el = await this.click(arg.slice(0, eq));
        await sleep(300);
        await this.type(arg.slice(eq + 1));
        return { step, element: el };
      }
      case "scroll": await this.scroll(arg === "up" ? "up" : "down"); return { step };
      case "scroll-to": return { step, element: await this.scrollTo(arg) };
      case "key": await this.key(arg); return { step };
      case "tap": {
        const [x, y] = arg.split(",").map(Number);
        if (!Number.isFinite(x) || !Number.isFinite(y)) throw new SecurityError("tap needs x,y", 400);
        await this.tap(x, y); return { step };
      }
      case "type": await this.type(arg); return { step };
      case "sleep": await sleep(Math.min(Number(arg) || 1, 30) * 1000); return { step };
      default: throw new SecurityError(`Unknown verb '${verb}' (shell steps are not supported)`, 400);
    }
  }

  /** Download over HTTP(S), re-validating every redirect hop against SSRF rules. */
  private async download(raw: string, maxBytes = 300 * 1024 * 1024): Promise<Buffer> {
    let url = (await this.security.validateUrl(raw)).toString();
    for (let hop = 0; hop < 5; hop++) {
      const res = await fetch(url, { redirect: "manual" });
      if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
        url = (await this.security.validateUrl(new URL(res.headers.get("location")!, url).toString())).toString();
        continue;
      }
      if (!res.ok) throw new Error(`Download failed (${res.status}): ${url}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length > maxBytes) throw new Error("APK too large");
      return buf;
    }
    throw new Error("Too many redirects");
  }

  /** Install from `fdroid:<package>`, an https URL, or a file inside the data directory. */
  async installApp(source: string): Promise<{ source: string; result: string }> {
    const dir = await mkdtemp(path.join(tmpdir(), "agentdroid-"));
    try {
      let apk: string;
      if (source.startsWith("fdroid:")) {
        const pkg = source.slice(7);
        if (!/^[\w.]+$/.test(pkg)) throw new SecurityError(`Invalid package: ${pkg}`, 400);
        const meta = JSON.parse((await this.download(`https://f-droid.org/api/v1/packages/${pkg}`)).toString());
        const code = meta.suggestedVersionCode ?? meta.packages?.[0]?.versionCode;
        if (!code) throw new Error(`F-Droid has no build for ${pkg}`);
        apk = path.join(dir, "app.apk");
        await writeFile(apk, await this.download(`https://f-droid.org/repo/${pkg}_${code}.apk`));
      } else if (/^https?:\/\//.test(source)) {
        apk = path.join(dir, "app.apk");
        await writeFile(apk, await this.download(source));
      } else {
        apk = this.security.resolveDataPath(source);
      }
      return { source, result: await this.adb.install(apk) };
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  }
}
