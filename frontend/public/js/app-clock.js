/* ============================================================
   Qwelio — Clock: Live timezone clock in header
   ============================================================ */

function initClock() {
  const clockEl = document.getElementById("header-clock");
  function updateClock() {
    const now = djs();
    const time = now.format("HH:mm:ss");
    const tz = userTimezone;
    clockEl.textContent = `${time} ${tz}`;
  }
  updateClock();
  setInterval(updateClock, 1000);
}
