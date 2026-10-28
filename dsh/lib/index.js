// DeepSeek Harness entry for the vendored iPhone Use runtime.
//
// Three jobs:
//   1. mount @deepseek-ai/dsh-mcp-client for vendor/iphone-use/server/iphone_use.py
//   2. mount a second dsh-skill-filesystem provider for the bundled skills
//   3. start the live preview (an in-process loopback server) and expose its URL
//      to the model through the `iphone_preview` tool
//
// Every path is derived from this module's own URL, so a git install works
// wherever pnpm put the package.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as mcpClient from "@deepseek-ai/dsh-mcp-client";
import * as skillFilesystem from "@deepseek-ai/dsh-skill-filesystem";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { createPreviewServer } from "../preview/server.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
// <pkg>/dsh/lib/index.js -> <pkg>
const PKG = dirname(dirname(HERE));
const UPSTREAM = join(PKG, "vendor", "iphone-use");

export const name = "iphone-use";
export const inject = ["tools"];

// Root-scope registrations outlive the plugin that made them: a plugin reload
// leaves the previous MCP client, skill provider and tool behind, and the next
// activation fails with "serverName is already in use" or "tool is already
// registered". Keep the children in a process-wide slot so the next activation
// can dispose them even when it comes from a freshly evaluated module (HMR and
// reinstalls do exactly that), and dispose this activation's own set on unload.
const CHILDREN = Symbol.for("dsh-iphone-use.children");

async function disposeAll(children) {
  for (const child of children.splice(0).reverse()) {
    try {
      await child?.dispose?.();
    } catch {
      // Already disposed.
    }
  }
}

// No `Config` export on purpose: cordis treats an exported Config as a Standard
// Schema and calls `.validate` on it; a plain object throws at activation.
//
// Children mount on `ctx.root`: mounted on this plugin's own fiber they
// activate without errors, but the agent's tool and skill catalogs never see
// them (the scope is isolated).

