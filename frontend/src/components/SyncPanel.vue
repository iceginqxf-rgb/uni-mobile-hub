<template>
  <div class="sync-view">
    <div class="card sync-card">
      <div class="row between wrap" style="margin-bottom: 12px">
        <div>
          <strong>{{ t("sync.title") }}</strong>
          <div class="muted" style="font-size: 0.8rem">{{ t("sync.subtitle") }}</div>
        </div>
        <div class="row" style="gap: 8px">
          <button v-if="hasGroups" class="ghost" :disabled="saving" @click="onClearAll">
            {{ t("sync.clearAll") }}
          </button>
          <button class="primary" :disabled="!canSave || saving" @click="onSave">
            {{ t("sync.save") }}
          </button>
        </div>
      </div>

      <div v-if="devices.length < 2" class="muted" style="padding: 12px 0">
        {{ t("sync.needTwoDevices") }}
      </div>

      <template v-else>
        <div class="sync-columns">
          <div class="sync-col">
            <label class="muted">{{ t("sync.master") }}</label>
            <div class="sync-list">
              <button
                v-for="d in devices"
                :key="d.udid"
                type="button"
                class="sync-item"
                :class="{ active: master === d.udid }"
                @click="selectMaster(d.udid)"
              >
                <span class="os-badge" :class="d.platform === 'android' ? 'android' : 'ios'">
                  {{ d.platform === "android" ? "AND" : "iOS" }}
                </span>
                <span class="sync-name">{{ d.label || d.name || d.udid }}</span>
                <span class="muted" style="font-size: 0.72rem">{{ d.screen_width || "?" }}×{{ d.screen_height || "?" }}</span>
              </button>
            </div>
          </div>

          <div class="sync-col">
            <div class="row between" style="margin-bottom: 6px">
              <label class="muted">{{ t("sync.slaves") }}</label>
              <button type="button" class="ghost" style="padding: 2px 8px; font-size: 0.76rem" @click="selectAllSlaves">
                {{ t("sync.selectAll") }}
              </button>
            </div>
            <div class="sync-list">
              <label
                v-for="d in slaveCandidates"
                :key="d.udid"
                class="sync-item sync-check"
                :class="{ active: selectedSlaves.includes(d.udid) }"
              >
                <input
                  type="checkbox"
                  :value="d.udid"
                  v-model="selectedSlaves"
                />
                <span class="os-badge" :class="d.platform === 'android' ? 'android' : 'ios'">
                  {{ d.platform === "android" ? "AND" : "iOS" }}
                </span>
                <span class="sync-name">{{ d.label || d.name || d.udid }}</span>
                <span class="muted" style="font-size: 0.72rem">{{ d.screen_width || "?" }}×{{ d.screen_height || "?" }}</span>
              </label>
            </div>
          </div>
        </div>
      </template>

      <div v-if="hasGroups" class="block" style="margin-top: 16px">
        <label class="muted">{{ t("sync.activeGroups") }}</label>
        <div class="sync-groups">
          <div v-for="(slaves, m) in groups" :key="m" class="sync-group-row">
            <div>
              <strong>{{ labelFor(m) }}</strong>
              <span class="muted"> → {{ slaves.map(labelFor).join(", ") }}</span>
            </div>
            <button class="ghost" style="padding: 3px 10px" :disabled="saving" @click="onRemoveGroup(m)">
              {{ t("sync.remove") }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { syncApi } from "../api/sync";
import { useDevices } from "../composables/useDevices";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const { devices } = useDevices();
const { push: pushToast } = useToast();
const { t } = useUiI18n();

const groups = ref({});
const master = ref("");
const selectedSlaves = ref([]);
const saving = ref(false);

const hasGroups = computed(() => Object.keys(groups.value).length > 0);
const slaveCandidates = computed(() => devices.value.filter((d) => d.udid !== master.value));
const canSave = computed(() => !!master.value && selectedSlaves.value.length > 0);

function labelFor(udid) {
  const dev = devices.value.find((d) => d.udid === udid);
  return dev ? `${dev.label || dev.name || udid} (${dev.platform === "android" ? "AND" : "iOS"})` : udid;
}

function selectMaster(udid) {
  master.value = udid;
  selectedSlaves.value = (groups.value[udid] || []).filter((s) => s !== udid);
}

function selectAllSlaves() {
  selectedSlaves.value = slaveCandidates.value.map((d) => d.udid);
}

async function refresh() {
  try {
    const res = await syncApi.status();
    groups.value = res?.groups || {};
    if (!master.value && devices.value.length) {
      const existingMaster = Object.keys(groups.value)[0];
      selectMaster(existingMaster || devices.value[0].udid);
    }
  } catch {
    /* ignore */
  }
}

async function onSave() {
  if (!canSave.value) return;
  saving.value = true;
  try {
    const res = await syncApi.setGroup(master.value, selectedSlaves.value);
    groups.value = res?.groups || {};
    pushToast(t("sync.saved"), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  } finally {
    saving.value = false;
  }
}

async function onRemoveGroup(m) {
  saving.value = true;
  try {
    const res = await syncApi.clearGroup(m);
    groups.value = res?.groups || {};
    if (m === master.value) selectedSlaves.value = [];
    pushToast(t("sync.cleared"), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  } finally {
    saving.value = false;
  }
}

async function onClearAll() {
  saving.value = true;
  try {
    const res = await syncApi.clearAll();
    groups.value = res?.groups || {};
    selectedSlaves.value = [];
    pushToast(t("sync.cleared"), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  } finally {
    saving.value = false;
  }
}

watch(devices, (list) => {
  if (!master.value && list.length) {
    selectMaster(list[0].udid);
  }
});

onMounted(refresh);
</script>

<style scoped>
.sync-view { max-width: 920px; }
.sync-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 700px) { .sync-columns { grid-template-columns: 1fr; } }
.sync-col label { display: block; margin-bottom: 6px; font-size: 0.82rem; }
.sync-list { display: flex; flex-direction: column; gap: 6px; }
.sync-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface);
  color: inherit; text-align: left; cursor: pointer;
}
.sync-item.active { border-color: var(--accent); background: rgba(79, 124, 255, 0.12); }
.sync-name { flex: 1; font-size: 0.86rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.os-badge { font-size: 0.68rem; padding: 1px 6px; border-radius: 999px; font-weight: 700; }
.os-badge.android { background: rgba(52, 199, 89, 0.16); color: #34c759; }
.os-badge.ios { background: rgba(79, 124, 255, 0.16); color: #6ea2ff; }
.sync-groups { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.sync-group-row {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
}
</style>
