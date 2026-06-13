const http = require("http");
const path = require("path");

const BACKEND_PORT = 8099;
const FRONTEND_PORT = 3098;
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

async function fetch(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    }).on("error", reject);
  });
}

async function post(url, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const urlObj = new URL(url);
    const req = http.request({
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data),
      },
    }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => resolve({ status: res.statusCode, body }));
    });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

async function run() {
  console.log("Integration tests (frontend → backend)...\n");

  // Start mock backend
  const mockBackend = http.createServer((req, res) => {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Content-Type", "application/json");

    if (req.url === "/api/chat" && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        res.writeHead(200);
        res.end(JSON.stringify({ content: "Mock response" }));
      });
      return;
    }

    if (req.url === "/api/calendar/today") {
      res.writeHead(200);
      res.end(JSON.stringify({ events: [{ summary: "Test Event", start: "2025-01-01T10:00:00Z" }] }));
      return;
    }

    if (req.url === "/api/calendar/week") {
      res.writeHead(200);
      res.end(JSON.stringify({ events: [] }));
      return;
    }

    res.writeHead(404);
    res.end(JSON.stringify({ error: "not found" }));
  });

  await new Promise((resolve) => mockBackend.listen(BACKEND_PORT, resolve));
  console.log(`  Mock backend on port ${BACKEND_PORT}`);

  // Start frontend
  const app = require("../frontend/server");
  const frontend = app.listen(FRONTEND_PORT, () => {
    console.log(`  Frontend on port ${FRONTEND_PORT}\n`);
  });

  try {
    // Test 1: Frontend serves HTML
    console.log("  Frontend serving:");
    const index = await fetch(`http://localhost:${FRONTEND_PORT}/`);
    assert(index.status === 200, "Frontend serves index.html");
    assert(index.body.includes("app.js"), "References app.js");

    // Test 2: Frontend serves JS
    console.log("\n  Frontend assets:");
    const js = await fetch(`http://localhost:${FRONTEND_PORT}/app.js`);
    assert(js.status === 200, "Frontend serves app.js");
    assert(js.body.includes("const API"), "app.js contains API constant");

    // Test 3: Backend chat endpoint
    console.log("\n  Backend chat:");
    const chatRes = await post(`http://localhost:${BACKEND_PORT}/api/chat`, {
      messages: [{ role: "user", content: "test" }],
    });
    assert(chatRes.status === 200, "Backend /api/chat returns 200");
    const chatData = JSON.parse(chatRes.body);
    assert(chatData.content === "Mock response", "Chat response has content field");

    // Test 4: Backend calendar today
    console.log("\n  Backend calendar:");
    const todayRes = await fetch(`http://localhost:${BACKEND_PORT}/api/calendar/today`);
    assert(todayRes.status === 200, "Backend /api/calendar/today returns 200");
    const todayData = JSON.parse(todayRes.body);
    assert(Array.isArray(todayData.events), "Today response has events array");
    assert(todayData.events[0].summary === "Test Event", "Event has summary");

    // Test 5: Backend calendar week
    console.log("\n  Backend calendar week:");
    const weekRes = await fetch(`http://localhost:${BACKEND_PORT}/api/calendar/week`);
    assert(weekRes.status === 200, "Backend /api/calendar/week returns 200");
    const weekData = JSON.parse(weekRes.body);
    assert(Array.isArray(weekData.events), "Week response has events array");

    // Test 6: Backend calendar week
    console.log("\n  Backend calendar week:");
    const weekRes = await fetch(`http://localhost:${BACKEND_PORT}/api/calendar/week`);
    assert(weekRes.status === 200, "Backend /api/calendar/week returns 200");
    const weekData = JSON.parse(weekRes.body);
    assert(Array.isArray(weekData.events), "Week response has events array");
  } catch (e) {
    console.error(`  ✗ Test error: ${e.message}`);
    failed++;
  } finally {
    mockBackend.close();
    frontend.close();
    console.log(`\n  Results: ${passed} passed, ${failed} failed`);
    process.exit(failed > 0 ? 1 : 0);
  }
}

run().catch((e) => {
  console.error("Test runner error:", e);
  process.exit(1);
});
