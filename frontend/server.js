const express = require("express");
const path = require("path");
const http = require("http");

const app = express();

app.use(express.json());

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const backendUrl = new URL(BACKEND_URL);
const PROXY_TIMEOUT_MS = parseInt(process.env.PROXY_TIMEOUT_MS, 10) || 120000;

const SKIP_HEADERS = new Set([
  "connection", "keep-alive", "transfer-encoding", "te", "trailer",
  "upgrade", "proxy-authorization", "proxy-authenticate", "host",
]);

function proxyToBackend(req, res) {
  const headers = {};
  for (const [key, value] of Object.entries(req.headers)) {
    if (!SKIP_HEADERS.has(key)) {
      headers[key] = value;
    }
  }
  headers.host = backendUrl.host;

  const options = {
    hostname: backendUrl.hostname,
    port: backendUrl.port || (backendUrl.protocol === "https:" ? 443 : 80),
    path: req.originalUrl,
    method: req.method,
    headers,
  };

  let responded = false;
  let headersSent = false;

  console.log(`[QW-P001] Proxy ${req.method} ${req.originalUrl} → ${backendUrl.host}${req.originalUrl}`);

  const reqObj = http.request(options, (backendRes) => {
    if (responded) return;
    responded = true;
    console.log(`[QW-P002] Proxy response ${backendRes.statusCode} for ${req.method} ${req.originalUrl}`);

    const setCookie = backendRes.headers["set-cookie"];
    if (setCookie) {
      const cleaned = setCookie.map(c => {
        let cookie = c;
        cookie = cookie.replace(/Domain=[^;]+/gi, "");
        cookie = cookie.replace(/SameSite=Lax/i, "SameSite=None; Secure");
        return cookie.replace(/;;/g, ";").trim();
      });
      console.log(`[QW-P003] Set-Cookie for ${req.method} ${req.originalUrl}:`, cleaned.map(c => c.split(";")[0]).join(", "));
      res.setHeader("set-cookie", cleaned);
    }

    const forwardHeaders = ["content-type", "cache-control", "expires", "etag", "location", "retry-after"];
    for (const key of forwardHeaders) {
      if (backendRes.headers[key]) {
        res.setHeader(key, backendRes.headers[key]);
      }
    }

    res.status(backendRes.statusCode);
    headersSent = true;
    backendRes.pipe(res);
  });

  reqObj.setTimeout(PROXY_TIMEOUT_MS, () => {
    if (responded) return;
    responded = true;
    reqObj.destroy();
    console.log(`[QW-P005] Gateway timeout for ${req.method} ${req.originalUrl}`);
    res.status(504).send("Gateway Timeout");
  });
  reqObj.on("error", (err) => {
    if (responded) return;
    if (headersSent) {
      console.log(`[QW-P006] Backend connection dropped for ${req.method} ${req.originalUrl} (headers already sent): ${err.message}`);
      return;
    }
    responded = true;
    console.log(`[QW-P005] Bad gateway for ${req.method} ${req.originalUrl}: ${err.message}`);
    res.status(502).send("Bad Gateway");
  });

  if (req.body && Object.keys(req.body).length > 0) {
    reqObj.write(JSON.stringify(req.body));
  }
  reqObj.end();
}

function checkSession(req) {
  return new Promise((resolve) => {
    const options = {
      hostname: backendUrl.hostname,
      port: backendUrl.port || (backendUrl.protocol === "https:" ? 443 : 80),
      path: "/api/auth/me",
      method: "GET",
      headers: {
        cookie: req.headers.cookie || "",
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
  res.setHeader("Cache-Control", "no-store");
  const isAuthenticated = await checkSession(req);
  if (!isAuthenticated) {
    res.sendFile(path.join(__dirname, "public", "login.html"));
    return;
  }
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.get("/login", (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  res.sendFile(path.join(__dirname, "public", "login.html"));
});

app.all("/api/*", (req, res) => {
  proxyToBackend(req, res);
});

app.use(express.static(path.join(__dirname, "public"), {
  index: false,
  setHeaders: (res) => {
    res.setHeader("Cache-Control", "no-cache, no-store, must-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");
  },
}));

if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`Dashboard running at http://localhost:${PORT}`);
  });
}

module.exports = app;
