const API = "http://localhost:8000/api";
const chatHistory = [];
let chatLoading = false;
let calendarConnected = false;

function checkAuth() {
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
  if (text !== undefined) el.textContent = text;
  return el;
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function createEventEl(e, showDate) {
  const div = createEl("div", "event");

  if (showDate) {
    const dateSpan = createEl("span", "event-date", formatDate(e.start));
    div.appendChild(dateSpan);
  }

  const timeSpan = createEl("span", "event-time", formatTime(e.start));
  div.appendChild(timeSpan);

  const summarySpan = createEl("span", "event-summary", e.summary);
  div.appendChild(summarySpan);

  if (e.location) {
    const locSpan = createEl("span", "event-location", e.location);
    div.appendChild(locSpan);
  }

  return div;
}

function setPlaceholder(container, text) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const p = createEl("p", "placeholder", text);
  container.appendChild(p);
}

async function loadToday() {
  try {
    const res = await fetch(`${API}/calendar/today`, { credentials: "include" });
    const data = await res.json();
    const container = document.getElementById("today-events");
    const status = document.getElementById("calendar-status");

    if (data.auth_required) {
      calendarConnected = false;
      while (status.firstChild) status.removeChild(status.firstChild);
      const span = createEl("span");
      span.textContent = "Calendar: ";
      const a = document.createElement("a");
      a.className = "connect-btn";
      a.href = data.auth_url;
      a.target = "_blank";
      a.textContent = "Connect";
      span.appendChild(a);
      status.appendChild(span);
      setPlaceholder(container, "Connect your Google Calendar to see your events.");
      return;
    }

    calendarConnected = true;
    status.textContent = "Calendar: connected";

    if (!data.events || data.events.length === 0) {
      setPlaceholder(container, "No events today — ask me to schedule something!");
      return;
    }

    while (container.firstChild) container.removeChild(container.firstChild);
    data.events.forEach(e => container.appendChild(createEventEl(e, false)));
  } catch (err) {
    setPlaceholder(container, "Failed to load today's events.");
  }
}

async function loadWeek() {
  try {
    const res = await fetch(`${API}/calendar/week`, { credentials: "include" });
    const data = await res.json();
    const container = document.getElementById("week-events");

    if (data.auth_required) {
      setPlaceholder(container, "Connect your Google Calendar to see events.");
      return;
    }

    if (!data.events || data.events.length === 0) {
      setPlaceholder(container, "Your week is clear. Want help planning?");
      return;
    }

    while (container.firstChild) container.removeChild(container.firstChild);
    data.events.forEach(e => container.appendChild(createEventEl(e, true)));
  } catch (err) {
    setPlaceholder(container, "Failed to load week's events.");
  }
}

function addMessage(role, content) {
  const container = document.getElementById("chat-messages");
  const div = createEl("div", `message ${role}`, content);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

const SUGGESTIONS = {
  disconnected: ["Connect your calendar", "What can Qwelio do?", "How does this work?"],
  connected: ["What do I have today?", "Schedule a meeting for tomorrow at 2pm", "Show my week"],
};

function sendSuggestion(text) {
  document.getElementById("chat-input").value = text;
  document.getElementById("chat-form").dispatchEvent(new Event("submit", { cancelable: true }));
}

function getSuggestions() {
  return calendarConnected ? SUGGESTIONS.connected : SUGGESTIONS.disconnected;
}

function initOnboarding() {
  const container = document.getElementById("chat-messages");
  if (container.dataset.onboarded) return;
  container.dataset.onboarded = "true";

  const welcome = createEl("div", "message assistant welcome");
  welcome.textContent = "Welcome to Qwelio! I'm your AI calendar assistant. Connect your Google Calendar and I can help you manage your schedule.";
  container.appendChild(welcome);

  const chips = createEl("div", "suggestion-chips");
  getSuggestions().forEach(text => {
    const btn = createEl("button", "suggestion-chip", text);
    btn.addEventListener("click", () => {
      if (chatLoading) return;
      chips.remove();
      const welcomeEl = container.querySelector(".message.welcome");
      if (welcomeEl) welcomeEl.remove();
      sendSuggestion(text);
    });
    chips.appendChild(btn);
  });
  container.appendChild(chips);
  container.scrollTop = container.scrollHeight;
}

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (chatLoading) return;

  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;

  input.value = "";
  chatLoading = true;
  document.getElementById("chat-form").querySelector("button").disabled = true;

  const welcomeEl = document.querySelector(".message.welcome");
  if (welcomeEl) welcomeEl.remove();
  addMessage("user", text);
  chatHistory.push({ role: "user", content: text });

  try {
    const res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ messages: chatHistory.slice(-20) }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage("system", data.error);
    } else {
      addMessage("assistant", data.content);
      chatHistory.push({ role: "assistant", content: data.content });
    }
  } catch (err) {
    addMessage("system", "Failed to get response.");
  } finally {
    chatLoading = false;
    document.getElementById("chat-form").querySelector("button").disabled = false;
  }
});

document.getElementById("logout-btn").addEventListener("click", logout);

(async () => {
  if (await checkAuth()) {
    await loadToday();
    loadWeek();
    initOnboarding();
    setInterval(loadToday, 60000);
    setInterval(loadWeek, 300000);
  }
})();
