const API = "/api";

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorDiv = document.getElementById("login-error");
  errorDiv.style.display = "none";
  errorDiv.textContent = "";

  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const btn = e.target.querySelector("button");
  btn.disabled = true;

  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      window.location.href = "/";
    } else {
      const data = await res.json();
      if (res.status === 429) {
        errorDiv.textContent = "Too many login attempts. Try again later.";
      } else {
        errorDiv.textContent = data.detail || "Invalid credentials";
      }
      errorDiv.style.display = "block";
    }
  } catch {
    errorDiv.textContent = "Failed to connect to the server.";
    errorDiv.style.display = "block";
  } finally {
    btn.disabled = false;
  }
});
