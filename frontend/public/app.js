const API = "http://localhost:8000/api";
const chatHistory = [];
let chatLoading = false;

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
  container.innerHTML = "";
  const p = createEl("p", "placeholder", text);
  container.appendChild(p);
}

async function loadToday() {
  try {
    const res = await fetch(`${API}/calendar/today`);
    const data = await res.json();
    const container = document.getElementById("today-events");
    const status = document.getElementById("calendar-status");

    if (data.auth_required) {
      status.innerHTML = "";
      const span = createEl("span");
      span.textContent = "Calendar: ";
      const a = document.createElement("a");
      a.href = data.auth_url;
      a.target = "_blank";
      a.textContent = "Connect";
      span.appendChild(a);
      status.appendChild(span);
      setPlaceholder(container, "Connect your Google Calendar to see events.");
      return;
    }

    status.textContent = "Calendar: connected";

    if (!data.events || data.events.length === 0) {
      setPlaceholder(container, "No events today.");
      return;
    }

    container.innerHTML = "";
    data.events.forEach(e => container.appendChild(createEventEl(e, false)));
  } catch (err) {
    container.innerHTML = "";
    const p = createEl("p", "error", "Failed to load today's events.");
    container.appendChild(p);
  }
}

async function loadWeek() {
  try {
    const res = await fetch(`${API}/calendar/week`);
    const data = await res.json();
    const container = document.getElementById("week-events");

    if (data.auth_required) {
      setPlaceholder(container, "Connect your Google Calendar to see events.");
      return;
    }

    if (!data.events || data.events.length === 0) {
      setPlaceholder(container, "No events this week.");
      return;
    }

    container.innerHTML = "";
    data.events.forEach(e => container.appendChild(createEventEl(e, true)));
  } catch (err) {
    container.innerHTML = "";
    const p = createEl("p", "error", "Failed to load week's events.");
    container.appendChild(p);
  }
}

function addMessage(role, content) {
  const container = document.getElementById("chat-messages");
  const div = createEl("div", `message ${role}`, content);
  container.appendChild(div);
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

  addMessage("user", text);
  chatHistory.push({ role: "user", content: text });

  try {
    const res = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

loadToday();
loadWeek();
setInterval(loadToday, 60000);
setInterval(loadWeek, 300000);
