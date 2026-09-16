import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

// The Pixel API owns every paid provider. The web app must never hold provider
// credentials, call provider hosts, or expose server routes that could bypass accounting.
const WEB_ROOT = join(__dirname, "..");
const SOURCE_DIRS = ["app", "lib", "types"];
const FORBIDDEN = [
  /api\.openai\.com/,
  /generativelanguage\.googleapis\.com/,
  /tts\.speech\.microsoft\.com/,
  /\bAZURE_SPEECH_[A-Z_]+/,
  /\bGEMINI_API_KEY\b/,
  /\bOPENAI_API_KEY\b/,
  /RTCPeerConnection/
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("provider boundary", () => {
  const files = SOURCE_DIRS.flatMap((dir) => sourceFiles(join(WEB_ROOT, dir)));

  it("scans the web app source", () => {
    expect(files.length).toBeGreaterThan(5);
  });

  it("contains no provider hosts or credentials", () => {
    const violations = files.flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return FORBIDDEN.filter((pattern) => pattern.test(source))
        .map((pattern) => `${relative(WEB_ROOT, file)}: ${pattern}`);
    });
    expect(violations).toEqual([]);
  });

  it("has no server API routes that could call providers directly", () => {
    const routes = files.filter((file) => /[\\/]app[\\/]api[\\/]/.test(file));
    expect(routes.map((file) => relative(WEB_ROOT, file))).toEqual([]);
  });
});
