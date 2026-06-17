/* ============================================================
   Qwelio — Core: API, Auth, Logging, DOM Helpers
   ============================================================ */
const API = "/api";
const chatHistory = [];
let chatLoading = false;
let calendarConnected = false;
let todayInterval = null;
let weekInterval = null;
let authLossHandled = false;
let userTimezone = "UTC";
let allMonthEvents = [];

function qwlog(tag, msg) {
  console.log(`[${tag}] ${msg}`);
}

function tzOffset() {
  if (userTimezone === "UTC") return 0;
  const m = userTimezone.match(/^UTC([+-])(\d{1,2})$/);
  return m ? (m[1] === "+" ? 1 : -1) * parseInt(m[2], 10) : 0;
}

function djs(offset) {
  return dayjs().utcOffset(offset || tzOffset());
}

function djsTz(dateStr, offset) {
  const o = offset || tzOffset();
  // If the string has no timezone info (date-only or naive datetime),
  // parse it as local time in the user's offset — not UTC.
  // If it has explicit offset (e.g. from Google API), parse as UTC then shift.
  if (/[+-]\d{2}:\d{2}$/.test(dateStr) || dateStr.endsWith("Z")) {
    return dayjs.utc(dateStr).utcOffset(o);
  }
  return dayjs(dateStr).utcOffset(o);
}

function handleAuthLoss() {
  if (authLossHandled) return;
  authLossHandled = true;
  qwlog("QW-F010", "handleAuthLoss: clearing intervals and redirecting to /login");
  if (todayInterval) clearInterval(todayInterval);
  if (weekInterval) clearInterval(weekInterval);
  todayInterval = weekInterval = null;
  window.location.replace("/login");
}

async function checkAuth() {
  qwlog("QW-F001", "checkAuth: fetching /api/auth/me");
  try {
    const res = await fetch(`${API}/auth/me`, { credentials: "include" });
    qwlog("QW-F002", `checkAuth: status=${res.ok ? "ok" : "failed"} (${res.status})`);
    if (!res.ok) {
      qwlog("QW-F003", "checkAuth: redirecting to /login (auth failed)");
      window.location.replace("/login");
      return false;
    }
    const data = await res.json();
    userTimezone = data.timezone || "UTC";
    dayjs.tz.guess();
  } catch (err) {
    qwlog("QW-F003", `checkAuth: redirecting to /login (error: ${err.message})`);
    window.location.replace("/login");
    return false;
  }
  qwlog("QW-F004", "checkAuth: auth OK, showing app");
  document.getElementById("loading-overlay").style.display = "none";
  document.getElementById("app-root").classList.remove("app-hidden");
  return true;
}

async function logout() {
  await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
  window.location.href = "/";
}

function createEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
}

function setPlaceholder(container, text) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const p = createEl("p", "placeholder", text);
  container.appendChild(p);
}
