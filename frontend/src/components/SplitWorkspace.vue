<template>
  <div ref="rootEl" class="sp-root" :class="layoutClass">
    <template v-if="panes.length < 2">
      <div class="card sp-empty muted">{{ t("split.needDevices") }}</div>
    </template>

    <!-- 2-pane horizontal split with draggable divider -->
    <template v-else-if="mode === 'split-2'">
      <div
        class="sp-pane"
        :class="{ focused: panes[0] === focusedUdid }"
        :style="{ flex: `0 0 calc(${(ratio * 100).toFixed(2)}% - 3px)` }"
        @pointerdown="$emit('focus', panes[0])"
      >
        <div class="sp-head">
          <div class="sp-head-left">
            <span class="sp-dot" :class="dotClass(panes[0])" />
            <span class="sp-os mono" :class="isAndroid(panes[0]) ? 'and' : 'ios'">
              {{ isAndroid(panes[0]) ? "AND" : "iOS" }}
            </span>
            <select
              class="sp-select"
              :value="panes[0]"
              :aria-label="t('detail.switchDevice')"
              @change="$emit('replace', 0, $event.target.value)"
            >
              <option v-for="d in devices" :key="d.udid" :value="d.udid">
                {{ d.marketing || d.name || d.udid.slice(0, 12) }} ({{ d.platform === 'android' ? 'AND' : 'iOS' }})
              </option>
            </select>
          </div>
          <div class="sp-head-actions">
            <button
              type="button"
              class="sp-sync-btn"
              :class="{ active: isMaster(panes[0]) }"
              :disabled="syncSaving"
              :title="t('split.setMasterHint')"
              @click.stop="toggleMaster(panes[0])"
            >
              {{ t("split.masterBtn") }}
            </button>
            <button
              type="button"
              class="sp-sync-btn slave"
              :class="{ active: isSlave(panes[0]) }"
              :disabled="syncSaving"
              :title="t('split.toggleSlaveHint')"
              @click.stop="onToggleSlave(panes[0])"
            >
              {{ t("split.slaveBtn") }}
            </button>
            <button type="button" class="sp-icon-btn" :title="t('viewMode.expand')" @click.stop="$emit('open-single', panes[0])">⤢</button>
            <button type="button" class="sp-icon-btn" :title="t('split.closePane')" @click.stop="$emit('remove', panes[0])">✕</button>
          </div>
        </div>
        <div class="sp-body">
          <template v-if="canControl(panes[0])">
            <DeviceStage v-if="devOf(panes[0])?.connected" :udid="panes[0]" :connected="true" :fill-pane="true" />
            <div v-else class="sp-gate">
              <button class="primary" :disabled="busy[panes[0]]" @click="connectOne(panes[0])">
                {{ busy[panes[0]] ? t("detail.connecting") : t("detail.connect") }}
              </button>
            </div>
          </template>
          <div v-else class="sp-gate">
            <p class="muted sp-gate-hint">{{ t("reservation.reserveToControl") }}</p>
            <ReservationCard :udid="panes[0]" style="width: min(290px, 100%)" />
          </div>
        </div>
      </div>

      <div
        class="sp-divider"
        :class="{ dragging }"
        role="separator"
        aria-orientation="vertical"
        @pointerdown.prevent="startDrag"
      />

      <div
        class="sp-pane"
        :class="{ focused: panes[1] === focusedUdid }"
        :style="{ flex: '1 1 0' }"
        @pointerdown="$emit('focus', panes[1])"
      >
        <div class="sp-head">
          <div class="sp-head-left">
            <span class="sp-dot" :class="dotClass(panes[1])" />
            <span class="sp-os mono" :class="isAndroid(panes[1]) ? 'and' : 'ios'">
              {{ isAndroid(panes[1]) ? "AND" : "iOS" }}
            </span>
            <select
              class="sp-select"
              :value="panes[1]"
              :aria-label="t('detail.switchDevice')"
              @change="$emit('replace', 1, $event.target.value)"
            >
              <option v-for="d in devices" :key="d.udid" :value="d.udid">
                {{ d.marketing || d.name || d.udid.slice(0, 12) }} ({{ d.platform === 'android' ? 'AND' : 'iOS' }})
              </option>
            </select>
          </div>
          <div class="sp-head-actions">
            <button
              type="button"
              class="sp-sync-btn"
              :class="{ active: isMaster(panes[1]) }"
              :disabled="syncSaving"
              :title="t('split.setMasterHint')"
              @click.stop="toggleMaster(panes[1])"
            >
              {{ t("split.masterBtn") }}
            </button>
            <button
              type="button"
              class="sp-sync-btn slave"
              :class="{ active: isSlave(panes[1]) }"
              :disabled="syncSaving"
              :title="t('split.toggleSlaveHint')"
              @click.stop="onToggleSlave(panes[1])"
            >
              {{ t("split.slaveBtn") }}
            </button>
            <button type="button" class="sp-icon-btn" :title="t('viewMode.expand')" @click.stop="$emit('open-single', panes[1])">⤢</button>
            <button type="button" class="sp-icon-btn" :title="t('split.closePane')" @click.stop="$emit('remove', panes[1])">✕</button>
          </div>
        </div>
        <div class="sp-body">
          <template v-if="canControl(panes[1])">
            <DeviceStage v-if="devOf(panes[1])?.connected" :udid="panes[1]" :connected="true" :fill-pane="true" />
            <div v-else class="sp-gate">
              <button class="primary" :disabled="busy[panes[1]]" @click="connectOne(panes[1])">
                {{ busy[panes[1]] ? t("detail.connecting") : t("detail.connect") }}
              </button>
            </div>
          </template>
          <div v-else class="sp-gate">
            <p class="muted sp-gate-hint">{{ t("reservation.reserveToControl") }}</p>
            <ReservationCard :udid="panes[1]" style="width: min(290px, 100%)" />
          </div>
        </div>
      </div>
    </template>

    <!-- 3-4 pane adaptive multi-grid split -->
    <template v-else>
      <div
        v-for="(udid, idx) in panes"
        :key="udid + '-' + idx"
        class="sp-pane"
        :class="{ focused: udid === focusedUdid }"
        @pointerdown="$emit('focus', udid)"
      >
        <div class="sp-head">
          <div class="sp-head-left">
            <span class="sp-dot" :class="dotClass(udid)" />
            <span class="sp-os mono" :class="isAndroid(udid) ? 'and' : 'ios'">
              {{ isAndroid(udid) ? "AND" : "iOS" }}
            </span>
            <select
              class="sp-select"
              :value="udid"
              :aria-label="t('detail.switchDevice')"
              @change="$emit('replace', idx, $event.target.value)"
            >
              <option v-for="d in devices" :key="d.udid" :value="d.udid">
                {{ d.marketing || d.name || d.udid.slice(0, 12) }} ({{ d.platform === 'android' ? 'AND' : 'iOS' }})
              </option>
            </select>
          </div>
          <div class="sp-head-actions">
            <button
              type="button"
              class="sp-sync-btn"
              :class="{ active: isMaster(udid) }"
              :disabled="syncSaving"
              :title="t('split.setMasterHint')"
              @click.stop="toggleMaster(udid)"
            >
              {{ t("split.masterBtn") }}
            </button>
            <button
              type="button"
              class="sp-sync-btn slave"
              :class="{ active: isSlave(udid) }"
              :disabled="syncSaving"
              :title="t('split.toggleSlaveHint')"
              @click.stop="onToggleSlave(udid)"
            >
              {{ t("split.slaveBtn") }}
            </button>
            <button type="button" class="sp-icon-btn" :title="t('viewMode.expand')" @click.stop="$emit('open-single', udid)">⤢</button>
            <button type="button" class="sp-icon-btn" :title="t('split.closePane')" @click.stop="$emit('remove', udid)">✕</button>
          </div>
        </div>
        <div class="sp-body">
          <template v-if="canControl(udid)">
            <DeviceStage v-if="devOf(udid)?.connected" :udid="udid" :connected="true" :fill-pane="true" />
            <div v-else class="sp-gate">
              <button class="primary" :disabled="busy[udid]" @click="connectOne(udid)">
                {{ busy[udid] ? t("detail.connecting") : t("detail.connect") }}
              </button>
            </div>
          </template>
          <div v-else class="sp-gate">
            <p class="muted sp-gate-hint">{{ t("reservation.reserveToControl") }}</p>
            <ReservationCard :udid="udid" style="width: min(290px, 100%)" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref } from "vue";
