const express = require("express");
const path = require("path");
const http = require("http");

const app = express();

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const backendUrl = new URL(BACKEND_URL);

function checkSession(req) {
  return new Promise((resolve) => {
    const options = {
      hostname: backendUrl.hostname,
      port: backendUrl.port || (backendUrl.protocol === "https:" ? 443 : 80),
      path: "/api/auth/me",
      method: "GET",
      headers: {
        Cookie: req.headers.cookie || "",
      },
    };

    const reqObj = http.request(options, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });

    reqObj.setTimeout(3000, () => { reqObj.destroy(); resolve(false); });
    reqObj.on("error", () => resolve(false));
    reqObj.end();
  });
}

app.get("/", async (req, res) => {
  const isAuthenticated = await checkSession(req);
  if (!isAuthenticated) {
    res.sendFile(path.join(__dirname, "public", "login.html"));
    return;
  }
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`Dashboard running at http://localhost:${PORT}`);
  });
}

module.exports = app;
