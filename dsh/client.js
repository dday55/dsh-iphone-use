// Browser half: put the live preview in the right-sidebar Browser for the
// Sessions that actually use iPhone Use.
//
// DSH has no MCP App host, so the preview is a loopback page served by the bundle
// itself (see preview/server.mjs). Whether a Session used iPhone Use is known by
// the host: the `iphone_preview` tool marks that Session on the preview server,
// and this half asks `GET /health?session=<id>` before placing anything.
//
// Hand-written in the built-bundle format the client module system loads
// (`window.__ModuleLoader__.load`), so it needs no build step.

window.__ModuleLoader__.load({
  id: "dsh-iphone-use",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    // The Sidebar service places tabs; the Browser page kind ships with Desktop.
    const inject = ["sidebarRight"];

    // The host prefers 18760 and walks forward when the port is taken.
    const PORTS = [18760, 18761, 18762, 18763, 18764, 18765, 18766, 18767, 18768, 18769];
    const PREVIEW_URL = /127\.0\.0\.1:1876\d/;

    // Nothing placed yet / no Session on screen yet.
    const RETRY_MS = 1200;
    // Tab is on screen: only the DOM is re-read at this cadence, no network.
    const WATCH_MS = 4000;
    // Not used in this Session yet: ask the host at this cadence.
    const POLL_MS = 3000;
    // A placement that does not show up in the DOM may belong to another Session
    // (or an unmounted pane); back off instead of stacking tabs.
    const CONFIRM_MS = 1200;
    const BACKOFF_MAX = 30000;

    // Per-Session "the user closed it" memory. sessionStorage keeps it across a
    // reload of this page but clears when the browser tab/window goes away.
    const CLOSED_PREFIX = "dsh-iphone-use.preview-closed:";

    // Is a preview tab mounted for THIS Session? Sidebar tabs are real DOM nodes,
    // so the mounted subtree is the only honest "this Session shows the preview"
    // signal — but Desktop keeps inactive Browser tabs mounted (`keepMounted`), so
    // a global "any preview frame exists" check would treat another Session's hidden
    // tab as this Session's and never open anything here.
    function previewTabMounted(sessionId) {
      for (const node of document.querySelectorAll("iframe, webview")) {
        const src = node.getAttribute("src") || node.src || "";
        if (!PREVIEW_URL.test(src)) continue;
        if (!sessionId) return true;
        const owner = node.closest("[data-sidebar-right-session]");
        if (!owner) return true;
        if (owner.dataset.sidebarRightSession === sessionId) return true;
      }
      return false;
    }

    async function findPreview() {
      for (const port of PORTS) {
        try {
          const response = await fetch(`http://127.0.0.1:${port}/health`, { cache: "no-store" });
          if (!response.ok) continue;
          const health = await response.json();
          if (health && typeof health === "object" && "frame_seq" in health) {
            return `http://127.0.0.1:${port}`;
          }
        } catch {
          // Not this port; keep probing.
        }
      }
      return null;
    }

    // Fire-and-forget beacon to whichever preview server answers. Used before the
    // plugin knows its own URL, so load-time failures stay observable.
    async function beacon(event, extra) {
      for (const port of PORTS) {
        try {
          const response = await fetch(`http://127.0.0.1:${port}/health`, { cache: "no-store" });
          if (!response.ok) continue;
          const health = await response.json();
          if (!health || typeof health !== "object" || !("frame_seq" in health)) continue;
          await fetch(`http://127.0.0.1:${port}/client-report`, {
            method: "POST",
            headers: { "content-type": "text/plain" },
            body: JSON.stringify({ event, at: Date.now(), href: location.href, ...extra }),
            keepalive: true,
            cache: "no-store",
          }).catch(() => {});
          return;
        } catch {
          // Keep probing the next candidate port.
        }
      }
    }

    // Evaluation beacon: proves the page actually downloaded and ran this file.
    // Without it, `client: null` cannot tell "script never loaded" apart from
    // "script ran but apply() was never called (inject waited forever)".
    {
      let bootIds = null;
      try {
        bootIds = (window.__DSH_BOOT__?.entries ?? []).map((entry) => entry.id);
      } catch {
        bootIds = null;
      }
      beacon("module-evaluated", {
        in_boot: Array.isArray(bootIds) ? bootIds.includes("dsh-iphone-use") : null,
        boot_size: Array.isArray(bootIds) ? bootIds.length : null,
      });
    }

    async function sessionUsed(base, sessionId) {
      if (!sessionId) return false;
      try {
        const response = await fetch(`${base}/health?session=${encodeURIComponent(sessionId)}`, { cache: "no-store" });
        if (!response.ok) return false;
        const health = await response.json();
        return health?.used === true;
      } catch {
        return false;
      }
    }

    function apply(ctx) {
      try {
        beacon("apply-entered");
        return runApply(ctx);
      } catch (error) {
        beacon("apply-threw", { error: String(error?.message ?? error) });
        throw error;
      }
    }

    function runApply(ctx) {
      let cancelled = false;
      let timer;
      let url = null;
      let confirmed = false;
      // Placements since the last DOM confirmation: drives the backoff only.
      let unconfirmed = 0;
      // Last observed (Session, DOM-mounted) pair, to tell a user close from a
      // Session switch.
      let lastMounted = false;
      // Session whose pane currently shows the preview. A close is only a close
      // when the Session did not change; otherwise the tab merely left the screen
      // because the user switched Sessions.
      let mountedFor = null;
      // Session we already reported as "not used" so the 3 s poll stays quiet.
      let idleFor = null;
      // Progressive poll backoff counter for idle sessions.
      let idlePolls = 0;

      // The Session whose pane is on screen. Check sidebarRight's mounted store
      // directly first (authoritative in Desktop and Web), then fall back to DOM.
      const currentSessionId = () => {
        try {
          const sid = ctx.sidebarRight.mounted?.getSnapshot?.();
          if (typeof sid === "string" && sid) return sid;
        } catch {
          // Fall through.
        }
        try {
          const selected = document.querySelector('[data-row-key^="session:"][aria-selected="true"]');
          const key = selected?.getAttribute("data-row-key") ?? "";
          if (key.startsWith("session:")) {
            const id = key.slice("session:".length);
            if (id) return id;
          }
        } catch {
          // Fall through to the service.
        }
        try {
          return ctx.sidebarRight.commandTarget?.()?.sessionId ?? null;
        } catch {
          return null;
        }
      };
      const wasClosed = (sessionId) => {
        try {
          return sessionId ? window.sessionStorage.getItem(CLOSED_PREFIX + sessionId) === "1" : false;
        } catch {
          return false;
        }
      };
      const markClosed = (sessionId) => {
        try {
          if (sessionId) window.sessionStorage.setItem(CLOSED_PREFIX + sessionId, "1");
        } catch {
          // Storage unavailable: the tab simply stays closed for this page load.
        }
      };

      const schedule = (ms) => {
        clearTimeout(timer);
        if (!cancelled) timer = setTimeout(attempt, ms);
      };

      // Fire-and-forget diagnostics: text/plain keeps it a simple request, so the
      // browser does not preflight a loopback endpoint on every attempt.
      const report = (event, extra) => {
        if (!url) return;
        try {
          fetch(`${url}/client-report`, {
            method: "POST",
            headers: { "content-type": "text/plain" },
            body: JSON.stringify({ event, at: Date.now(), href: location.href, ...extra }),
            keepalive: true,
            cache: "no-store",
          }).catch(() => {});
        } catch {
          // Diagnostics must never break placement.
        }
      };

      const attempt = async () => {
        if (cancelled) return;

        if (!url) {
          url = await findPreview();
          if (cancelled) return;
          if (!url) {
            // The host half is not listening yet (bundle still activating).
            schedule(RETRY_MS);
            return;
          }
          report("client-connected");
        }

        const sessionId = currentSessionId();
        const mounted = previewTabMounted(sessionId);

        // Mounted -> unmounted inside the same Session is the user closing the
        // tab. Switching Sessions changes the id, so it is never mistaken for a
        // close (that used to suppress the next conversation's preview).
        if (sessionId && lastMounted && !mounted && sessionId === mountedFor) {
          markClosed(sessionId);
          report("closed-in-session", { session: sessionId });
          mountedFor = null;
          lastMounted = false;
          confirmed = false;
          schedule(WATCH_MS);
          return;
        }
        lastMounted = mounted;
        if (mounted) mountedFor = sessionId;

        // This Session already shows the preview: keep watching.
        if (mounted) {
          if (!confirmed) {
            confirmed = true;
            unconfirmed = 0;
            report("mounted");
          }
          schedule(WATCH_MS);
          return;
        }
        confirmed = false;

        // If no Session is on screen (e.g. home/plugins/settings page), stay quiet.
        if (!sessionId) {
          schedule(WATCH_MS);
          return;
        }

        // The user closed the preview in this Session: stay quiet until the
        // window is reopened.
        if (wasClosed(sessionId)) {
          schedule(WATCH_MS);
          return;
        }

        // The only trigger: iPhone Use was used in this Session. A conversation
        // that never touched the phone gets no sidebar tab.
        const used = await sessionUsed(url, sessionId);
        if (cancelled) return;
        if (!used) {
          if (idleFor !== sessionId) {
            idleFor = sessionId;
            idlePolls = 0;
            report("idle", { session: sessionId });
          }
          idlePolls += 1;
          const delay = idlePolls <= 4 ? POLL_MS : idlePolls <= 12 ? POLL_MS * 2 : 15000;
          schedule(delay);
          return;
        }
        idleFor = null;
        idlePolls = 0;

        try {
          // Browser page kind; the initial address travels in navigation params.
          ctx.sidebarRight.openTab("browser", { params: { url } });
        } catch (error) {
          // No adopted Session on screen yet, or the Browser type is unavailable.
          report("openTab-failed", { error: String(error?.message ?? error), unconfirmed });
          schedule(RETRY_MS);
          return;
        }

        unconfirmed += 1;
        report("placed", { unconfirmed, session: sessionId });
        // Check whether it actually landed before placing anything again.
        schedule(unconfirmed > 2 ? Math.min(CONFIRM_MS * 2 ** unconfirmed, BACKOFF_MAX) : CONFIRM_MS);
      };

      // A Session switch, a restored layout or a fresh focus is exactly when the
      // tab from the previous Session stops being on screen.
      const onSessionishEvent = () => {
        if (cancelled) return;
        idlePolls = 0;
        if (previewTabMounted(currentSessionId())) return;
        confirmed = false;
        unconfirmed = 0;
        schedule(300);
      };
      const onVisible = () => {
        if (!document.hidden) onSessionishEvent();
      };
      for (const name of ["hashchange", "popstate"]) {
        window.addEventListener(name, onSessionishEvent);
      }
      document.addEventListener("visibilitychange", onVisible);
      window.addEventListener("focus", onSessionishEvent);

      timer = setTimeout(attempt, 1500);
      ctx.effect(() => () => {
        cancelled = true;
        clearTimeout(timer);
        for (const name of ["hashchange", "popstate"]) {
          window.removeEventListener(name, onSessionishEvent);
        }
        document.removeEventListener("visibilitychange", onVisible);
        window.removeEventListener("focus", onSessionishEvent);
      }, "iphone-use.preview-tab");
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
