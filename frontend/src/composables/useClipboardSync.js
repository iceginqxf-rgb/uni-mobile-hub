import { ref } from "vue";
import { controlApi } from "../api/control";

const STORAGE_KEY = "umh-clip-sync-v1";

function _loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) || {};
  } catch {
    return {};
  }
}

const saved = _loadState();
const autoSync = ref(Boolean(saved.autoSync));
const autoType = ref(Boolean(saved.autoType));
const busy = ref(false);

function _persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ autoSync: autoSync.value, autoType: autoType.value }),
    );
  } catch {
    /* ignore storage quota errors */
  }
}

async function _writeBrowserClipboard(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      /* fallback for LAN HTTP origins without secure clipboard context */
    }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-9999px";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  try {
    const ok = document.execCommand("copy");
    if (!ok) throw new Error("execCommand copy failed");
  } finally {
    ta.remove();
  }
}

/**
 * Cross-OS browser <-> device clipboard synchronization helper.
 */
export function useClipboardSync() {
  async function pushText(udid, text, { autoTypeOverride } = {}) {
    if (!udid || !text) return null;
    const shouldType = autoTypeOverride ?? autoType.value;
    busy.value = true;
    try {
      await controlApi.setClipboard(udid, text);
      if (shouldType) {
        await controlApi.input(udid, text);
      }
      return { text, typed: Boolean(shouldType) };
    } finally {
      busy.value = false;
    }
  }

  async function pushFromBrowser(udid) {
    if (!udid) return null;
    if (!navigator.clipboard?.readText) {
      const err = new Error("Clipboard read requires HTTPS or localhost permission");
      err.code = "CLIPBOARD_UNAVAILABLE";
      throw err;
    }
    let text = "";
    try {
      text = await navigator.clipboard.readText();
    } catch (e) {
      const err = new Error(e?.message || "Failed to read browser clipboard");
      err.code = "CLIPBOARD_UNAVAILABLE";
      throw err;
    }
    if (!text) {
      const err = new Error("Browser clipboard is empty");
      err.code = "CLIPBOARD_EMPTY";
      throw err;
    }
    return pushText(udid, text);
  }

  async function pullToBrowser(udid) {
    if (!udid) return "";
    busy.value = true;
    try {
      const res = await controlApi.getClipboard(udid);
      const text = res?.text || "";
      if (!text) {
        const err = new Error("Device clipboard is empty");
        err.code = "CLIPBOARD_EMPTY";
        throw err;
      }
      await _writeBrowserClipboard(text);
      return text;
    } finally {
      busy.value = false;
    }
  }

  function setAutoSync(v) {
    autoSync.value = Boolean(v);
    _persist();
  }

  function setAutoType(v) {
    autoType.value = Boolean(v);
    _persist();
  }

  function toggleAutoSync() {
    setAutoSync(!autoSync.value);
    return autoSync.value;
  }

  function toggleAutoType() {
    setAutoType(!autoType.value);
    return autoType.value;
  }

  return {
    autoSync,
    autoType,
    busy,
    pushText,
    pushFromBrowser,
    pullToBrowser,
    setAutoSync,
    setAutoType,
    toggleAutoSync,
    toggleAutoType,
  };
}
