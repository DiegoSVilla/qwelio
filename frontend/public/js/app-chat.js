/* ============================================================
   Qwelio — Chat: Terminal-style messages, markdown, onboarding
   ============================================================ */

function addMessage(role, content) {
  const container = document.getElementById("chat-messages");
  const div = createEl("div", `chat-message ${role}`);

  const prefix = createEl("span", "msg-prefix");
  prefix.textContent = role === "user" ? "> " : role === "assistant" ? "Q> " : "! ";
  div.appendChild(prefix);

  const contentEl = createEl("span", "msg-content");
  if (role === "assistant" && typeof content === "string") {
    contentEl.innerHTML = DOMPurify.sanitize(marked.parse(content));
  } else {
    contentEl.textContent = content || "";
  }
  div.appendChild(contentEl);

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addToolCall(toolName) {
  const container = document.getElementById("chat-messages");
  const div = createEl("div", "chat-message tool-call");

  const prefix = createEl("span", "msg-prefix");
  prefix.textContent = "[tool] ";
  div.appendChild(prefix);

  const contentEl = createEl("span", "msg-content");
  contentEl.textContent = toolName;
  div.appendChild(contentEl);

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addSummaryMessage(period, periodStart, content) {
  const container = document.getElementById("chat-messages");
  const div = createEl("div", "chat-message summary");

  const prefix = createEl("span", "msg-prefix");
  const periodLabel = period === "monthly" ? "MONTH" : period === "weekly" ? "WEEK" : "DAY";
  prefix.textContent = `[${periodLabel}]`;
  div.appendChild(prefix);

  const contentEl = createEl("span", "msg-content");
  contentEl.textContent = content;
  div.appendChild(contentEl);

  if (container.firstChild) {
    container.insertBefore(div, container.firstChild);
  } else {
    container.appendChild(div);
  }
}

async function loadChatHistory() {
  const container = document.getElementById("chat-messages");
  try {
    const limit = 20;
    const res = await fetch(`${API}/conversations?limit=${limit}`, { credentials: "include" });
    if (!res.ok) return;
    const data = await res.json();

    if (data.history && data.history.length) {
      data.history.forEach(msg => {
        if (msg.role === "user" && msg.content) {
          addMessage("user", msg.content);
          chatHistory.push({ role: "user", content: msg.content });
        } else if (msg.role === "assistant" && msg.content) {
          addMessage("assistant", msg.content);
          chatHistory.push({ role: "assistant", content: msg.content });
        }
      });
      return;
    }
  } catch (err) {
    qwlog("QW-F060", `loadChatHistory: exception: ${err.message}`);
  }
  initOnboarding();
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

  const welcome = createEl("div", "chat-message assistant welcome");
  const wPrefix = createEl("span", "msg-prefix", "Q> ");
  welcome.appendChild(wPrefix);
  const wContent = createEl("span", "msg-content");
  wContent.textContent = "Welcome to Qwelio! I'm your AI calendar assistant. Connect your Google Calendar and I can help you manage your schedule.";
  welcome.appendChild(wContent);
  container.appendChild(welcome);

  const chips = createEl("div", "suggestion-chips");
  getSuggestions().forEach(text => {
    const btn = createEl("button", "suggestion-chip", text);
    btn.addEventListener("click", () => {
      if (chatLoading) return;
      chips.remove();
      const welcomeEl = container.querySelector(".chat-message.welcome");
      if (welcomeEl) welcomeEl.remove();
      sendSuggestion(text);
    });
    chips.appendChild(btn);
  });
  container.appendChild(chips);
  container.scrollTop = container.scrollHeight;
}

function initChat() {
  const input = document.getElementById("chat-input");

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("chat-form").requestSubmit();
    }
  });

  document.getElementById("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (chatLoading) return;

    const text = input.value.trim();
    if (!text) return;

    qwlog("QW-F050", `Chat submit: "${text.substring(0, 80)}"`);
    input.value = "";
    autoResize();
    chatLoading = true;
    document.getElementById("chat-form").querySelector("button").disabled = true;

    const welcomeEl = document.querySelector(".chat-message.welcome");
    if (welcomeEl) welcomeEl.remove();
    addMessage("user", text);
    chatHistory.push({ role: "user", content: text });

    try {
      qwlog("QW-F051", `Chat: sending ${chatHistory.length} messages to /api/chat`);
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ messages: chatHistory.slice(-20) }),
      });
      qwlog("QW-F052", `Chat: response status=${res.status}`);
      if (res.status === 401) { qwlog("QW-F053", "Chat: 401, handleAuthLoss"); handleAuthLoss(); return; }
      const data = await res.json();
      if (data.error) {
        qwlog("QW-F054", `Chat: error response: ${data.error}`);
        addMessage("system", data.error);
      } else {
        qwlog("QW-F055", `Chat: success, response length=${data.content ? data.content.length : 0}`);
      if (data.tool_calls && data.tool_calls.length) {
        data.tool_calls.forEach(tc => addToolCall(tc));
        const calendarTools = new Set(["create_event", "edit_event", "delete_event"]);
        if (data.tool_calls.some(tc => calendarTools.has(tc))) {
          loadMonthEvents();
        }
      }
        addMessage("assistant", data.content);
        chatHistory.push({ role: "assistant", content: data.content });
      }
    } catch (err) {
      qwlog("QW-F056", `Chat: exception: ${err.message}`);
      addMessage("system", "Failed to get response.");
    } finally {
      qwlog("QW-F057", "Chat: finally block, resetting loading state");
      chatLoading = false;
      document.getElementById("chat-form").querySelector("button").disabled = false;
    }
  });
}
