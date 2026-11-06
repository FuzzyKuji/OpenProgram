const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { resolvePackagedWorker } = require("../main/self-update/packaged-runtime");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "openprogram-runtime-check-"));
try {
  const runtime = path.join(root, "runtime");
  const python = path.join(runtime, "py", "python.exe");
  const pythonw = path.join(runtime, "py", "pythonw.exe");
  const playwright = path.join(runtime, "assets", "playwright");
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.mkdirSync(playwright, { recursive: true });
  fs.writeFileSync(python, "");
  fs.writeFileSync(pythonw, "");
  const capabilities = Object.fromEntries(
    [
      "web",
      "providers",
      "mcp",
      "memory",
      "channels",
      "search",
      "tui.ink",
      "browser.playwright",
    ].map((name) => [name, { present: true, verified: true }]),
  );
  fs.writeFileSync(
    path.join(runtime, "runtime-manifest.json"),
    JSON.stringify({
      schema: 2,
      openprogram: "0.6.1",
      python: "py/python.exe",
      capabilities,
      assets: {
        playwright: "assets/playwright",
      },
    }),
  );
  const launch = resolvePackagedWorker(root, "0.6.1", "win32");
  assert.strictEqual(launch.command, pythonw);
  assert.strictEqual(launch.authCommand, python);
  assert.deepStrictEqual(
    launch.args,
    ["-I", "-B", "-m", "openprogram", "worker", "start"],
  );
  assert.deepStrictEqual(launch.env, {
    PLAYWRIGHT_BROWSERS_PATH: playwright,
  });
  assert.strictEqual(
    resolvePackagedWorker(root, "0.6.1", "linux").command,
    python,
  );

  assert.throws(
    () => resolvePackagedWorker(root, "0.6.2", "win32"),
    /runtime version mismatch/,
  );

  fs.writeFileSync(
    path.join(runtime, "runtime-manifest.json"),
    JSON.stringify({
      schema: 2,
      openprogram: "0.6.1",
      python: "../../usr/bin/python3",
      capabilities,
      assets: {
        playwright: "assets/playwright",
      },
    }),
  );
  assert.throws(
    () => resolvePackagedWorker(root, "0.6.1", "win32"),
    /escapes runtime resources/,
  );
  console.log("packaged runtime checks passed");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
