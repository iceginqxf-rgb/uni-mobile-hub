<template>
  <div class="nodes-view">
    <div class="nodes-head">
      <div>
        <h2 class="nodes-title">{{ t("nodes.title") }}</h2>
        <div class="muted nodes-sub">{{ t("nodes.subtitle") }}</div>
      </div>
      <div class="row wrap" style="gap: 8px">
        <span v-if="lastUpdatedAt" class="muted mono nodes-clock">
          {{ t("nodes.updatedAt") }} {{ formatClock(lastUpdatedAt) }}
        </span>
        <button
          type="button"
          class="ghost np-btn"
          :class="{ active: autoRefresh }"
          @click="autoRefresh = !autoRefresh"
        >
          <span class="np-auto-dot" :class="{ live: autoRefresh }" />
          {{ autoRefresh ? t("nodes.autoOn") : t("nodes.autoOff") }}
        </button>
        <button
          type="button"
          class="np-btn"
          :disabled="loading"
          @click="onManualRefresh"
        >
          {{ loading ? t("nodes.refreshing") : t("nodes.refresh") }}
        </button>
      </div>
    </div>

    <div v-if="error" class="banner err">{{ error }}</div>

    <section class="np-kpi-strip" aria-label="cluster summary">
      <div class="np-kpi" :class="{ alert: offlineNodes > 0 }">
        <span class="np-kpi-label">{{ t("nodes.kpiOnline") }}</span>
        <strong class="np-kpi-val mono">{{ onlineNodes }} / {{ totalNodes }}</strong>
      </div>
      <div class="np-kpi">
        <span class="np-kpi-label">{{ t("nodes.kpiDevices") }}</span>
        <strong class="np-kpi-val mono">{{ totalDevices }}</strong>
      </div>
      <div class="np-kpi">
        <span class="np-kpi-label">{{ t("nodes.kpiStreams") }}</span>
        <strong class="np-kpi-val mono">{{ activeStreams }}</strong>
      </div>
      <div class="np-kpi">
        <span class="np-kpi-label">{{ t("nodes.kpiLatency") }}</span>
        <strong class="np-kpi-val mono">{{ avgLatencyMs !== null ? `${avgLatencyMs} ms` : "—" }}</strong>
      </div>
    </section>

    <section class="np-section">
      <div class="np-section-head">
        <strong>{{ t("nodes.nodesSection") }}</strong>
        <span class="muted mono">{{ totalNodes }}</span>
      </div>

      <p v-if="!nodes.length" class="muted np-empty">{{ t("nodes.emptyNodes") }}</p>

      <div v-else class="np-grid">
        <article
          v-for="node in nodes"
          :key="node.id"
          class="card np-card"
          :class="{ down: !node.online }"
        >
          <header class="np-card-head">
            <div class="np-id-wrap">
              <span class="np-dot" :class="node.online ? 'on' : 'off'" />
              <span class="np-id mono">{{ node.id }}</span>
              <span class="np-type mono">{{ String(node.type || "local").toUpperCase() }}</span>
            </div>
            <span class="pill mono" :class="node.online ? 'on' : 'off'">
              {{ node.online ? t("nodes.online") : t("nodes.offline") }}
            </span>
          </header>

          <div v-if="!node.online || node.last_error" class="np-alert">
            <div class="np-alert-top">
              <span class="np-err-badge mono">
                {{ t("nodes.failures") }}: {{ node.consecutive_failures || 0 }}
              </span>
              <span v-if="retryInSec(node) > 0" class="np-retry mono">
                {{ t("nodes.retryIn", { sec: retryInSec(node).toFixed(1) }) }}
              </span>
            </div>
            <div class="np-err-msg mono">
              {{ node.last_error || t("nodes.unreachable") }}
            </div>
          </div>

          <dl class="np-metrics">
            <div class="np-metric-cell">
              <dt>{{ t("nodes.latency") }}</dt>
              <dd class="mono">{{ formatLatency(node) }}</dd>
            </div>
            <div class="np-metric-cell">
              <dt>{{ t("nodes.devices") }}</dt>
              <dd class="mono">{{ node.device_count ?? 0 }}</dd>
            </div>
            <div class="np-metric-cell">
              <dt>{{ t("nodes.endpoint") }}</dt>
              <dd class="mono np-ellipsis" :title="node.url">{{ node.url || "local" }}</dd>
            </div>
            <div class="np-metric-cell">
              <dt>{{ t("nodes.lastOk") }}</dt>
              <dd class="mono">{{ formatLastOk(node) }}</dd>
            </div>
          </dl>

          <footer class="np-card-foot">
            <button
              v-if="node.reconnectable"
              type="button"
              class="np-btn primary-soft"
              :disabled="!!reconnecting[node.id]"
              @click="onReconnect(node.id)"
            >
              {{ reconnecting[node.id] ? t("nodes.reconnecting") : t("nodes.reconnect") }}
            </button>
            <span v-else class="muted mono np-local-tag">{{ t("nodes.localAdapter") }}</span>
          </footer>
        </article>
      </div>
    </section>

    <section class="np-section">
      <div class="np-section-head">
        <strong>{{ t("nodes.streamsSection") }}</strong>
        <span class="muted mono">{{ activeStreams }} / {{ streams.length }}</span>
      </div>

      <p v-if="!streams.length" class="muted np-empty">{{ t("nodes.emptyStreams") }}</p>

      <div v-else class="np-table-wrap">
        <table class="np-table">
          <thead>
            <tr>
              <th>{{ t("nodes.colDevice") }}</th>
              <th>{{ t("nodes.colNode") }}</th>
              <th>{{ t("nodes.colState") }}</th>
              <th>{{ t("nodes.colProvider") }}</th>
              <th>{{ t("nodes.colFps") }}</th>
              <th style="text-align: right">{{ t("nodes.colAction") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in streams" :key="s.udid">
              <td>
                <div class="np-dev-cell">
                  <span class="os-badge mono" :class="s.platform === 'android' ? 'android' : 'ios'">
                    {{ s.platform === "android" ? "AND" : "iOS" }}
                  </span>
                  <span class="np-dev-name">{{ s.name || s.udid }}</span>
                </div>
              </td>
              <td class="mono muted">{{ s.node_id || "local" }}</td>
              <td>
                <span
                  class="pill mono"
                  :class="s.streaming ? 'on' : s.connected ? 'warn' : ''"
                >
                  {{
                    s.streaming
                      ? t("nodes.stateStreaming")
                      : s.connected
                        ? t("nodes.stateConnected")
                        : t("nodes.stateIdle")
                  }}
                </span>
              </td>
              <td class="mono">{{ s.provider || "—" }}</td>
              <td class="mono">
                <template v-if="s.streaming && s.provider === 'scrcpy-webrtc' && (!s.fps || s.fps === 0)">
                  <span class="np-webrtc-tag">WebRTC</span>
                  <span v-if="s.viewers" class="muted" style="margin-left: 6px">({{ s.viewers }})</span>
                </template>
                <template v-else-if="s.streaming">
                  {{ Number(s.fps || 0).toFixed(1) }} fps
                </template>
                <template v-else>—</template>
              </td>
              <td style="text-align: right">
                <button
                  type="button"
                  class="ghost np-btn"
                  @click="$emit('open-device', s.udid)"
                >
                  {{ t("nodes.openDevice") }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from "vue";
import { useNodes } from "../composables/useNodes";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const emit = defineEmits(["open-device", "refresh-devices"]);
const { t } = useUiI18n();
const { push: pushToast } = useToast();
const {
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
} = useNodes();

function formatClock(ms) {
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString([], { hour12: false });
}

function formatLatency(node) {
  if (!node.online || node.latency_ms === null || node.latency_ms === undefined) return "—";
  if (node.url === "local" && Number(node.latency_ms) === 0) return "<1 ms";
  return `${node.latency_ms} ms`;
}

function formatLastOk(node) {
  if (!node.reconnectable && node.url === "local") {
    return node.online ? t("nodes.localReady") : "—";
  }
  if (!node.last_ok_at) return "—";
  const nowSec = (nowMs.value + serverTimeOffsetMs.value) / 1000;
  const diff = Math.max(0, Math.round(nowSec - Number(node.last_ok_at)));
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  return new Date(Number(node.last_ok_at) * 1000).toLocaleTimeString([], { hour12: false });
}

async function onManualRefresh() {
  await refresh(false);
}

async function onReconnect(nodeId) {
  try {
    const res = await reconnect(nodeId);
    emit("refresh-devices");
    if (res?.online) {
      pushToast(t("nodes.reconnectOk", { id: nodeId }), "ok");
    } else {
      pushToast(res?.last_error || t("nodes.reconnectFail", { id: nodeId }), "err");
    }
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  }
}

onMounted(() => {
  refresh(false);
  startPolling(4000);
});

onUnmounted(() => {
  stopPolling();
});
</script>

<style scoped>
.nodes-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 1240px;
}
.nodes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.nodes-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
  color: var(--text-strong);
}
.nodes-sub { font-size: 0.78rem; margin-top: 2px; }
.nodes-clock { font-size: 0.72rem; }
.np-btn { min-height: 28px; padding: 3px 10px; font-size: 0.76rem; border-radius: 0; }
.np-btn.active {
  color: var(--text-strong);
  border-color: var(--border-strong);
  background: var(--surface-1);
}
.np-btn.primary-soft {
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary-2);
}
.np-btn.primary-soft:hover:not(:disabled) {
  background: var(--primary);
  color: var(--primary-fg);
  border-color: var(--primary);
}
.np-auto-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted);
}
.np-auto-dot.live {
  background: var(--ok);
  box-shadow: 0 0 6px color-mix(in srgb, var(--ok) 65%, transparent);
}

