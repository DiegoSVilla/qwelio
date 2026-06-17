const { test, expect } = require("@playwright/test");
const { spawn } = require("child_process");
const path = require("path");

const BACKEND_PORT = 8201;
const FRONTEND_PORT = 3201;

let backendProc;
let frontendApp;

test.beforeAll(async () => {
  const uvPath = process.env.UV_PATH || "/home/beestorm/.local/bin/uv";
  backendProc = spawn(uvPath, ["run", "uvicorn", "main:app", "--port", String(BACKEND_PORT)], {
    cwd: path.join(__dirname, "..", "backend"),
    env: {
      ...process.env,
      PATH: process.env.PATH + ":/home/beestorm/.local/bin",
      GOOGLE_CLIENT_ID: "test_client_id",
      GOOGLE_CLIENT_SECRET: "test_client_secret",
      GOOGLE_REDIRECT_URI: `http://localhost:${FRONTEND_PORT}/api/calendar/callback`,
      QWEN_API_URL: "http://localhost:9999",
      QWEN_API_KEY: "test_key",
      MODEL_NAME: "test-model",
    },
    stdio: "pipe",
  });

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Backend startup timeout")), 30000);
    backendProc.stdout.on("data", (data) => {
      if (data.toString().includes("Application startup complete") || data.toString().includes("Uvicorn running")) {
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

  process.env.BACKEND_URL = `http://localhost:${BACKEND_PORT}`;
  const app = require("../frontend/server");
  const server = app.listen(FRONTEND_PORT);
  frontendApp = server;

  globalThis.__backendProc = backendProc;
});

test.afterAll(async () => {
  if (frontendApp) frontendApp.close();
  if (globalThis.__backendProc) globalThis.__backendProc.kill();
  delete process.env.BACKEND_URL;
});

test.describe("Chat layout", () => {
  test("chat panel does not grow with messages — input stays visible", async ({ page }) => {
    await page.goto(`http://localhost:${FRONTEND_PORT}`);

    // Login
    await page.locator('input[name="username"]').fill("admin");
    await page.locator('input[name="password"]').fill("lels1234");
    await page.locator('button[type="submit"]').click();
    await page.waitForSelector("#app-root");

    const chatPanel = page.locator("#chat-messages");
    const chatInput = page.locator("#chat-input");
    const chatForm = page.locator("#chat-form");

    // Measure panel height with no messages
    const emptyHeight = await chatPanel.boundingBox();
    expect(emptyHeight).toBeTruthy();

    // Add 100 messages via JS to simulate long chat
    await page.evaluate(() => {
      const container = document.getElementById("chat-messages");
      for (let i = 0; i < 100; i++) {
        const div = document.createElement("div");
        div.className = "chat-message assistant";
        const prefix = document.createElement("span");
        prefix.className = "msg-prefix";
        prefix.textContent = "Q> ";
        div.appendChild(prefix);
        const content = document.createElement("span");
        content.className = "msg-content";
        content.textContent = `Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Message ${i + 1}.`;
        div.appendChild(content);
        container.appendChild(div);
      }
    });

    await page.waitForTimeout(100);

    // Chat panel height should not have grown
    const filledHeight = await chatPanel.boundingBox();
    expect(filledHeight).toBeTruthy();

    // Panel height should stay the same (within 2px tolerance for rounding)
    expect(Math.abs(filledHeight.height - emptyHeight.height)).toBeLessThan(2);

    // Input and form should still be visible in viewport
    const inputBox = await chatInput.boundingBox();
    const formBox = await chatForm.boundingBox();
    expect(inputBox).toBeTruthy();
    expect(formBox).toBeTruthy();

    // Input should be within the viewport
    const viewport = page.viewportSize();
    expect(inputBox.y + inputBox.height).toBeLessThan(viewport.height);
  });
});
