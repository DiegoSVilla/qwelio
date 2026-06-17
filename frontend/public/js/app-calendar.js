/* ============================================================
   Qwelio — Calendar Grid: Monthly view with prev/next nav
   ============================================================ */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

let viewYear, viewMonth;
let selectedDate;

function initCalendar() {
  const now = djs();
  viewYear = now.year();
  viewMonth = now.month();
  selectedDate = now.format("YYYY-MM-DD");
  renderWeekdays();
  renderCalendar();
}

function renderWeekdays() {
  const container = document.getElementById("cal-weekdays");
  while (container.firstChild) container.removeChild(container.firstChild);
  WEEKDAYS.forEach(name => {
    container.appendChild(createEl("div", "calendar-weekday", name));
  });
}

function renderCalendar() {
  const grid = document.getElementById("cal-grid");
  while (grid.firstChild) grid.removeChild(grid.firstChild);

  const label = document.getElementById("cal-month-label");
  label.textContent = `${MONTHS[viewMonth]} ${viewYear}`;

  const now = djs();
  const today = now.format("YYYY-MM-DD");

  const firstDay = djsTz(`${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-01`);
  const startDow = firstDay.day();
  const daysInMonth = firstDay.daysInMonth();

  const currentWeekStart = now.startOf("week").date();
  const currentWeekEnd = now.endOf("week").date();

  const prevMonth = viewMonth === 0 ? 11 : viewMonth - 1;
  const prevYear = viewMonth === 0 ? viewYear - 1 : viewYear;
  const daysInPrevMonth = djsTz(`${prevYear}-${String(prevMonth + 1).padStart(2, "0")}-01`).daysInMonth();

  const eventDates = {};
  allMonthEvents.forEach(ev => {
    const start = ev.start || "";
    if (start) {
      const d = djsTz(start);
      if (d.year() === viewYear && d.month() === viewMonth) {
        const key = d.format("YYYY-MM-DD");
        if (!eventDates[key]) eventDates[key] = 0;
        eventDates[key]++;
      }
    }
  });

  const totalCells = Math.ceil((startDow + daysInMonth) / 7) * 7;

  for (let i = 0; i < totalCells; i++) {
    const cell = document.createElement("div");
    cell.className = "calendar-day";

    let dayNum, dateStr, isOtherMonth = false;

    if (i < startDow) {
      const offset = startDow - i;
      dayNum = daysInPrevMonth - offset + 1;
      dateStr = `${prevYear}-${String(prevMonth + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
      isOtherMonth = true;
    } else if (i >= startDow + daysInMonth) {
      const offset = i - startDow - daysInMonth + 1;
      dayNum = offset;
      const nextMonth = viewMonth === 11 ? 0 : viewMonth + 1;
      const nextYear = viewMonth === 11 ? viewYear + 1 : viewYear;
      dateStr = `${nextYear}-${String(nextMonth + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
      isOtherMonth = true;
    } else {
      dayNum = i - startDow + 1;
      dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
    }

    if (isOtherMonth) {
      cell.classList.add("other-month");
    }

    const d = djsTz(dateStr);
    const dDate = d.date();
    if (dDate >= currentWeekStart && dDate <= currentWeekEnd) {
      cell.classList.add("current-week");
    }

    if (dateStr === today) {
      cell.classList.add("today");
    }
    if (dateStr === selectedDate) {
      cell.classList.add("selected");
    }

    const numEl = createEl("span", "calendar-day-number", dayNum);
    cell.appendChild(numEl);

    // Render event bars for this day
    const dayEvents = allMonthEvents.filter(ev => {
      const s = ev.start || "";
      if (!s) return false;
      const evDate = djsTz(s).format("YYYY-MM-DD");
      return evDate === dateStr;
    }).sort((a, b) => (a.start || "").localeCompare(b.start || ""));

    if (dayEvents.length > 0) {
      const barsContainer = document.createElement("div");
      barsContainer.className = "calendar-day-bars";
      const maxVisible = 3;
      const shown = dayEvents.slice(0, maxVisible);
      shown.forEach(ev => {
        const bar = document.createElement("div");
        bar.className = "calendar-event-bar";
        const isAllDay = !ev.start.includes("T");
        if (isAllDay) {
          bar.classList.add("all-day");
          bar.style.left = "0%";
          bar.style.width = "100%";
        } else {
          const s = djsTz(ev.start);
          const e = ev.end ? djsTz(ev.end) : null;
          const startMin = s.hour() * 60 + s.minute();
          const endMin = e ? e.hour() * 60 + e.minute() : startMin + 60;
          const leftPct = (startMin / 1440) * 100;
          const widthPct = Math.max(((endMin - startMin) / 1440) * 100, 3);
          bar.style.left = `${leftPct}%`;
          bar.style.width = `${widthPct}%`;
        }
        bar.title = ev.summary || "No title";
        barsContainer.appendChild(bar);
      });
      if (dayEvents.length > maxVisible) {
        const more = createEl("div", "calendar-more", `+${dayEvents.length - maxVisible}`);
        barsContainer.appendChild(more);
      }
      cell.appendChild(barsContainer);
    }

    if (!isOtherMonth) {
      cell.addEventListener("click", () => {
        selectedDate = dateStr;
        renderCalendar();
        loadDayEvents(dateStr);
      });
    }

    grid.appendChild(cell);
  }
}

async function loadMonthEvents() {
  if (!calendarConnected) return;
  try {
    const res = await fetch(`${API}/calendar/month?year=${viewYear}&month=${viewMonth + 1}`, { credentials: "include" });
    if (res.status === 401) { handleAuthLoss(); return; }
    const data = await res.json();
    if (data.auth_required) {
      calendarConnected = false;
      return;
    }
    allMonthEvents = data.events || [];
    renderCalendar();
  } catch (err) {
    qwlog("QW-C001", `loadMonthEvents: error: ${err.message}`);
  }
}

function navigateMonth(delta) {
  viewMonth += delta;
  if (viewMonth > 11) { viewMonth = 0; viewYear++; }
  if (viewMonth < 0) { viewMonth = 11; viewYear--; }
  renderCalendar();
  loadMonthEvents();
}