.np-kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
@media (max-width: 780px) {
  .np-kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.np-kpi {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.np-kpi.alert {
  border-color: rgba(239, 68, 68, 0.55);
  background: rgba(239, 68, 68, 0.06);
}
.np-kpi-label {
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.35px;
}
.np-kpi-val {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-strong);
}

.np-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.np-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.84rem;
  color: var(--text-strong);
}
.np-empty {
  padding: 16px;
  border: 1px solid var(--border);
  background: var(--panel);
  margin: 0;
  font-size: 0.82rem;
}

.np-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 10px;
}
.np-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 0;
}
.np-card.down {
  border-color: rgba(239, 68, 68, 0.45);
}
.np-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.np-id-wrap {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
.np-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.np-dot.on { background: var(--ok); }
.np-dot.off { background: var(--danger); }
.np-id {
  font-weight: 700;
  font-size: 0.88rem;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.np-type {
  font-size: 0.66rem;
  padding: 1px 5px;
  border: 1px solid var(--border);
  background: var(--inset);
  color: var(--muted);
  border-radius: 0;
}

.np-alert {
  border: 1px solid rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.08);
  padding: 7px 9px;
  border-radius: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.np-alert-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.7rem;
}
.np-err-badge { color: #fca5a5; font-weight: 600; }
.np-retry { color: #fde047; font-weight: 600; }
.np-err-msg {
  font-size: 0.72rem;
  color: #fca5a5;
  word-break: break-word;
  line-height: 1.35;
}

.np-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}
.np-metric-cell {
  background: var(--inset);
  border: 1px solid var(--border);
  padding: 6px 8px;
  border-radius: 0;
  min-width: 0;
}
.np-metric-cell dt {
  font-size: 0.66rem;
  color: var(--muted);
  margin: 0 0 2px;
}
.np-metric-cell dd {
  margin: 0;
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--text-strong);
}
.np-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.np-card-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-top: 2px;
}
.np-local-tag { font-size: 0.72rem; }

.np-table-wrap {
  border: 1px solid var(--border);
  background: var(--panel);
  overflow-x: auto;
  border-radius: 0;
}
.np-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.np-table th,
.np-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}
.np-table th {
  font-size: 0.7rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
  background: var(--surface-2);
}
.np-table tbody tr:last-child td { border-bottom: none; }
.np-dev-cell { display: flex; align-items: center; gap: 7px; }
.np-dev-name { font-weight: 600; color: var(--text-strong); }
.os-badge { font-size: 0.66rem; padding: 1px 5px; border-radius: 0; font-weight: 700; }
.os-badge.android { background: rgba(52, 199, 89, 0.16); color: #34c759; }
.os-badge.ios { background: rgba(79, 124, 255, 0.16); color: #6ea2ff; }
.np-webrtc-tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: 0.7rem;
  font-weight: 600;
  border: 1px solid color-mix(in srgb, var(--primary) 45%, transparent);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary-2);
  border-radius: 0;
}
</style>
