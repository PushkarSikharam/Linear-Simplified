import { join } from "node:path";

/** Path to the project's virtualenv interpreter for the current platform. */
export function venvPython(root = process.cwd()) {
  return process.platform === "win32"
    ? join(root, ".venv", "Scripts", "python.exe")
    : join(root, ".venv", "bin", "python");
}
