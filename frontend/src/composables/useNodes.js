import { computed, reactive, ref } from "vue";
import { nodesApi } from "../api/nodes";

const nodes = ref([]);
const streams = ref([]);
const loading = ref(false);
const error = ref("");
const lastUpdatedAt = ref(0);
const serverTimeOffsetMs = ref(0);
const autoRefresh = ref(true);
const nowMs = ref(Date.now());
const reconnecting = reactive({});

let _pollTimer = null;
let _tickTimer = null;
let _pollConsumers = 0;

function _clearTimers() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
  if (_tickTimer) {
    clearInterval(_tickTimer);
    _tickTimer = null;
  }
}

export function useNodes() {
  const totalNodes = computed(() => nodes.value.length);
  const onlineNodes = computed(() => nodes.value.filter((n) => n.online).length);
  const offlineNodes = computed(() => nodes.value.filter((n) => !n.online).length);
  const totalDevices = computed(() =>
    nodes.value.reduce((acc, n) => acc + (Number(n.device_count) || 0), 0),
  );
  const activeStreams = computed(() => streams.value.filter((s) => s.streaming).length);
  const avgLatencyMs = computed(() => {
    const rtts = nodes.value
      .filter((n) => n.online && n.url !== "local" && typeof n.latency_ms === "number")
      .map((n) => n.latency_ms);
    if (!rtts.length) return null;
    const sum = rtts.reduce((a, b) => a + b, 0);
    return Math.round((sum / rtts.length) * 10) / 10;
  });

  function retryInSec(node) {
    const base = Number(node?.retry_in_sec || 0);
    if (!base || node?.online || !lastUpdatedAt.value) return 0;
    const elapsedSec = Math.max(0, (nowMs.value - lastUpdatedAt.value) / 1000);
    return Math.max(0, Math.ceil((base - elapsedSec) * 10) / 10);
  }

  async function refresh(silent = false) {
    if (!silent) loading.value = true;
    try {
      const data = await nodesApi.list();
      nodes.value = data?.nodes || [];
      streams.value = data?.streams || [];
      error.value = "";
      const fetchedAt = Date.now();
      lastUpdatedAt.value = fetchedAt;
      nowMs.value = fetchedAt;
      if (typeof data?.server_time === "number") {
        serverTimeOffsetMs.value = data.server_time * 1000 - fetchedAt;
      }
      return data;
    } catch (e) {
      error.value = e?.message || "Failed to load nodes";
      return null;
    } finally {
      if (!silent) loading.value = false;
    }
  }

  async function reconnect(nodeId) {
    if (!nodeId || reconnecting[nodeId]) return null;
    reconnecting[nodeId] = true;
    try {
      const res = await nodesApi.reconnect(nodeId);
      await refresh(true);
      return res?.node || null;
    } finally {
      reconnecting[nodeId] = false;
    }
  }

  function startPolling(intervalMs = 4000) {
    _pollConsumers += 1;
    if (_pollTimer) return;
    nowMs.value = Date.now();
    _tickTimer = setInterval(() => {
      nowMs.value = Date.now();
    }, 1000);
    _pollTimer = setInterval(() => {
      if (!autoRefresh.value) return;
      if (typeof document !== "undefined" && document.hidden) return;
      refresh(true);
    }, intervalMs);
  }

  function stopPolling() {
    _pollConsumers = Math.max(0, _pollConsumers - 1);
    if (_pollConsumers === 0) _clearTimers();
  }

  return {
    nodes,
    streams,
    loading,
    error,
    lastUpdatedAt,
    serverTimeOffsetMs,
    autoRefresh,
    nowMs,
    reconnecting,
    totalNodes,
    onlineNodes,
    offlineNodes,
    totalDevices,
    activeStreams,
    avgLatencyMs,
    retryInSec,
    refresh,
    reconnect,
    startPolling,
    stopPolling,
  };
}
