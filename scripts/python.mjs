#!/usr/bin/env node
// Runs the project's virtualenv Python with the given arguments, on Windows and POSIX.
// Usage: node scripts/python.mjs -m unittest discover -s apps/api/tests
import { spawn } from "node:child_process";
import { venvPython } from "./venv-python.mjs";

const child = spawn(venvPython(), process.argv.slice(2), { stdio: "inherit" });
child.on("error", (error) => {
  console.error(`Could not start ${venvPython()}: ${error.message}. Create the virtualenv in .venv first.`);
  process.exit(1);
});
child.on("exit", (code, signal) => process.exit(signal ? 1 : (code ?? 1)));
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
