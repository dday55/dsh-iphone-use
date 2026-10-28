// iPhone Use live preview for DeepSeek Harness.
//
// The Codex widget is an MCP App: `assets/phone-screen.html` talks the MCP Apps
// protocol to its host over postMessage. Harness has no MCP Apps host, so this
// module plays that role — it embeds the unchanged page in an iframe, answers
// `ui/initialize`, and forwards `tools/call` to `server/iphone_use.py` over
// stdio. Nothing in the upstream snapshot is modified.
//
// Two entry points:
//   * `createPreviewServer()` — used by dsh/lib/index.js, so the preview starts
//     with the bundle and is already listening before anyone asks for it;
//   * `node dsh/preview/server.mjs [--port 18760]` — standalone.
//
// The Python server is spawned lazily on the first tool call, so an unused
// preview costs one loopback listener and nothing else.

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..", "..");
const DEFAULT_UPSTREAM = process.env.IPHONE_USE_UPSTREAM || join(PKG, "vendor", "iphone-use");
const HOST = "127.0.0.1";

export function createPreviewServer(options = {}) {
  const upstream = options.upstream || DEFAULT_UPSTREAM;
  const python = options.python || process.env.IPHONE_USE_PYTHON || "python3";
  const extraEnv = { ...(options.env ?? {}) };
  const selfClientId = options.selfClientId || "dsh-iphone-use";
  const clientGraph = typeof options.clientGraph === "function" ? options.clientGraph : () => null;
  const clientBundle = typeof options.clientBundle === "function" ? options.clientBundle : null;
  const server = join(upstream, "server", "iphone_use.py");
  const appHtml = readFileSync(join(upstream, "assets", "phone-screen.html"));
  const hostHtml = readFileSync(join(HERE, "host.html"));

  const state = {
    ready: false,
    started: false,
    lastSeq: 0,
    lastBytes: 0,
    lastAt: 0,
    probes: 0,
    error: null,
    // Last report from dsh/client.js. `null` means the browser half never ran in
    // the page that is loaded now, so the preview could not open itself.
    client: null,
    clientReports: 0,
    // Sessions where iPhone Use was actually used in this host process; the
    // browser half opens the sidebar tab only for these.
    usedSessions: new Set(),
  };
  let child = null;
  let nextId = 0;
  const pending = new Map();
  let buffer = "";
  let startPromise = null;

  function rpc(method, params) {
    const id = ++nextId;
    return new Promise((resolveRpc, rejectRpc) => {
      pending.set(id, { resolve: resolveRpc, reject: rejectRpc });
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }

  function ensureMcp() {
    if (state.ready) return Promise.resolve();
    if (startPromise) return startPromise;
    state.started = true;
    child = spawn(python, [server], {
      cwd: upstream,
      env: {
        ...process.env,
        IPHONE_USE_ANALYTICS: process.env.IPHONE_USE_ANALYTICS ?? "0",
        DO_NOT_TRACK: "1",
        ...extraEnv,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    child.stderr.on("data", (chunk) => console.error(`[iphone-use preview] ${chunk}`));
    child.on("exit", (code) => {
      state.ready = false;
      state.started = false;
      startPromise = null;
      state.error = `MCP server exited (${code})`;
      for (const [id, entry] of pending.entries()) {
        pending.delete(id);
        entry.reject(new Error(`MCP server exited before response (code ${code})`));
      }
    });
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        if (!line) continue;
        let message;
        try { message = JSON.parse(line); } catch { continue; }
        if (message.id === undefined) continue;
        const entry = pending.get(message.id);
        if (!entry) continue;
        pending.delete(message.id);
        message.error
          ? entry.reject(new Error(message.error.message || "MCP error"))
          : entry.resolve(message.result);
      }
    });
    startPromise = (async () => {
      try {
        await rpc("initialize", {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "iphone-use-preview", version: "1.0" },
        });
        child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
        // Starts the cached MJPEG hub and the same session the model uses.
        await rpc("tools/call", { name: "pua_screen", arguments: { action: "open" } });
        state.ready = true;
      } catch (error) {
        state.ready = false;
        state.started = false;
        startPromise = null;
        throw error;
      }
    })();
    return startPromise;
  }

  async function callTool(name, args) {
    await ensureMcp();
    const result = await rpc("tools/call", { name, arguments: args ?? {} });
    if (name === "pua_screen_frame" && !result?.isError) {
      const frame = result.structuredContent?.frame;
      if (frame?.seq) {
        state.lastSeq = frame.seq;
        state.lastBytes = typeof frame.data === "string" ? frame.data.length : 0;
        state.lastAt = Date.now();
      }
    }
    return result;
  }

  function isTrustedOrigin(origin) {
    if (!origin) return true;
    try {
      const parsed = new URL(origin);
      return parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost";
    } catch {
      return false;
    }
  }

  function corsHeaders(request) {
    const origin = request.headers.origin;
    if (origin && isTrustedOrigin(origin)) {
      return {
        "access-control-allow-origin": origin,
        "vary": "Origin",
      };
    }
    return {};
  }

  const http = createServer(async (request, response) => {
    const origin = request.headers.origin;
    if (origin && !isTrustedOrigin(origin)) {
      response.writeHead(403, { "content-type": "text/plain" });
      return response.end("Forbidden: cross-origin access from untrusted origin denied.");
    }

    const url = new URL(request.url, `http://${HOST}`);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      return response.end(hostHtml);
    }
    if (request.method === "GET" && url.pathname === "/app.html") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
      return response.end(appHtml);
    }
    if (request.method === "GET" && url.pathname === "/health") {
      // The DSH UI runs on another loopback port and probes this from the
      // browser before opening the sidebar tab (and keeps probing until the tab
      // delivers its first frame).
      state.probes += 1;
      response.writeHead(200, {
        "content-type": "application/json",
        ...corsHeaders(request),
        "cache-control": "no-store",
      });
      const session = url.searchParams.get("session");
      // Host-side evidence: is this package's client module part of the boot
      // graph the page was served with? When this is false the browser can never
      // run the plugin no matter how often the page is reloaded.
      let boot = null;
      try {
        const ids = clientGraph();
        if (Array.isArray(ids)) {
          boot = { total: ids.length, has_self: ids.includes(selfClientId) };
          if (url.searchParams.get("graph") === "1") boot.ids = ids;
        }
      } catch {
        boot = null;
      }
      return response.end(JSON.stringify({
        // `used` answers the only question the browser half asks: did the model
        // use iPhone Use in this very Session?
        ...(session ? { session, used: state.usedSessions.has(session) } : {}),
        ready: state.ready,
        frame_seq: state.lastSeq,
        frame_bytes: state.lastBytes,
        frame_age_ms: state.lastAt ? Date.now() - state.lastAt : null,
        probes: state.probes,
        error: state.error,
        client: state.client,
        client_reports: state.clientReports,
        client_boot: boot,
        ...(url.searchParams.get("bundle") === "1" && clientBundle
          ? { client_bundle: await clientBundle() }
          : {}),
      }));
    }
    // Mark a Session as one that used iPhone Use. The host tool calls this in
    // process; the endpoint also lets a local diagnostic do the same.
    if (request.method === "POST" && url.pathname === "/mark-used") {
      let body = "";
      for await (const chunk of request) body += chunk;
      let session = "";
      try {
        session = String(JSON.parse(body || "{}").session ?? "");
      } catch {
        session = "";
      }
      if (!session) {
        response.writeHead(400, { "content-type": "application/json", ...corsHeaders(request) });
        return response.end(JSON.stringify({ ok: false, error: "session_required" }));
      }
      state.usedSessions.add(session);
      response.writeHead(204, { ...corsHeaders(request), "cache-control": "no-store" });
      return response.end();
    }
    // Browser half telemetry: proves whether dsh/client.js ran in the loaded page
    // and whether its openTab call landed. Loopback-only, write-only, no secrets.
    if (request.method === "POST" && url.pathname === "/client-report") {
      let body = "";
      for await (const chunk of request) body += chunk;
      state.clientReports += 1;
      try {
        const report = JSON.parse(body || "{}");
        state.client = typeof report === "object" && report !== null ? report : { event: "unparsed" };
      } catch {
        state.client = { event: "unparsed", raw: String(body).slice(0, 200) };
      }
      response.writeHead(204, {
        ...corsHeaders(request),
        "cache-control": "no-store",
      });
      return response.end();
    }
    if (request.method === "OPTIONS") {
      response.writeHead(204, {
        ...corsHeaders(request),
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type",
        "access-control-max-age": "600",
      });
      return response.end();
    }
    if (request.method === "POST" && url.pathname === "/rpc") {
      let body = "";
      for await (const chunk of request) body += chunk;
      try {
        const { name, arguments: args } = JSON.parse(body || "{}");
        const result = await callTool(name, args);
        response.writeHead(200, { "content-type": "application/json", ...corsHeaders(request) });
        return response.end(JSON.stringify({ result }));
      } catch (error) {
        state.error = String(error?.message || error);
        response.writeHead(200, { "content-type": "application/json", ...corsHeaders(request) });
        return response.end(JSON.stringify({
          result: { isError: true, content: [{ type: "text", text: state.error }] },
        }));
      }
    }
    response.writeHead(404).end("not found");
  });

  async function alive(port) {
    try {
      const response = await fetch(`http://${HOST}:${port}/health`, { signal: AbortSignal.timeout(1500) });
      if (!response.ok) return false;
      const health = await response.json();
      // Only reuse our own listener, never an unrelated service that happens to
      // answer 200 on this port.
      return typeof health === "object" && health !== null && "frame_seq" in health;
    } catch {
      return false;
    }
  }

  return {
    state,
    /** Listen on the first free port, or reuse an identical instance already there. */
    async listen(preferred = 18760) {
      for (let offset = 0; offset < 10; offset += 1) {
        const port = preferred + offset;
        if (await alive(port)) return { url: `http://${HOST}:${port}`, port, reused: true };
        const bound = await new Promise((resolveListen) => {
          const onError = (error) => {
            http.removeListener("listening", onListening);
            resolveListen(error.code === "EADDRINUSE" ? "busy" : `error:${error.code}`);
          };
          const onListening = () => {
            http.removeListener("error", onError);
            resolveListen("ok");
          };
          http.once("error", onError);
          http.once("listening", onListening);
          http.listen(port, HOST);
        });
        if (bound === "ok") return { url: `http://${HOST}:${port}`, port, reused: false };
        if (bound !== "busy") throw new Error(`preview could not listen on ${HOST}:${port} (${bound})`);
      }
      throw new Error("preview could not find a free loopback port");
    },
    /** Record that iPhone Use was used in this Session. */
    markUsed(sessionId) {
      if (typeof sessionId === "string" && sessionId) state.usedSessions.add(sessionId);
    },
    close() {
      try { http.close(); } catch { /* already closed */ }
      try { child?.kill(); } catch { /* already gone */ }
      state.ready = false;
      state.started = false;
      startPromise = null;
      for (const [id, entry] of pending.entries()) {
        pending.delete(id);
        entry.reject(new Error("Preview server closed"));
      }
    },
  };
}

// Standalone entry: node dsh/preview/server.mjs [--port 18760]
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  const portArg = argv.indexOf("--port");
  const preferred = Number(portArg >= 0 ? argv[portArg + 1] : process.env.IPHONE_USE_PREVIEW_PORT || 18760);
  const preview = createPreviewServer();
  const { url, port, reused } = await preview.listen(preferred);
  console.log(`iPhone Use preview: ${url}${reused ? " (reused a running instance)" : ""}`);
  console.log("Open it in the Harness right sidebar (Browser) or any browser window.");
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { preview.close(); process.exit(0); });
  void port;
}