export async function apply(ctx, config = {}) {
  const timeout = Number.isInteger(config.toolCallTimeoutMs) ? config.toolCallTimeoutMs : 180000;
  const python = typeof config.python === "string" && config.python ? config.python : "python3";
  const env = {
    IPHONE_USE_ANALYTICS: "0",
    DO_NOT_TRACK: "1",
  };
  for (const [key, value] of Object.entries(config.env ?? {})) env[key] = String(value);

  const owned = [];
  // Dispose whatever a previous activation in this process left behind, and let
  // this activation own the slot from here on.
  await disposeAll(globalThis[CHILDREN] ?? []);
  globalThis[CHILDREN] = owned;
  ctx.effect(() => () => {
    if (globalThis[CHILDREN] === owned) globalThis[CHILDREN] = [];
    return disposeAll(owned);
  }, "iphone-use.children");

  // A reload may race the previous instance's teardown. Wait up to ~8 s for a
  // conflicting registration to clear, then accept the existing one: the row is
  // more useful active with the previous instance's MCP client than failed.
  async function mountChild(label, plugin, pluginConfig) {
    for (let attempt = 0; attempt < 16; attempt += 1) {
      try {
        const child = await ctx.root.plugin(plugin, pluginConfig);
        owned.push(child);
        return child;
      } catch (error) {
        const message = String(error?.message ?? error);
        if (!/already in use|already registered/i.test(message)) throw error;
        if (attempt === 15) {
          console.error(`[iphone-use] ${label} already provided by another instance; continuing with it (${message})`);
          return undefined;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    return undefined;
  }

  // Await the child fibers: mounted on the root scope they are not part of this
  // plugin's own activation, and boot would otherwise hand the first turn a tool
  // catalog captured before the MCP connection finished syncing. Awaiting makes
  // activation mean "tools are registered".
  await mountChild("mcp-client", mcpClient, {
    serverName: "iphone_use",
    transport: "stdio",
    command: python,
    args: [join(UPSTREAM, "server", "iphone_use.py")],
    cwd: UPSTREAM,
    ...(Object.keys(env).length ? { env } : {}),
    toolCallTimeoutMs: timeout,
  });

  // Ship the two upstream skills plus the Harness-specific adapter. Default
  // roots stay off so this provider only contributes what this package carries;
  // the host's own providers still supply their own skills.
  await mountChild("skill-provider", skillFilesystem, {
    providerName: "iphone-use",
    includeDefaultRoots: false,
    customSkillDirs: [join(UPSTREAM, "skills"), join(PKG, "dsh", "skills")],
  });

  // Live preview: starts with the bundle, so the URL is already answering when
  // the user is told about it. The Python server behind it starts on the first
  // tool call, so an unused preview costs one loopback listener.
  const previewEnabled = config.preview !== false;
  const preferredPort = Number.isInteger(config.previewPort) ? config.previewPort : 18760;
  const previewState = { url: null, error: null, reused: false };
  let preview = null;

  // Host-side evidence for the browser half: which client bundles the page was
  // actually served with. `client_boot.has_self === false` means this package's
  // client plugin was never in the boot graph, so reloading the page cannot help.
  let clientModules = null;
  try {
    ctx.inject(["clientModules"], (scoped) => {
      clientModules = scoped.clientModules ?? scoped.get?.("clientModules") ?? null;
    });
  } catch {
    // Older hosts without the client module system.
  }
  const clientGraph = () => {
    try {
      const mods = clientModules ?? ctx.get?.("clientModules") ?? null;
      const entries = mods?.graph?.()?.entries;
      return Array.isArray(entries) ? entries.map((entry) => entry.id) : null;
    } catch {
      return null;
    }
  };

  // Serve-and-check the very bundle the page is told to load. `has_module: false`
  // or a non-200 status means the host cannot deliver this client half at all;
  // the browser then has nothing to execute no matter how often it reloads.
  let bundleProbe = { at: 0, value: null };
  const clientBundle = async () => {
    const now = Date.now();
    if (bundleProbe.value && now - bundleProbe.at < 15000) return bundleProbe.value;
    let value = null;
    try {
      const mods = clientModules ?? ctx.get?.("clientModules") ?? null;
      const entry = mods?.graph?.()?.entries?.find((row) => row.id === "dsh-iphone-use");
      if (!entry) {
        value = { reason: "entry-absent-from-graph" };
      } else if (typeof mods.fetchBundle !== "function") {
        value = { url: String(entry.url), reason: "fetchBundle-unavailable" };
      } else {
        const target = new URL(entry.url, "http://127.0.0.1");
        const response = await mods.fetchBundle(new Request(target, { method: "GET" }));
        const text = await response.text();
        value = {
          url: String(entry.url),
          status: response.status,
          bytes: text.length,
          has_module: text.includes("dsh-iphone-use"),
        };
      }
    } catch (error) {
      value = { reason: "probe-threw", error: String(error?.message ?? error) };
    }
    bundleProbe = { at: now, value };
    return value;
  };

  if (previewEnabled) {
    try {
      preview = createPreviewServer({
        upstream: UPSTREAM,
        python,
        env,
        clientGraph,
        clientBundle,
        selfClientId: "dsh-iphone-use",
      });
      try {
        const info = await preview.listen(preferredPort);
        previewState.url = info.url;
        previewState.reused = info.reused;
      } catch (error) {
        previewState.error = String(error?.message || error);
      }
      ctx.effect(() => () => preview.close(), "iphone-use.preview");
    } catch (error) {
      previewState.error = String(error?.message || error);
    }
  }

  // Mark the Session as soon as it actually touches the phone. Waiting for the
  // model to remember `iphone_preview` made auto-open depend on a habit instead
  // of on usage, and a READY-only first conversation silently got no preview.
  // Any pua_* MCP tool call is proof enough.
  ctx.on("tools/execute", (exec, next) => {
    try {
      const name = typeof exec?.name === "string" ? exec.name : "";
      const sessionId = exec?.agent?.session?.id;
      if (preview && sessionId && name.startsWith("mcp__iphone_use__")) {
        preview.markUsed(sessionId);
      }
    } catch {
      // Diagnostics must never block a tool call.
    }
    return next();
  });

  // Register on the root scope so the agent sees the tool, but keep the disposer
  // and tie it to this plugin: otherwise a reload leaves the name registered and
  // the next activation dies with "tool already registered".
  let unregisterTool;
  try {
    unregisterTool = ctx.root.tools.register(defineTool({
      name: "iphone_preview",
      description:
        "Report the local live iPhone preview and return its URL. The sidebar Browser tab opens by itself once this Session actually calls any iPhone Use tool, so this is a status/URL helper rather than the trigger. It performs no phone action.",
      parameters: {},
      output: {
        schema: {
          type: "object",
          additionalProperties: false,
          properties: {
            url: { type: "string", description: "Loopback URL of the live preview, or empty when disabled." },
            running: { type: "boolean", description: "True when the preview HTTP server is listening." },
            frame_seq: { type: "number", description: "Last frame sequence delivered to a viewer; 0 before anyone opens it." },
            note: { type: "string", description: "What to tell the user, or why the preview is unavailable." },
          },
        },
        render: (_args, value) => [{
          type: "text",
          text: value.running
            ? `${value.url} — ${value.note}`
            : value.note || "iPhone preview is not running.",
        }],
      },
      async execute(_args, exec) {
        // The Session that actually used iPhone Use is the only one whose sidebar
        // gets a preview tab; the browser half asks the server for this.
        const sessionId = exec?.agent?.session?.id;
        if (sessionId && preview) {
          try {
            preview.markUsed(sessionId);
          } catch {
            // Diagnostics only.
          }
        }
        const running = Boolean(previewState.url);
        const frameSeq = preview?.state?.lastSeq ?? 0;
        const client = preview?.state?.client ?? null;
        const graphIds = clientGraph();
        const inBoot = Array.isArray(graphIds) ? graphIds.includes("dsh-iphone-use") : null;
        // `client === null` is the honest signal that the browser half never ran
        // in the page that is loaded now: the tab cannot open itself in that page.
        const clientNote = !client
          ? inBoot === false
            ? "本包的客户端插件根本没有进入当前页面的启动清单（client 未进入 boot graph），因此刷新或重启都无效；请重装插件后再重启桌面应用。"
            : "客户端插件已在启动清单里，但本页面尚未运行它（请完全退出并重新打开应用）。"
          : client.event === "openTab-failed"
            ? `浏览器半侧已加载，但 openTab 失败：${client.error ?? "未知原因"}。`
            : `浏览器半侧最近报告：${client.event}${client.unconfirmed ? `（未确认 ${client.unconfirmed} 次）` : ""}。`;
        const note = !previewEnabled
          ? "预览已在这个 profile 的配置里关闭（config.preview = false）。"
          : running
            ? `预览已自动启动：右侧栏 Browser 会显示实时画面；模型自己的观察仍用 pua_observe(mode="screenshot")。${clientNote}`
            : `预览未启动${previewState.error ? `：${previewState.error}` : "，稍后重试或手工运行 node dsh/preview/server.mjs"}`;
        return { url: previewState.url ?? "", running, frame_seq: frameSeq, note };
      },
    }));
  } catch (error) {
    // A previous instance's registration is still in place; its URL is the same.
    console.error(`[iphone-use] iphone_preview already registered; reusing it (${String(error?.message ?? error)})`);
  }

  if (unregisterTool) {
    ctx.effect(() => () => {
      try {
        unregisterTool();
      } catch {
        // Already removed.
      }
    }, "iphone-use.tool");
  }
}
