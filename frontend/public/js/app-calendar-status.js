/* ============================================================
   Qwelio — Calendar Status: Connection check, auth flow
   ============================================================ */

async function checkCalendarStatus() {
  const statusEl = document.getElementById("calendar-status");
  try {
    const res = await fetch(`${API}/calendar/status`, { credentials: "include" });
    if (res.status === 401) { handleAuthLoss(); return; }
    const data = await res.json();
    if (data.connected) {
      calendarConnected = true;
      statusEl.textContent = "Calendar: connected";
      statusEl.style.color = "var(--color-success)";
      await loadMonthEvents();
      const todayStr = djs().format("YYYY-MM-DD");
      loadDayEvents(todayStr);
    } else {
      calendarConnected = false;
      statusEl.innerHTML = "";
      const btn = document.createElement("button");
      btn.className = "calendar-nav-btn";
      btn.textContent = "Connect Calendar";
      btn.style.color = "var(--color-accent)";
      btn.addEventListener("click", startCalendarAuth);
      statusEl.appendChild(btn);
    }
  } catch (err) {
    qwlog("QW-C002", `checkCalendarStatus: error: ${err.message}`);
  }
}

async function startCalendarAuth() {
  qwlog("QW-F025", "Connect button clicked, fetching /api/calendar/auth");
  try {
    const authRes = await fetch(`${API}/calendar/auth`, { credentials: "include" });
    qwlog("QW-F026", `Connect: auth response status=${authRes.status}`);
    if (authRes.status === 401) { handleAuthLoss(); return; }
    const authData = await authRes.json();
    if (authData.auth_url) {
      qwlog("QW-F027", `Connect: navigating to auth_url`);
      window.location.href = authData.auth_url;
    }
  } catch (err) {
    qwlog("QW-F028", `Connect: error: ${err.message}`);
  }
}
