const http = require("http");
const { spawn } = require("child_process");
const path = require("path");

const BACKEND_PORT = 8199;
const FRONTEND_PORT = 3199;
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

class CookieClient {
  constructor() {
    this.cookies = {};
  }

  request(method, urlStr, body) {
    return new Promise((resolve, reject) => {
      const url = new URL(urlStr);
      const headers = {
        "Content-Type": "application/json",
        "Content-Length": body ? Buffer.byteLength(body) : 0,
      };

      const domainCookies = this.cookies[url.hostname + ":" + url.port] || [];
      if (domainCookies.length) {
        headers.Cookie = domainCookies.join("; ");
      }

      const req = http.request({
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method,
        headers,
      }, (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          const setCookies = res.headers["set-cookie"];
          if (setCookies) {
            if (!this.cookies[url.hostname + ":" + url.port]) {
              this.cookies[url.hostname + ":" + url.port] = [];
            }
            for (const c of setCookies) {
              const semiIdx = c.indexOf(";");
              const nameValue = (semiIdx === -1 ? c.trim() : c.substring(0, semiIdx).trim());
              const eqIdx = nameValue.indexOf("=");
              if (eqIdx !== -1) {
                const name = nameValue.substring(0, eqIdx);
                this.cookies[url.hostname + ":" + url.port] =
                  this.cookies[url.hostname + ":" + url.port].filter(
                    existing => existing.substring(0, existing.indexOf("=")) !== name
                  );
                this.cookies[url.hostname + ":" + url.port].push(nameValue);
              }
            }
          }

          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: data,
            json: () => JSON.parse(data),
          });
        });
      });
      req.on("error", reject);
      if (body) req.write(body);
      req.end();
    });
  }

  get(url) { return this.request("GET", url); }
  post(url, data) { return this.request("POST", url, JSON.stringify(data)); }
}