import DeviceStage from "./DeviceStage.vue";
import ReservationCard from "./ReservationCard.vue";
import { useDevices } from "../composables/useDevices";
import { useReservations } from "../composables/useReservations";
import { useSync } from "../composables/useSync";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  devices: { type: Array, default: () => [] },
  panes: { type: Array, default: () => [] },
  mode: { type: String, default: "split-2" },
  ratio: { type: Number, default: 0.5 },
  focusedUdid: { type: String, default: "" },
});
const emit = defineEmits(["focus", "replace", "remove", "resize-ratio", "open-single"]);

const { t } = useUiI18n();
const { connect } = useDevices();
const { canControl } = useReservations();
const { saving: syncSaving, isMaster, isSlave, setMaster, toggleSlave } = useSync();
const { push: toast } = useToast();

const rootEl = ref(null);
const busy = reactive({});
const dragging = ref(false);

const layoutClass = computed(() => {
  if (props.mode === "split-2" && props.panes.length >= 2) return "sp-row";
  return props.panes.length <= 2 ? "sp-grid-2" : "sp-grid-4";
});

const devOf = (udid) => props.devices.find((d) => d.udid === udid);
const isAndroid = (udid) => devOf(udid)?.platform === "android";
const dotClass = (udid) => {
  const d = devOf(udid);
  return d && (d.connected || d.streaming) ? "on" : "idle";
};

