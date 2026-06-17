/* ============================================================
   Qwelio — Settings Modal: Timezone, inference, disconnect
   ============================================================ */

let savedSettings = {};

function initSettings() {
  const modal = document.getElementById("settings-modal");
  document.getElementById("settings-btn").addEventListener("click", openSettings);
  document.getElementById("settings-close").addEventListener("click", closeSettings);
  document.getElementById("settings-save").addEventListener("click", saveSettings);
  document.getElementById("settings-disconnect").addEventListener("click", disconnectCalendar);
  document.getElementById("settings-clear-history").addEventListener("click", clearHistory);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeSettings();
  });
}

async function openSettings() {
  const modal = document.getElementById("settings-modal");
  modal.style.display = "flex";
  await loadSettings();
  await loadTimezones();
}

function closeSettings() {
  document.getElementById("settings-modal").style.display = "none";
}

async function loadSettings() {
  try {
    const res = await fetch(`${API}/settings`, { credentials: "include" });
    if (res.status === 401) { handleAuthLoss(); return; }
    const data = await res.json();
    savedSettings = data;
    document.getElementById("settings-model").value = data.model_name || "";
    document.getElementById("settings-temp").value = data.temperature ?? 0.6;
    document.getElementById("settings-timeout").value = data.timeout ?? 30;
    document.getElementById("settings-retries").value = data.max_retries ?? 2;
    document.getElementById("settings-context").value = data.max_context_turns ?? 20;
    document.getElementById("settings-iterations").value = data.max_tool_iterations ?? 5;
    const tzSel = document.getElementById("settings-timezone");
    tzSel.value = data.timezone || "UTC";
  } catch (err) {
    qwlog("QW-S001", `loadSettings: error: ${err.message}`);
  }
}

async function loadTimezones() {
  try {
    const res = await fetch(`${API}/timezones`, { credentials: "include" });
    if (res.status === 401) { handleAuthLoss(); return; }
    const data = await res.json();
    const sel = document.getElementById("settings-timezone");
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    const current = savedSettings.timezone || "UTC";
    data.timezones.forEach(tz => {
      const opt = document.createElement("option");
      opt.value = tz;
      opt.textContent = tz;
      sel.appendChild(opt);
    });
    sel.value = current;
  } catch (err) {
    qwlog("QW-S002", `loadTimezones: error: ${err.message}`);
  }
}

async function saveSettings() {
  const newTz = document.getElementById("settings-timezone").value;
  if (newTz !== (savedSettings.timezone || "UTC")) {
    try {
      const res = await fetch(`${API}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ timezone: newTz }),
      });
      if (res.ok) {
        userTimezone = newTz;
        savedSettings.timezone = newTz;
        initClock();
        initCalendar();
        const todayStr = djs().format("YYYY-MM-DD");
        loadDayEvents(todayStr);
      }
    } catch (err) {
      qwlog("QW-S003", `saveSettings: error: ${err.message}`);
    }
  } else {
    userTimezone = newTz;
    savedSettings.timezone = newTz;
    initClock();
    initCalendar();
    const todayStr = djs().format("YYYY-MM-DD");
    loadDayEvents(todayStr);
  }
  closeSettings();
}

async function disconnectCalendar() {
  if (!confirm("Disconnect your Google Calendar? You'll need to re-authorize to use calendar features.")) return;
  try {
    const res = await fetch(`${API}/calendar/disconnect`, {
      method: "DELETE",
      credentials: "include",
    });
    if (res.ok) {
      calendarConnected = false;
      allMonthEvents = [];
      checkCalendarStatus();
      renderCalendar();
      setPlaceholder(document.getElementById("day-detail-events"), "Calendar disconnected");
    }
  } catch (err) {
    qwlog("QW-S004", `disconnectCalendar: error: ${err.message}`);
  }
}

async function clearHistory() {
  if (!confirm("Clear all chat history? This cannot be undone.")) return;
  try {
    const res = await fetch(`${API}/conversations`, {
      method: "DELETE",
      credentials: "include",
    });
    if (res.ok) {
      chatHistory.length = 0;
      const container = document.getElementById("chat-messages");
      while (container.firstChild) container.removeChild(container.firstChild);
      delete container.dataset.onboarded;
      initOnboarding();
    }
  } catch (err) {
    qwlog("QW-S005", `clearHistory: error: ${err.message}`);
  }
}