async function run() {
  console.log("Integration tests (real frontend → real backend)...\n");

  // Start REAL backend with uvicorn
  const backendProc = spawn("uv", ["run", "uvicorn", "main:app", "--port", String(BACKEND_PORT)], {
    cwd: path.join(__dirname, "..", "backend"),
    env: {
      ...process.env,
      GOOGLE_CLIENT_ID: "test_client_id",
      GOOGLE_CLIENT_SECRET: "test_client_secret",
      GOOGLE_REDIRECT_URI: `http://localhost:${FRONTEND_PORT}/api/calendar/callback`,
      QWEN_API_URL: "http://localhost:9999",
      QWEN_API_KEY: "test_key",
      MODEL_NAME: "test-model",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  // Wait for backend ready
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Backend startup timeout")), 20000);
    backendProc.stdout.on("data", (data) => {
      if (data.toString().includes("Application startup complete")) {
        clearTimeout(timeout);
        resolve();
      }
    });
    backendProc.stderr.on("data", (data) => {
      if (data.toString().includes("Uvicorn running")) {
        clearTimeout(timeout);
        resolve();
      }
    });
  });
  console.log(`  Real backend on port ${BACKEND_PORT}`);

  // Start REAL frontend
  const originalEnv = process.env.BACKEND_URL;
  process.env.BACKEND_URL = `http://localhost:${BACKEND_PORT}`;

  const app = require("../frontend/server");
  const frontend = app.listen(FRONTEND_PORT, () => {
    console.log(`  Real frontend on port ${FRONTEND_PORT}\n`);
  });

  try {
    const client = new CookieClient();

    // === Test 1: Unauthenticated user sees login page ===
    console.log("  Auth gate:");
    const loginPage = await client.get(`http://localhost:${FRONTEND_PORT}/`);
    assert(loginPage.status === 200, "GET / returns 200");
    assert(
      loginPage.body.includes("login") || loginPage.body.includes("Login"),
      "Unauthenticated user sees login page"
    );

    // === Test 2: Login sets session cookie ===
    console.log("\n  Login flow:");
    const loginRes = await client.post(`http://localhost:${FRONTEND_PORT}/api/auth/login`, {
      username: "admin",
      password: "lels1234",
    });
    assert(loginRes.status === 200, "Login returns 200");
    const hasSessionCookie = loginRes.headers["set-cookie"] &&
      loginRes.headers["set-cookie"].some(c => c.includes("session"));
    assert(hasSessionCookie, "Login response sets session cookie");

    // === Test 3: Authenticated user sees dashboard ===
    console.log("\n  Dashboard access:");
    const dashboard = await client.get(`http://localhost:${FRONTEND_PORT}/`);
    assert(dashboard.status === 200, "GET / returns 200 after login");
    assert(
      dashboard.body.includes("app.js"),
      "Authenticated user sees dashboard with app.js"
    );

    // === Test 4: /api/auth/me returns user info ===
    console.log("\n  Session verification:");
    const meRes = await client.get(`http://localhost:${FRONTEND_PORT}/api/auth/me`);
    assert(meRes.status === 200, "/api/auth/me returns 200 with valid session");
    const meData = meRes.json();
    assert(meData.user && meData.user.username === "admin", "Returns correct username");

    // === Test 5: Calendar returns auth_required (no Google Calendar connected) ===
    console.log("\n  Calendar (no Google auth):");
    // Clean up any stale token file so get_service() raises NotAuthenticated
    const fs = require("fs");
    const tokenPath = path.join(__dirname, "..", "backend", ".calendar_token.json");
    const hadToken = fs.existsSync(tokenPath);
    if (hadToken) fs.unlinkSync(tokenPath);
    try {
      const todayRes = await client.get(`http://localhost:${FRONTEND_PORT}/api/calendar/today`);
      assert(todayRes.status === 200, "/api/calendar/today returns 200");
      const todayData = todayRes.json();
      assert(todayData.auth_required === true, "Calendar returns auth_required when not connected");
      assert(typeof todayData.auth_url === "string", "Calendar returns auth_url");
    } finally {
      // Restore token if it existed
      if (!hadToken) {
        try { fs.unlinkSync(tokenPath); } catch (_) { /* ignore */ }
      }
    }

    // === Test 6: Frontend JS uses relative paths ===
    console.log("\n  Frontend code quality:");
    const jsRes = await client.get(`http://localhost:${FRONTEND_PORT}/app.js`);
    assert(jsRes.status === 200, "app.js is served");
    assert(
      !jsRes.body.includes("localhost:8000"),
      "app.js has NO hardcoded backend URLs"
    );
    const coreRes = await client.get(`http://localhost:${FRONTEND_PORT}/js/app-core.js`);
    assert(
      coreRes.body.includes('const API = "/api"'),
      "app-core.js uses relative /api path"
    );

    // === Test 7: Login page JS uses relative paths ===
    const loginJsRes = await client.get(`http://localhost:${FRONTEND_PORT}/login.js`);
    assert(loginJsRes.status === 200, "login.js is served");
    assert(
      !loginJsRes.body.includes("localhost:8000"),
      "login.js has NO hardcoded backend URLs"
    );

    // === Test 8: Static assets work ===
    console.log("\n  Static assets:");
    const cssRes = await client.get(`http://localhost:${FRONTEND_PORT}/css/tokens.css`);
    assert(cssRes.status === 200, "tokens.css is served");

    // === Test 9: Logout clears session ===
    console.log("\n  Logout:");
    const logoutRes = await client.post(`http://localhost:${FRONTEND_PORT}/api/auth/logout`, {});
    assert(logoutRes.status === 200, "Logout returns 200");

    // After logout, / should show login page again
    const afterLogout = await client.get(`http://localhost:${FRONTEND_PORT}/`);
    assert(
      afterLogout.body.includes("login") || afterLogout.body.includes("Login"),
      "After logout, user sees login page again"
    );

    // === Test 10: /api/auth/me fails after logout ===
    const afterLogoutMe = await client.get(`http://localhost:${FRONTEND_PORT}/api/auth/me`);
    assert(afterLogoutMe.status === 401, "/api/auth/me returns 401 after logout");

  } catch (e) {
    console.error(`  ✗ Test error: ${e.message}`);
    console.error(e.stack);
    failed++;
  } finally {
    frontend.close();
    backendProc.kill();
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
