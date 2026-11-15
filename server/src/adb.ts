import { execFile } from "node:child_process";

export interface ExecResult {
  stdout: Buffer;
  stderr: string;
}

/** Thin ADB transport. All device I/O goes through here. */
export class Adb {
  readonly serial: string;
  readonly bin: string;
  private connected = false;

  constructor(serial = "127.0.0.1:5555", bin = process.env.AGENTDROID_ADB ?? "adb") {
    this.serial = serial;
    this.bin = bin;
  }

  private exec(args: string[], timeoutMs = 30_000): Promise<ExecResult> {
    return new Promise((resolve, reject) => {
      execFile(
        this.bin,
        args,
        { encoding: "buffer", maxBuffer: 64 * 1024 * 1024, timeout: timeoutMs },
        (err, stdout, stderr) => {
          if (err) {
            const msg = Buffer.from(stderr ?? "").toString().trim() || err.message;
            reject(new Error(`adb ${args.join(" ")} failed: ${msg}`));
          } else {
            resolve({ stdout: stdout as Buffer, stderr: Buffer.from(stderr ?? "").toString() });
          }
        },
      );
    });
  }

  /** Connect to network devices (host:port) once. */
  async ensureConnected(): Promise<void> {
    if (this.connected) return;
    if (this.serial.includes(":")) {
      await this.exec(["connect", this.serial], 10_000);
    }
    this.connected = true;
  }

  async adb(args: string[], timeoutMs?: number): Promise<Buffer> {
    await this.ensureConnected();
    return (await this.exec(["-s", this.serial, ...args], timeoutMs)).stdout;
  }

  /** Run a command in the device shell; the command string is interpreted by the device shell. */
  async shell(command: string, timeoutMs?: number): Promise<string> {
    return (await this.adb(["shell", command], timeoutMs)).toString("utf8");
  }

  async isOnline(): Promise<boolean> {
    try {
      return (await this.shell("echo ok", 5_000)).trim() === "ok";
    } catch {
      return false;
    }
  }

  async screenshotPng(): Promise<Buffer> {
    return this.adb(["exec-out", "screencap", "-p"], 30_000);
  }

  async push(local: string, remote: string): Promise<void> {
    await this.adb(["push", local, remote], 300_000);
  }

  async install(apkPath: string): Promise<string> {
    return (await this.adb(["install", "-r", "-g", apkPath], 300_000)).toString("utf8").trim();
  }
}

/** Quote a string for safe use as a single device-shell argument. */
export function shq(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}
