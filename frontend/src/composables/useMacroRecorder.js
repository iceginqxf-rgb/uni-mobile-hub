import { computed, ref } from "vue";
import { replayApi } from "../api/replay";

const STORAGE_KEY = "umh-macros-v1";
const MAX_SAVED = 30;
const round4 = (v) => Math.round(Number(v) * 10000) / 10000;

function _loadSaved() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function _persistSaved(list) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_SAVED)));
  } catch {
    /* ignore */
  }
}

const recordingUdid = ref("");
const draftName = ref("");
const steps = ref([]);
const savedMacros = ref(_loadSaved());
const activeJob = ref(null);
const running = computed(() => activeJob.value?.status === "running");

let _lastStepAt = 0;
let _pollTimer = null;

function _stopPoll() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

function _sanitizeStep(raw) {
  if (!raw || typeof raw !== "object") return null;
  const type = String(raw.type || "").trim().toLowerCase();
  const delay_ms = Math.max(0, Math.min(60000, Math.round(Number(raw.delay_ms || 0))));
  const clamp01 = (n) => round4(Math.max(0, Math.min(1, Number(n))));
  if (type === "tap" || type === "doubletap") {
    if (raw.nx === undefined || raw.ny === undefined) return null;
    return { type, nx: clamp01(raw.nx), ny: clamp01(raw.ny), delay_ms };
  }
  if (type === "longpress") {
    if (raw.nx === undefined || raw.ny === undefined) return null;
    const duration = Math.max(0.1, Math.min(10, Number(raw.duration || 0.8)));
    return { type, nx: clamp01(raw.nx), ny: clamp01(raw.ny), duration: round4(duration), delay_ms };
  }
  if (type === "swipe") {
    if ([raw.nx1, raw.ny1, raw.nx2, raw.ny2].some((v) => v === undefined)) return null;
    const duration = Math.max(0.05, Math.min(10, Number(raw.duration || 0.3)));
    return {
      type,
      nx1: clamp01(raw.nx1),
      ny1: clamp01(raw.ny1),
      nx2: clamp01(raw.nx2),
      ny2: clamp01(raw.ny2),
      duration: round4(duration),
      delay_ms,
    };
  }
  if (type === "button" || type === "key") {
    const name = String(raw.name || "").trim().toLowerCase();
    if (!name) return null;
    return { type, name, delay_ms };
  }
  if (type === "text") {
    const text = String(raw.text ?? "");
    if (!text) return null;
    return { type, text, delay_ms };
  }
  if (type === "wait") {
    const duration_ms = Math.max(0, Math.min(60000, Math.round(Number(raw.duration_ms ?? 1000))));
    return { type, duration_ms, delay_ms };
  }
  return null;
}

export function recordAction(udid, step) {
  if (!udid || recordingUdid.value !== udid) return;
  const now = performance.now();
  const delay_ms = _lastStepAt > 0 ? Math.min(10000, Math.max(0, Math.round(now - _lastStepAt))) : 0;
  _lastStepAt = now;
  const clean = _sanitizeStep({ ...step, delay_ms });
  if (clean && steps.value.length < 500) {
    steps.value = [...steps.value, clean];
  }
}

export function useMacroRecorder() {
  function startRecording(udid) {
    if (!udid) return;
    recordingUdid.value = udid;
    _lastStepAt = performance.now();
  }

  function stopRecording() {
    recordingUdid.value = "";
    _lastStepAt = 0;
  }

  function addWait(durationMs = 1000) {
    const clean = _sanitizeStep({ type: "wait", duration_ms: durationMs, delay_ms: 0 });
    if (clean && steps.value.length < 500) {
      steps.value = [...steps.value, clean];
    }
  }

  function removeStep(idx) {
    steps.value = steps.value.filter((_, i) => i !== idx);
  }

  function clearSteps() {
    steps.value = [];
  }

  function saveMacro(name) {
    if (!steps.value.length) return null;
    const cleanName = String(name || draftName.value || "").trim() || `Macro ${new Date().toLocaleTimeString([], { hour12: false })}`;
    const entry = {
      id: `m-${Date.now().toString(36)}`,
      name: cleanName,
      createdAt: Date.now(),
      steps: steps.value.map((s) => ({ ...s })),
    };
    savedMacros.value = [entry, ...savedMacros.value].slice(0, MAX_SAVED);
    _persistSaved(savedMacros.value);
    draftName.value = cleanName;
    return entry;
  }

  function loadMacro(id) {
    const found = savedMacros.value.find((m) => m.id === id);
    if (!found) return false;
    stopRecording();
    draftName.value = found.name;
    steps.value = found.steps.map(_sanitizeStep).filter(Boolean);
    return true;
  }

  function deleteMacro(id) {
    savedMacros.value = savedMacros.value.filter((m) => m.id !== id);
    _persistSaved(savedMacros.value);
  }

  function exportJson() {
    if (!steps.value.length) return;
    const payload = {
      schema: "uni-mobile-hub/macro-v1",
      name: draftName.value || "macro",
      exported_at: new Date().toISOString(),
      steps: steps.value,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const slug = (draftName.value || "macro").replace(/[^A-Za-z0-9._-]+/g, "-") || "macro";
    a.href = url;
    a.download = `${slug}.macro.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function importJson(text) {
    const data = JSON.parse(text);
    const rawList = Array.isArray(data) ? data : data?.steps;
    if (!Array.isArray(rawList) || !rawList.length) {
      throw new Error("Invalid macro JSON: missing steps array");
    }
    const clean = rawList.map(_sanitizeStep).filter(Boolean);
    if (!clean.length) {
      throw new Error("Macro JSON contains no valid steps");
    }
    stopRecording();
    if (!Array.isArray(data) && data?.name) draftName.value = String(data.name);
    steps.value = clean.slice(0, 500);
    return clean.length;
  }

  async function runReplay({ targets, speed = 1.0, loops = 1, name = "" }) {
    if (!steps.value.length || !targets?.length) return null;
    stopRecording();
    _stopPoll();
    const res = await replayApi.run({
      targets,
      steps: steps.value,
      speed: Number(speed) || 1.0,
      loops: Number(loops) || 1,
      name: name || draftName.value || "",
    });
    activeJob.value = res?.job || null;
    if (activeJob.value?.id && activeJob.value.status === "running") {
      _pollTimer = setInterval(async () => {
        try {
          const cur = await replayApi.getJob(activeJob.value.id);
          if (cur?.job) activeJob.value = cur.job;
          if (!cur?.job || cur.job.status !== "running") {
            _stopPoll();
          }
        } catch {
          _stopPoll();
        }
      }, 400);
    }
    return activeJob.value;
  }

  async function stopReplay() {
    if (!activeJob.value?.id) return;
    _stopPoll();
    const res = await replayApi.stopJob(activeJob.value.id);
    if (res?.job) activeJob.value = res.job;
  }

  return {
    recordingUdid,
    draftName,
    steps,
    savedMacros,
    activeJob,
    running,
    startRecording,
    stopRecording,
    addWait,
    removeStep,
    clearSteps,
    saveMacro,
    loadMacro,
    deleteMacro,
    exportJson,
    importJson,
    runReplay,
    stopReplay,
  };
}