async function connectOne(udid) {
  if (busy[udid]) return;
  busy[udid] = true;
  try {
    await connect(udid);
  } catch (e) {
    toast(e?.message || t("detail.connectFailed"), "err");
  } finally {
    busy[udid] = false;
  }
}

async function toggleMaster(udid) {
  try {
    const wasMaster = isMaster(udid);
    const others = props.panes.filter((id) => id && id !== udid);
    await setMaster(udid, others);
    toast(wasMaster ? t("sync.cleared") : t("split.masterActive"), "ok");
  } catch (e) {
    toast(e?.message || t("errors.generic"), "err");
  }
}

async function onToggleSlave(udid) {
  try {
    const fallback = props.panes.find((id) => id && id !== udid) || "";
    await toggleSlave(udid, fallback);
    toast(t("sync.saved"), "ok");
  } catch (e) {
    toast(e?.message || t("errors.generic"), "err");
  }
}

function onMove(ev) {
  if (!dragging.value || !rootEl.value) return;
  const r = rootEl.value.getBoundingClientRect();
  if (r.width > 0) emit("resize-ratio", (ev.clientX - r.left) / r.width);
}
function onUp() {
  if (!dragging.value) return;
  dragging.value = false;
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("pointerup", onUp);
}
function startDrag() {
  dragging.value = true;
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}
onUnmounted(onUp);
</script>

<style scoped>
.sp-root {
  height: 100%;
  width: 100%;
  min-height: 0;
  overflow: hidden;
}
.sp-row {
  display: flex;
  height: 100%;
  width: 100%;
}
.sp-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: minmax(0, 1fr);
  gap: 8px;
  height: 100%;
}
.sp-grid-4 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
  gap: 8px;
  height: 100%;
}
@media (max-width: 900px) {
  .sp-row, .sp-grid-2, .sp-grid-4 {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-auto-rows: minmax(420px, 1fr);
    overflow: auto;
  }
  .sp-divider { display: none; }
}

.sp-divider {
  width: 6px;
  flex: 0 0 6px;
  cursor: col-resize;
  background: transparent;
  transition: background .12s;
}
.sp-divider:hover, .sp-divider.dragging {
  background: var(--primary);
}

.sp-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 0;
}
.sp-pane.focused {
  border-color: var(--primary);
}

.sp-head {
  height: 34px;
  flex: 0 0 34px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0 6px 0 8px;
  background: var(--panel-solid);
  border-bottom: 1px solid var(--border);
}
.sp-head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.sp-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); flex: none; }
.sp-dot.on { background: var(--ok); }
.sp-os {
  font-size: 0.62rem;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 0;
  flex: none;
}
.sp-os.and { background: rgba(34, 197, 94, 0.14); color: var(--ok); }
.sp-os.ios { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--primary-2); }
.sp-select {
  min-height: 24px;
  height: 24px;
  padding: 0 6px;
  font-size: 0.76rem;
  max-width: 190px;
  min-width: 0;
  flex: 1;
  border-radius: 0;
}

.sp-head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}
.sp-sync-btn {
  min-height: 22px;
  height: 22px;
  padding: 0 7px;
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 0;
  background: var(--inset);
  border: 1px solid var(--border);
  color: var(--muted);
}
.sp-sync-btn.active {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--primary-fg);
}
.sp-sync-btn.slave.active {
  background: rgba(34, 197, 94, 0.18);
  border-color: var(--ok);
  color: var(--ok);
}
.sp-icon-btn {
  min-height: 22px;
  height: 22px;
  width: 22px;
  padding: 0;
  font-size: 0.78rem;
  border-radius: 0;
}

.sp-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 6px;
  overflow: hidden;
}
.sp-gate {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 16px;
}
.sp-gate-hint { margin: 0; font-size: 0.8rem; }
.sp-empty { text-align: center; padding: 32px; }
</style>
