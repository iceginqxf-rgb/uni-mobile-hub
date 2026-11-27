<template>
  <div>
    <div class="matrix-filters">
      <button class="flt" :class="{ active: filter === 'all' }" @click="filter = 'all'">
        {{ t("devices.filterAll") }} ({{ devices.length }})
      </button>
      <button class="flt" :class="{ active: filter === 'android' }" @click="filter = 'android'">
        {{ t("devices.filterAndroid") }} ({{ androidCount }})
      </button>
      <button class="flt" :class="{ active: filter === 'ios' }" @click="filter = 'ios'">
        {{ t("devices.filterIos") }} ({{ iosCount }})
      </button>
    </div>

    <div class="matrix">
      <div v-for="d in filteredDevices" :key="d.udid" class="matrix-tile card">
        <div class="matrix-head">
          <div class="matrix-name">
            <strong>{{ d.marketing || d.name || d.udid.slice(0, 12) }}</strong>
            <span class="muted" style="font-size: 0.72rem">
              <span class="plat-badge" :class="d.platform === 'android' ? 'and' : 'ios'">
                {{ d.platform === 'android' ? 'Android' : 'iOS' }}
              </span>
              <template v-if="d.os_version || d.ios_version"> {{ d.os_version || d.ios_version }}</template>
              <template v-if="d.product_type"> · {{ d.product_type }}</template>
              <span v-if="d.node_id && d.node_id !== 'local'" class="node-badge">{{ d.node_id }}</span>
            </span>
          </div>
          <div class="row" style="gap: 6px">
            <span
              class="pill"
              :class="(d.platform === 'android' ? d.connected : d.wda_running) ? 'on' : 'off'"
            >
              {{ d.platform === 'android' ? 'Scrcpy' : 'WDA' }}
            </span>
            <button class="mx-icon" :title="t('viewMode.expand')" @click="$emit('open', d.udid)">⤢</button>
          </div>
        </div>

        <div class="matrix-body">
          <!-- Controllable (admin, or the normal user who holds this device): the
               live stage with input. -->
          <template v-if="canControl(d.udid)">
            <DeviceStage v-if="d.connected" :udid="d.udid" :connected="true" compact />
            <div v-else class="matrix-connect">
              <button class="primary" :disabled="busy[d.udid]" @click="connectOne(d.udid)">
                {{ busy[d.udid] ? t("detail.connecting") : t("detail.connect") }}
              </button>
            </div>
          </template>

          <!-- Not controllable (a normal user who hasn't claimed this device):
               reservation gate instead of the screen — mirrors Android. They must
               占用 first; control surfaces are never exposed for un-held devices. -->
          <div v-else class="matrix-gate">
            <p class="muted matrix-gate-hint">{{ t("reservation.reserveToControl") }}</p>
            <ReservationCard :udid="d.udid" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onBeforeUnmount, onMounted } from "vue";
import DeviceStage from "./DeviceStage.vue";
import ReservationCard from "./ReservationCard.vue";
import { useDevices } from "../composables/useDevices";
import { useReservations } from "../composables/useReservations";
import { useUiI18n } from "../composables/useUiI18n";
import { useToast } from "../composables/useToast";
import { devicesApi } from "../api/devices";

const props = defineProps({ devices: { type: Array, default: () => [] } });
defineEmits(["open"]);

const { t } = useUiI18n();
const { push: pushToast } = useToast();
const { connect } = useDevices();
const { canControl, fetchReservations } = useReservations();
const busy = reactive({});
const filter = ref("all");

const androidCount = computed(() => props.devices.filter((d) => d.platform === "android").length);
const iosCount = computed(() => props.devices.filter((d) => d.platform !== "android").length);
const filteredDevices = computed(() => {
  if (filter.value === "android") return props.devices.filter((d) => d.platform === "android");
  if (filter.value === "ios") return props.devices.filter((d) => d.platform !== "android");
  return props.devices;
});

// Reservation state drives canControl() per tile — make sure it's loaded.
onMounted(fetchReservations);

// Grid renders every device's screen at once → re-encode CPU = resolution ×
// device count. Drop each iOS device to GRID_SCALING% while in the grid; restore to
// 100% (full, sharp) on exit (single/list view) — best-effort, WDA-live.
const GRID_SCALING = 70;
const setScaling = (d, n) => {
  if (d && d.platform !== "android" && canControl(d.udid)) {
    devicesApi.streamQuality(d.udid, n).catch(() => {});
  }
};

// Apply 70% to already-connected, controllable iOS devices immediately.
props.devices.forEach((d) => { if (d.connected) setScaling(d, GRID_SCALING); });

onBeforeUnmount(() => {
  props.devices.forEach((d) => setScaling(d, 100));
});

async function connectOne(udid) {
  if (busy[udid]) return;
  busy[udid] = true;
  try {
    const dev = await connect(udid);
    setScaling(dev || props.devices.find((x) => x.udid === udid), GRID_SCALING);
  } catch (e) {
    pushToast(e?.message || t("detail.connectFailed"), "err");
  } finally {
    busy[udid] = false;
  }
}
</script>

<style scoped>
.matrix-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.flt {
  min-height: 32px; padding: 4px 12px; border-radius: 999px; font-size: 0.8rem;
  background: var(--panel); border: 1px solid var(--border-strong); color: var(--muted);
}
.flt.active {
  color: var(--text-strong); border-color: rgba(59, 130, 246, 0.55);
  background: rgba(59, 130, 246, 0.16); font-weight: 600;
}
.plat-badge {
  display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 0.68rem;
  font-weight: 600; margin-right: 4px;
}
.plat-badge.and { background: rgba(16, 185, 129, 0.15); color: #34d399; }
.plat-badge.ios { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.node-badge {
  display: inline-block; margin-left: 5px; padding: 1px 6px; border-radius: 999px;
  font-size: 0.68rem; background: rgba(245, 158, 11, 0.15); color: #fbbf24;
}
.matrix { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; align-items: start; }
.matrix-tile { display: flex; flex-direction: column; gap: 10px; }
.matrix-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.matrix-name { display: flex; flex-direction: column; min-width: 0; }
.mx-icon { min-height: 30px; width: 32px; padding: 0; font-size: 0.95rem; }
.matrix-connect { display: flex; align-items: center; justify-content: center; min-height: 280px; }
.matrix-gate { display: flex; flex-direction: column; gap: 10px; justify-content: center; min-height: 280px; }
.matrix-gate-hint { font-size: 0.82rem; text-align: center; margin: 0; }
</style>
