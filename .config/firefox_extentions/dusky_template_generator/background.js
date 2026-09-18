/*
 * Dusky Template Generator — background.js (MV3 event page, Gecko 156+)
 *
 * Single privileged broker:
 *   1. ONE long-lived native host process via runtime.connectNative, with
 *      id-correlated request/response and a hard timeout (FINDING 6);
 *   2. content.js injected on demand through scripting.executeScript under
 *      the activeTab grant;
 *   3. Alt+Shift+P toggles the picker, degrading loudly when the command
 *      carries no host permission (FINDING 7);
 *   4. domain is ALWAYS derived from sender.url for tab-originated messages,
 *      so a content script can never write another site's template.
 */
"use strict";

const HOST = "dusky_template_generator";
const HOST_OPS = new Set(["ping", "read", "write", "splice", "delete"]);
const HOST_TIMEOUT_MS = 8000;
const IDLE_DISCONNECT_MS = 30000;

/* ── Native port: one process, correlated messages ───────────────────── */
let port = null;
let nextId = 1;
let idleTimer = 0;
const pending = new Map();

function dropPort(reason) {
  const p = port;
  port = null;
  for (const [, entry] of pending) {
    clearTimeout(entry.timer);
    entry.reject(new Error(reason));
  }
  pending.clear();
  try { p?.disconnect(); } catch { /* already gone */ }
}

function armIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (!pending.size) dropPort("idle");
  }, IDLE_DISCONNECT_MS);
}

function getPort() {
  if (port) return port;
  port = browser.runtime.connectNative(HOST);
  port.onMessage.addListener((reply) => {
    const id = reply?.__id;
    const entry = pending.get(id);
    if (!entry) return;
    pending.delete(id);
    clearTimeout(entry.timer);
    delete reply.__id;
    entry.resolve(reply);
    armIdle();
  });
  port.onDisconnect.addListener((p) => {
    const err = p.error?.message ?? browser.runtime.lastError?.message ?? "native host disconnected";
    port = null;
    for (const [, entry] of pending) {
      clearTimeout(entry.timer);
      entry.reject(new Error(err));
    }
    pending.clear();
  });
  return port;
}

/* Dispatch is still serialised: the host holds a per-domain flock, but
 * ordering the writes here keeps the common path lock-free. */
let queue = Promise.resolve();

function hostCall(request) {
  const run = () => new Promise((resolve, reject) => {
    let p;
    try { p = getPort(); }
    catch (e) { reject(e); return; }
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      dropPort("native host timed out after " + HOST_TIMEOUT_MS + " ms");
      reject(new Error("Native host timed out — check: python3 host/dusky_template_host.py --selftest"));
    }, HOST_TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    try { p.postMessage({ ...request, __id: id }); }
    catch (e) {
      pending.delete(id);
      clearTimeout(timer);
      dropPort("post failed");
      reject(e);
    }
    armIdle();
  });
  const job = queue.then(run, run);
  queue = job.then(() => undefined, () => undefined);
  return job;
}

/* ── Helpers ─────────────────────────────────────────────────────────── */
function siteOf(url) {
  try {
    const u = new URL(url);
    return /^https?:$/.test(u.protocol) ? u.hostname.replace(/^www\./, "") : "";
  } catch { return ""; }
}

function explain(err) {
  const m = String(err?.message ?? err);
  if (/No such native application|not found/i.test(m)) {
    return "Native host not registered — run  python3 setup.py  in the extension folder, then reload the extension.";
  }
  if (/timed out/i.test(m)) return m;
  if (/disconnected|exited|unexpected error/i.test(m)) {
    return "Native host crashed — run  python3 host/dusky_template_host.py --selftest";
  }
  if (/Missing host permission|not allowed on this page|restricted|cannot access/i.test(m)) {
    return "Firefox does not allow extensions here (about:, addons.mozilla.org, PDF viewer, view-source:).";
  }
  if (/Receiving end does not exist|Could not establish connection/i.test(m)) {
    return "The page reloaded — reopen the popup.";
  }
  return m;
}

async function page(tabId, msg) {
  try {
    return await browser.tabs.sendMessage(tabId, msg);
  } catch {
    await browser.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return browser.tabs.sendMessage(tabId, msg);
  }
}

/* ── Message router ──────────────────────────────────────────────────── */
browser.runtime.onMessage.addListener((msg, sender) => {
  if (typeof msg?.type !== "string") return false;

  let job;
  if (msg.type === "page" && !sender.tab) {
    job = page(msg.tabId, msg.msg);
  } else if (HOST_OPS.has(msg.type)) {
    /* Tab-originated: domain is forced from sender.url, never trusted. */
    if (sender.tab) {
      const domain = siteOf(sender.url);
      if (!domain) return Promise.resolve({ ok: false, error: "This page has no themeable domain." });
      job = hostCall({ ...msg, domain });
    } else {
      job = hostCall(msg);
    }
  } else {
    return false;
  }

  return job.then(
    (reply) => (reply && typeof reply === "object" ? reply : { ok: false, error: "Empty reply from native host" }),
    (err) => ({ ok: false, error: explain(err) })
  );
});

/* ── Keyboard command (FINDING 7) ────────────────────────────────────── */
browser.commands.onCommand.addListener(async (command) => {
  if (command !== "toggle-picker") return;
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab || !siteOf(tab.url)) return;
  try {
    /* Fast path: content.js already present from a previous popup use. */
    await browser.tabs.sendMessage(tab.id, { type: "picker" });
  } catch {
    try {
      /* A custom command does NOT carry an activeTab grant in Gecko; this
       * succeeds only if the user already granted the tab. Otherwise we
       * surface the popup so the grant can be obtained with one click. */
      await browser.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      await browser.tabs.sendMessage(tab.id, { type: "picker" });
    } catch {
      await browser.action.openPopup().catch(() => {});
    }
  }
});

/* Tab navigation invalidates any in-page picker state. */
browser.tabs.onUpdated.addListener((_tabId, change) => {
  if (change.status === "loading") armIdle();
}, { properties: ["status"] });
