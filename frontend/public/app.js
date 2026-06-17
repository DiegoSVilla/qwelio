/* ============================================================
   Qwelio — Main App
   Bootstraps all modules after dayjs plugins are loaded
   ============================================================ */

// Load dayjs plugins (CDN scripts must be loaded before this runs)
dayjs.extend(window.dayjs_plugin_utc);
dayjs.extend(window.dayjs_plugin_timezone);
dayjs.extend(window.dayjs_plugin_relativeTime);

document.getElementById("logout-btn").addEventListener("click", logout);
document.getElementById("cal-prev-btn").addEventListener("click", () => navigateMonth(-1));
document.getElementById("cal-next-btn").addEventListener("click", () => navigateMonth(1));

(async () => {
  if (await checkAuth()) {
    initClock();
    initCalendar();
    initChat();
    initSettings();
    await checkCalendarStatus();
    await loadChatHistory();
    todayInterval = setInterval(loadMonthEvents, 60000);
  }
})();
