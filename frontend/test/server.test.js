const http = require("http");
const path = require("path");
const fs = require("fs");

const PORT = 3099;
const BACKEND_PORT = 8198;
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

async function request(port, pathname) {
  return new Promise((resolve, reject) => {
    http.get(`http://localhost:${port}${pathname}`, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    }).on("error", reject);
  });
}

async function run() {
  // Controllable mock backend — flip `authOk` to test both paths
  let authOk = true;
  const mockBackend = http.createServer((req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/api/auth/me") {
      if (authOk) {
        res.writeHead(200);
        res.end(JSON.stringify({ user: { id: "1", username: "admin" } }));
      } else {
        res.writeHead(401);
        res.end(JSON.stringify({ detail: "Not authenticated" }));
      }
    } else {
      res.writeHead(404);
      res.end(JSON.stringify({ error: "not found" }));
    }
  });

  await new Promise((resolve) => mockBackend.listen(BACKEND_PORT, resolve));

  const originalEnv = process.env.BACKEND_URL;
  process.env.BACKEND_URL = `http://localhost:${BACKEND_PORT}`;

  const app = require("../server");
  const server = app.listen(PORT, () => console.log(`Test server on port ${PORT}\n`));

  console.log("Frontend server tests...\n");

  // Test 1: Authenticated user sees dashboard
  console.log("  Auth gate (authenticated):");
  try {
    authOk = true;
    const res = await request(PORT, "/");
    assert(res.status === 200, "GET / returns 200");
    assert(res.headers["content-type"].includes("html"), "Content-Type is HTML");
    assert(res.body.includes("<title>Qwelio</title>"), "Contains Qwelio title");
    assert(res.body.includes('<script src="/app.js"></script>'), "References app.js");
    assert(res.body.includes('<link rel="stylesheet" href="/style.css">'), "References style.css");
  } catch (e) {
    failed += 5;
    console.error(`  ✗ GET / (authenticated) failed: ${e.message}`);
  }

  // Test 2: Unauthenticated user sees login page
  console.log("\n  Auth gate (unauthenticated):");
  try {
    authOk = false;
    const res = await request(PORT, "/");
    assert(res.status === 200, "GET / returns 200");
    assert(res.headers["content-type"].includes("html"), "Content-Type is HTML");
    assert(res.body.includes("login-form"), "Unauthenticated user sees login page");
    assert(res.body.includes("login.js"), "Login page references login.js");
    assert(!res.body.includes("app.js"), "Login page does NOT reference app.js");
  } catch (e) {
    failed += 5;
    console.error(`  ✗ GET / (unauthenticated) failed: ${e.message}`);
  }

  // Test 3: Backend down → shows login page (safe fallback)
  console.log("\n  Auth gate (backend down):");
  try {
    mockBackend.close();
    await new Promise(r => setTimeout(r, 100));
    const res = await request(PORT, "/");
    assert(res.status === 200, "GET / returns 200 when backend is down");
    assert(res.body.includes("login-form"), "Shows login page when backend unreachable");
  } catch (e) {
    failed += 2;
    console.error(`  ✗ GET / (backend down) failed: ${e.message}`);
  }

  // Restart mock backend for remaining tests
  await new Promise((resolve) => mockBackend.listen(BACKEND_PORT, resolve));
  authOk = true;

  // Test 4: serves CSS
  console.log("\n  Static assets:");
  try {
    const res = await request(PORT, "/style.css");
    assert(res.status === 200, "GET /style.css returns 200");
    assert(res.headers["content-type"].includes("css"), "Content-Type is CSS");
    assert(res.body.includes(".container"), "CSS contains .container rule");
  } catch (e) {
    failed += 3;
    console.error(`  ✗ GET /style.css failed: ${e.message}`);
  }

  // Test 5: serves JS modules
  console.log("\n  JavaScript:");
  try {
    const coreRes = await request(PORT, "/js/app-core.js");
    assert(coreRes.status === 200, "GET /js/app-core.js returns 200");
    assert(coreRes.headers["content-type"].includes("javascript"), "Content-Type is JavaScript");
    assert(coreRes.body.includes("const API"), "Contains API constant");
    assert(coreRes.body.includes("chatHistory"), "Contains chatHistory");
    assert(!coreRes.body.includes("localhost:8000"), "No hardcoded backend URLs");
    const appRes = await request(PORT, "/app.js");
    assert(appRes.status === 200, "GET /app.js returns 200");
    assert(!appRes.body.includes("localhost:8000"), "app.js has no hardcoded backend URLs");
  } catch (e) {
    failed += 4;
    console.error(`  ✗ GET /js/app-core.js failed: ${e.message}`);
  }

  // Test 6: serves login.js
  console.log("\n  Login JS:");
  try {
    const res = await request(PORT, "/login.js");
    assert(res.status === 200, "GET /login.js returns 200");
    assert(!res.body.includes("localhost:8000"), "login.js has no hardcoded backend URLs");
  } catch (e) {
    failed += 2;
    console.error(`  ✗ GET /login.js failed: ${e.message}`);
  }

  // Test 7: 404 for unknown routes
  console.log("\n  Error handling:");
  try {
    const res = await request(PORT, "/nonexistent");
    assert(res.status === 404, "GET /nonexistent returns 404");
  } catch (e) {
    failed++;
    console.error(`  ✗ GET /nonexistent failed: ${e.message}`);
  }

  try {
    // Test 8: XSS safety — scan all JS files
    console.log("\n  Security:");
    const jsDir = path.join(__dirname, "..", "public", "js");
    const jsFiles = fs.readdirSync(jsDir).filter(f => f.endsWith(".js"));
    const allJs = jsFiles.map(f => fs.readFileSync(path.join(jsDir, f), "utf8")).join("\n");
    const innerHTMLLines = allJs.split("\n").filter(l => l.includes("innerHTML ="));
    const safeInnerHtml = innerHTMLLines.every(l => l.includes("DOMPurify") || l.includes('innerHTML = ""'));
    assert(safeInnerHtml, "innerHTML only used for safe rendering (DOMPurify) or clearing");
    assert(allJs.includes("textContent"), "Uses textContent for safe text insertion");
    assert(allJs.includes("createElement"), "Uses createElement for DOM construction");
  } finally {
    server.close();
    mockBackend.close();
    if (originalEnv === undefined) {
      delete process.env.BACKEND_URL;
    } else {
      process.env.BACKEND_URL = originalEnv;
    }
    console.log(`\n  Results: ${passed} passed, ${failed} failed`);
    process.exit(failed > 0 ? 1 : 0);
  }
}

run().catch((e) => {
  console.error("Test runner error:", e);
  process.exit(1);
});
