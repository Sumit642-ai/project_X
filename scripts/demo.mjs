// `make demo`: rebuild the demo database from scratch, then start the API, the mock CM platform
// and the frontend with DEMO_MODE=true and the clock frozen at Mon 9 Nov 2026 08:00 New York.
// Ctrl+C stops everything. Synthetic data only.
import { spawn, spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const started = Date.now();
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const python = join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const data = join(root, "data", "demo");
const slash = (p) => p.replace(/\\/g, "/");
const API_PORT = process.env.DEMO_API_PORT ?? "8000";
const CM_PORT = process.env.DEMO_CM_PORT ?? "8200";

function makeWritable(path) {
  // The landing area is read-only by design; loosen it so the previous demo can be dropped.
  if (!existsSync(path)) return;
  chmodSync(path, 0o777);
  if (statSync(path).isDirectory()) for (const entry of readdirSync(path)) makeWritable(join(path, entry));
}

makeWritable(data);
rmSync(data, { recursive: true, force: true }); // drops the database, the mock CM and all state
mkdirSync(data, { recursive: true });

const env = {
  ...process.env,
  APP_ENV: "demo",
  DEMO_MODE: "true",
  CLOCK_MODE: "fixed",
  DATA_DIR: data,
  DATABASE_URL: `sqlite:///${slash(data)}/demo.db`,
  MOCK_CM_URL: `http://127.0.0.1:${CM_PORT}`,
  MOCK_CM_DATABASE_URL: `sqlite:///${slash(data)}/mock_cm.db`,
  JWT_TTL_MINUTES: "10080", // the demo clock jumps to Tuesday; keep the presenter signed in
};

const built = spawnSync(python, ["-m", "app.demo", "build"], { cwd: backend, env, stdio: "inherit" });
if (built.status !== 0) process.exit(built.status ?? 1);

const children = [
  spawn(python, ["-m", "uvicorn", "mock_cm.app:create_app", "--factory", "--host", "127.0.0.1", "--port", CM_PORT], {
    cwd: backend,
    env,
    stdio: ["ignore", "ignore", "inherit"],
  }),
  spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", API_PORT], {
    cwd: backend,
    env,
    stdio: ["ignore", "ignore", "inherit"],
  }),
  // One command string: npm is a .cmd script on Windows, so it needs a shell.
  spawn("npm run dev -- --host 127.0.0.1", {
    cwd: join(root, "frontend"),
    env: { ...env, VITE_API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
    stdio: ["ignore", "pipe", "inherit"],
    shell: true,
  }),
];
const stop = () => {
  for (const child of children) {
    // On Windows, kill() stops only the shell, not the Vite or uvicorn process under it.
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill();
  }
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);

async function up(url) {
  for (let i = 0; i < 600; i += 1) {
    try {
      if ((await fetch(url)).ok) return true;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

let frontendUrl = null;
children[2].stdout.on("data", (chunk) => {
  const match = /Local:\s+(http:\/\/\S+)/.exec(chunk.toString().replace(/\x1b\[[0-9;]*m/g, ""));
  if (match && !frontendUrl) frontendUrl = match[1];
});

const ok = (await up(`http://127.0.0.1:${CM_PORT}/health`)) && (await up(`http://127.0.0.1:${API_PORT}/health`));
while (ok && !frontendUrl) await new Promise((r) => setTimeout(r, 200));
if (!ok || !(await up(frontendUrl))) {
  console.error("Demo failed to start.");
  stop();
}
const seconds = ((Date.now() - started) / 1000).toFixed(1);
console.log(`\nDemo ready in ${seconds} s (clock frozen at Mon 9 Nov 2026 08:00 America/New_York).`);
console.log(`  Open:            ${frontendUrl}demo/old-way  (then sign in as Maria)`);
console.log(`  Operator panel:  ${frontendUrl}demo-admin`);
console.log(`  API:             http://127.0.0.1:${API_PORT}/docs   Mock CM: http://127.0.0.1:${CM_PORT}/health`);
console.log("  Script:          docs/DEMO.md      Ctrl+C stops everything.");
