"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

process.env.PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";

const tests = ["viewer.browser.cjs", "webcodecs.browser.cjs"];
const browsersPath = process.env.PLAYWRIGHT_BROWSERS_PATH;

let browsersPathIsDirectory = false;
if (browsersPath && path.isAbsolute(browsersPath)) {
  try {
    browsersPathIsDirectory = fs.statSync(browsersPath).isDirectory();
  } catch {
    browsersPathIsDirectory = false;
  }
}

if (!browsersPathIsDirectory) {
  console.log(
    JSON.stringify({
      status: "BLOCKED",
      reason: "playwright-browsers-path-invalid",
    }),
  );
  process.exit(2);
}

const results = [];
for (const name of tests) {
  const startedAt = Date.now();
  const child = spawnSync(process.execPath, [name], {
    cwd: __dirname,
    env: process.env,
    stdio: "inherit",
  });
  results.push({
    name,
    exit_code: child.status === null ? 1 : child.status,
    duration_ms: Date.now() - startedAt,
  });
}

const passed = results.every((result) => result.exit_code === 0);
console.log(
  JSON.stringify({
    status: passed ? "PASS" : "FAIL",
    browsers_path: browsersPath,
    tests: results,
  }),
);
process.exit(passed ? 0 : 1);
