<template>
  <Teleport to="body">
    <div class="ts-backdrop" role="dialog" aria-modal="true" :aria-label="t('taskSwitcher.title')" @click.self="$emit('close')">
      <div class="ts-modal">
        <header class="ts-head">
          <div class="ts-title-wrap">
            <strong>{{ t("taskSwitcher.title") }}</strong>
            <span class="muted ts-hint">{{ t("taskSwitcher.hint") }}</span>
          </div>
          <div class="row" style="gap: 6px">
            <button class="ts-icon-btn" :title="t('taskSwitcher.refresh')" :disabled="activeLoading" @click="refreshActive">↻</button>
            <button class="ts-icon-btn" :title="t('detail.close')" :aria-label="t('detail.close')" @click="$emit('close')">✕</button>
          </div>
        </header>

        <div class="ts-toolbar">
          <div class="ts-tabs" role="tablist">
            <button class="ts-tab" :class="{ active: mode === 'running' }" role="tab" :aria-selected="mode === 'running'" @click="switchMode('running')">
              <span>{{ t("taskSwitcher.running") }}</span>
              <span class="ts-badge">{{ runningApps.length }}</span>
            </button>
            <button class="ts-tab" :class="{ active: mode === 'all' }" role="tab" :aria-selected="mode === 'all'" @click="switchMode('all')">
              <span>{{ t("taskSwitcher.allApps") }}</span>
              <span v-if="allLoaded" class="ts-badge">{{ allApps.length }}</span>
            </button>
          </div>

          <div class="ts-filters">
            <input v-model.trim="query" type="search" class="ts-search" :placeholder="t('taskSwitcher.search')" />
            <label v-if="mode === 'running'" class="ts-check">
              <input v-model="showSystem" type="checkbox" @change="loadRunning" />
              <span>{{ t("taskSwitcher.showSystem") }}</span>
            </label>
          </div>
        </div>

        <p v-if="err" class="banner err ts-err">{{ err }}</p>

        <div class="ts-body">
          <p v-if="activeLoading && !filtered.length" class="muted ts-empty">{{ t("taskSwitcher.loading") }}</p>
          <p v-else-if="!filtered.length" class="muted ts-empty">{{ t("taskSwitcher.empty") }}</p>

          <div v-else class="ts-list">
            <div v-for="app in filtered" :key="app.bundle_id" class="ts-row" :class="{ foreground: app.foreground }">
              <div class="ts-meta">
                <div class="ts-name-line">
                  <span class="ts-name">{{ app.name }}</span>
                  <span v-if="app.foreground" class="pill on">{{ t("taskSwitcher.foreground") }}</span>
                  <span v-if="app.pid" class="ts-pid mono">#{{ app.pid }}</span>
                </div>
                <div class="ts-bundle mono muted">{{ app.bundle_id }}</div>
              </div>
              <div class="ts-actions">
                <button class="primary ts-btn" :disabled="busyId === app.bundle_id" @click="activate(app)">
                  {{ t("taskSwitcher.switch") }}
                </button>
                <button
                  v-if="mode === 'running'"
                  class="danger ts-btn"
                  :disabled="busyId === app.bundle_id"
                  @click="closeApp(app)"
                >
                  {{ t("taskSwitcher.closeApp") }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <footer class="ts-foot">
          <button @click="goHome">{{ t("control.home") }}</button>
          <button @click="toggleAssistiveTouch">{{ t("taskSwitcher.assistiveTouch") }}</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { appsApi } from "../api/apps";
import { useControl } from "../composables/useControl";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({ udid: { type: String, required: true } });
const emit = defineEmits(["close"]);

const { t } = useUiI18n();
const { push: toast } = useToast();
const ctrl = useControl(props.udid);

const mode = ref("running");
const query = ref("");
const showSystem = ref(false);
const runningApps = ref([]);
const allApps = ref([]);
const allLoaded = ref(false);
const loadingRunning = ref(false);
const loadingAll = ref(false);
const busyId = ref("");
const err = ref("");

const activeLoading = computed(() => (mode.value === "running" ? loadingRunning.value : loadingAll.value));

const filtered = computed(() => {
  const list = mode.value === "running" ? runningApps.value : allApps.value;
  const q = query.value.toLowerCase();
  if (!q) return list;
  return list.filter(
    (a) =>
      (a.name || "").toLowerCase().includes(q) ||
      (a.bundle_id || "").toLowerCase().includes(q),
  );
});

async function loadRunning() {
  loadingRunning.value = true;
  err.value = "";
  try {
    const res = await appsApi.running(props.udid, showSystem.value);
    runningApps.value = res.apps || res.data?.apps || [];
  } catch (e) {
    err.value = e.message || t("errors.generic");
  } finally {
    loadingRunning.value = false;
  }
}

async function loadAll() {
  loadingAll.value = true;
  err.value = "";
  try {
    const res = await appsApi.list(props.udid);
    allApps.value = res.apps || res.data?.apps || [];
    allLoaded.value = true;
  } catch (e) {
    err.value = e.message || t("errors.generic");
  } finally {
    loadingAll.value = false;
  }
}

function switchMode(next) {
  mode.value = next;
  if (next === "all" && !allLoaded.value) loadAll();
}

function refreshActive() {
  if (mode.value === "running") loadRunning();
  else loadAll();
}

async function activate(app) {
  busyId.value = app.bundle_id;
  err.value = "";
  try {
    await ctrl.launch(app.bundle_id);
    if (ctrl.error.value) {
      err.value = ctrl.error.value;
      return;
    }
    toast(`${t("toast.launched")} · ${app.name}`);
    emit("close");
  } finally {
    busyId.value = "";
  }
}

async function closeApp(app) {
  busyId.value = app.bundle_id;
  err.value = "";
  try {
    await ctrl.terminate(app.bundle_id);
    if (ctrl.error.value) {
      err.value = ctrl.error.value;
      return;
    }
    runningApps.value = runningApps.value.filter((item) => item.bundle_id !== app.bundle_id);
    toast(`${t("toast.terminated")} · ${app.name}`);
    loadRunning();
  } finally {
    busyId.value = "";
  }
}

async function goHome() {
  await ctrl.pressButton("home");
  if (ctrl.error.value) {
    err.value = ctrl.error.value;
    return;
  }
  emit("close");
}

async function toggleAssistiveTouch() {
  const r = await ctrl.accessibility("assistivetouch", "toggle");
  if (ctrl.error.value) {
    err.value = ctrl.error.value;
    return;
  }
  if (r) toast(`${t("taskSwitcher.assistiveTouch")} · ${r.enabled ? t("quick.on") : t("quick.off")}`);
}

function onKeyDown(ev) {
  if (ev.key === "Escape") emit("close");
}

watch(
  () => props.udid,
  () => {
    allLoaded.value = false;
    allApps.value = [];
    loadRunning();
  },
  { immediate: true },
);

onMounted(() => window.addEventListener("keydown", onKeyDown));
onUnmounted(() => window.removeEventListener("keydown", onKeyDown));
</script>

<style scoped>
.ts-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(2, 6, 23, 0.56);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.ts-modal {
  width: min(560px, 100%);
  max-height: min(82vh, 720px);
  display: flex;
  flex-direction: column;
  background: var(--panel-solid);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.ts-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.ts-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ts-hint {
  font-size: 0.78rem;
}
.ts-icon-btn {
  min-height: 30px;
  width: 30px;
  padding: 0;
  font-size: 0.9rem;
}
.ts-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px 10px;
  border-bottom: 1px solid var(--border);
}
.ts-tabs {
  display: flex;
  gap: 6px;
}
.ts-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-size: 0.84rem;
}
.ts-tab.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
  font-weight: 600;
}
.ts-badge {
  font-size: 0.74rem;
  opacity: 0.85;
}
.ts-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ts-search {
  flex: 1 1 200px;
  min-width: 0;
}
.ts-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
}
.ts-err {
  margin: 10px 16px 0;
}
.ts-body {
  flex: 1;
  overflow: auto;
  padding: 12px 16px;
}
.ts-empty {
  text-align: center;
  padding: 28px 12px;
  font-size: 0.88rem;
}
.ts-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ts-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel);
}
.ts-row.foreground {
  border-color: var(--primary);
}
.ts-meta {
  min-width: 0;
  flex: 1;
}
.ts-name-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ts-name {
  font-weight: 600;
  font-size: 0.92rem;
}
.ts-pid {
  font-size: 0.72rem;
  color: var(--muted);
}
.ts-bundle {
  font-size: 0.74rem;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ts-actions {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}
.ts-btn {
  min-height: 30px;
  padding: 4px 10px;
  font-size: 0.8rem;
}
.ts-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}
</style>
