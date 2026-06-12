const http = require("http");
const path = require("path");
const fs = require("fs");

const PORT = 3099;
let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) {
    passed++;
    console.log(`  ✓ ${msg}`);
  } else {
    failed++;
    console.error(`  ✗ ${msg}`);
  }
}

async function request(pathname) {
  return new Promise((resolve, reject) => {
    http.get(`http://localhost:${PORT}${pathname}`, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    }).on("error", reject);
  });
}

async function run() {
  const app = require("../server");
  const server = app.listen(PORT, () => console.log(`Test server on port ${PORT}\n`));

  console.log("Frontend server tests...\n");

  // Test 1: serves index.html
  console.log("  Serving files:");
  try {
    const res = await request("/");
    assert(res.status === 200, "GET / returns 200");
    assert(res.headers["content-type"].includes("html"), "Content-Type is HTML");
    assert(res.body.includes("<title>Qwelio</title>"), "Contains Qwelio title");
    assert(res.body.includes('<script src="/app.js"></script>'), "References app.js");
    assert(res.body.includes('<link rel="stylesheet" href="/style.css">'), "References style.css");
  } catch (e) {
    failed += 5;
    console.error(`  ✗ GET / failed: ${e.message}`);
  }

  // Test 2: serves CSS
  console.log("\n  Static assets:");
  try {
    const res = await request("/style.css");
    assert(res.status === 200, "GET /style.css returns 200");
    assert(res.headers["content-type"].includes("css"), "Content-Type is CSS");
    assert(res.body.includes(".container"), "CSS contains .container rule");
  } catch (e) {
    failed += 3;
    console.error(`  ✗ GET /style.css failed: ${e.message}`);
  }

  // Test 3: serves JS
  console.log("\n  JavaScript:");
  try {
    const res = await request("/app.js");
    assert(res.status === 200, "GET /app.js returns 200");
    assert(res.headers["content-type"].includes("javascript"), "Content-Type is JavaScript");
    assert(res.body.includes("const API"), "Contains API constant");
    assert(res.body.includes("chatHistory"), "Contains chatHistory");
  } catch (e) {
    failed += 3;
    console.error(`  ✗ GET /app.js failed: ${e.message}`);
  }

  // Test 4: 404 for unknown routes
  console.log("\n  Error handling:");
  try {
    const res = await request("/nonexistent");
    assert(res.status === 404, "GET /nonexistent returns 404");
  } catch (e) {
    failed++;
    console.error(`  ✗ GET /nonexistent failed: ${e.message}`);
  }

  // Test 5: XSS safety - no innerHTML in app.js
  console.log("\n  Security:");
  const appJsPath = path.join(__dirname, "..", "public", "app.js");
  const appJs = fs.readFileSync(appJsPath, "utf8");
  const innerHTMLAssignments = appJs.match(/innerHTML\s*=/g) || [];
  const innerHTMLLines = appJs.split("\n").filter(l => l.includes("innerHTML ="));
  const onlyClearing = innerHTMLLines.every(l => l.includes('innerHTML = ""'));
  assert(onlyClearing, "innerHTML only used for clearing, not injecting data");
  assert(appJs.includes("textContent"), "Uses textContent for safe text insertion");
  assert(appJs.includes("createElement"), "Uses createElement for DOM construction");

  server.close();
  console.log(`\n  Results: ${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((e) => {
  console.error("Test runner error:", e);
  process.exit(1);
});
