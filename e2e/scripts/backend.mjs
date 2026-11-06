// Builds a fresh demo database for the e2e run (the same build as `make demo`), then serves
// the API on 127.0.0.1:8100 and the mock CM platform on :8200, with DEMO_MODE=true.
import { spawn, spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const backend = join(root, "backend");
const python = join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const data = join(root, "e2e", ".data");

function makeWritable(path) {
  // The landing area is read-only by design; loosen it so the old run can be removed.
  if (!existsSync(path)) return;
  chmodSync(path, 0o777);
  if (statSync(path).isDirectory()) for (const entry of readdirSync(path)) makeWritable(join(path, entry));
}

makeWritable(data);
rmSync(data, { recursive: true, force: true });
mkdirSync(data, { recursive: true });

const env = {
  ...process.env,
  APP_ENV: "demo",
  CLOCK_MODE: "fixed",
  DEMO_MODE: "true",
  ANTHROPIC_API_KEY: "", // e2e never calls the model: the panel must fall back gracefully
  JWT_TTL_MINUTES: "10080", // the demo clock moves forward during the script
  DATA_DIR: data,
  DATABASE_URL: `sqlite:///${data.replace(/\\/g, "/")}/demo.db`,
  MOCK_CM_URL: "http://127.0.0.1:8200",
  MOCK_CM_DATABASE_URL: `sqlite:///${data.replace(/\\/g, "/")}/mock_cm.db`,
};

const result = spawnSync(python, ["-m", "app.demo", "build"], { cwd: backend, env, stdio: "inherit" });
if (result.status !== 0) process.exit(result.status ?? 1);

// The mock CM platform the API writes back to.
const mockCm = spawn(
  python,
  ["-m", "uvicorn", "mock_cm.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8200"],
  { cwd: backend, env, stdio: "inherit" },
);
const server = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100"], {
  cwd: backend,
  env,
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.kill();
    mockCm.kill();
  });
}
server.on("exit", (code) => process.exit(code ?? 0));
