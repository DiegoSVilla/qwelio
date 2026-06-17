/* ============================================================
   Qwelio — Day Detail: Event cards for selected day
   ============================================================ */

function formatTime(iso) {
  if (!iso) return "";
  const d = djsTz(iso);
  return d.format("HH:mm");
}

function formatDate(iso) {
  if (!iso) return "";
  const d = djsTz(iso);
  return d.format("ddd, MMM D");
}

function loadDayEvents(dateStr) {
  const container = document.getElementById("day-detail-events");
  const dateLabel = document.getElementById("day-detail-date");

  const d = djsTz(dateStr);
  dateLabel.textContent = d.format("dddd, MMMM D, YYYY");

  const dayEvents = allMonthEvents.filter(ev => {
    const start = ev.start || "";
    if (!start) return false;
    const evDate = djsTz(start).format("YYYY-MM-DD");
    return evDate === dateStr;
  }).sort((a, b) => (a.start || "").localeCompare(b.start || ""));

  while (container.firstChild) container.removeChild(container.firstChild);

  if (dayEvents.length === 0) {
    const p = createEl("p", "day-no-events", "No events for this day");
    container.appendChild(p);
    return;
  }

  dayEvents.forEach(ev => {
    const card = document.createElement("div");
    card.className = "day-event-card";

    const timeEl = createEl("span", "day-event-time", formatTime(ev.start));
    card.appendChild(timeEl);

    const info = document.createElement("div");
    info.className = "day-event-info";

    const summary = createEl("div", "day-event-summary", ev.summary || "No title");
    info.appendChild(summary);

    if (ev.location) {
      const loc = createEl("div", "day-event-location", ev.location);
      info.appendChild(loc);
    }

    if (ev.description) {
      const desc = createEl("div", "day-event-desc", ev.description.length > 80 ? ev.description.slice(0, 80) + "..." : ev.description);
      info.appendChild(desc);
    }

    card.appendChild(info);
    container.appendChild(card);
  });
}
