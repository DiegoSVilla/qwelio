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
  document.getElementById("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (chatLoading) return;

    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    qwlog("QW-F050", `Chat submit: "${text.substring(0, 80)}"`);
    input.value = "";
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
