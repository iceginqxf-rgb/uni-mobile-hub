<template>
  <div class="batch-view">
    <div class="bp-head">
      <div>
        <h2 class="bp-title">{{ t("batch.title") }}</h2>
        <div class="muted bp-sub">{{ t("batch.subtitle") }}</div>
      </div>
      <div class="row" style="gap: 8px">
        <span v-if="runningCount > 0" class="pill warn mono">
          {{ t("batch.runningPill", { n: runningCount }) }}
        </span>
        <button type="button" class="bp-btn" :disabled="loading" @click="refreshJobs(false)">
          {{ loading ? t("nodes.refreshing") : t("nodes.refresh") }}
        </button>
      </div>
    </div>

    <!-- 1. Target Devices & Execution Policy -->
    <section class="card bp-card">
      <div class="bp-bar">
        <strong>{{ t("batch.targetsTitle") }}</strong>
        <div class="row wrap" style="gap: 6px">
          <button type="button" class="ghost bp-btn" @click="selectAll">{{ t("batch.selectAll") }}</button>
          <button type="button" class="ghost bp-btn" @click="selectByPlatform('android')">{{ t("batch.selectAndroid") }}</button>
          <button type="button" class="ghost bp-btn" @click="selectByPlatform('ios')">{{ t("batch.selectIos") }}</button>
          <button type="button" class="ghost bp-btn" @click="selectedTargets = []">{{ t("batch.clearTargets") }}</button>
          <span class="bp-sep" />
          <label class="bp-inline-field">
            <span class="muted">{{ t("batch.modeLabel") }}</span>
            <select v-model="execMode" class="bp-select mono">
              <option value="parallel">{{ t("batch.modeParallel") }}</option>
              <option value="serial">{{ t("batch.modeSerial") }}</option>
            </select>
          </label>
          <label class="bp-inline-field">
            <span class="muted">{{ t("batch.retriesLabel") }}</span>
            <select v-model.number="retries" class="bp-select mono">
              <option :value="0">0</option>
              <option :value="1">1</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
            </select>
          </label>
        </div>
      </div>

      <p v-if="!devices.length" class="muted bp-empty">{{ t("devices.none") }}</p>
      <div v-else class="bp-chips">
        <label
          v-for="d in devices"
          :key="d.udid"
          class="bp-chip"
          :class="{ active: selectedTargets.includes(d.udid) }"
        >
          <input v-model="selectedTargets" type="checkbox" :value="d.udid" />
          <span class="os-badge mono" :class="d.platform === 'android' ? 'android' : 'ios'">
            {{ d.platform === "android" ? "AND" : "iOS" }}
          </span>
          <span class="bp-chip-name">{{ d.marketing || d.name || d.udid }}</span>
          <span class="muted mono bp-chip-node">{{ d.node_id || "local" }}</span>
        </label>
      </div>
    </section>

    <!-- 2. Task Builder -->
    <section class="card bp-card">
      <div class="bp-tabs" role="tablist">
        <button
          type="button"
          class="bp-tab"
          :class="{ active: modeTab === 'install' }"
          @click="modeTab = 'install'"
        >
          {{ t("batch.tabInstall") }}
        </button>
        <button
          type="button"
          class="bp-tab"
          :class="{ active: modeTab === 'workflow' }"
          @click="modeTab = 'workflow'"
        >
          {{ t("batch.tabWorkflow") }}
        </button>
      </div>

      <!-- 2A. Batch APK/IPA Install -->
      <div v-if="modeTab === 'install'" class="bp-builder">
        <div
          class="bp-drop"
          :class="{ drag: dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="onDropPkg"
          @click="pkgInput?.click()"
        >
          <input
            ref="pkgInput"
            type="file"
            accept=".apk,.ipa"
            style="display: none"
            @change="onPickPkg"
          />
          <template v-if="pkgFile">
            <strong class="mono">{{ pkgFile.name }}</strong>
            <span class="muted mono">{{ formatSize(pkgFile.size) }} · {{ pkgExpectedPlatform.toUpperCase() }}</span>
          </template>
          <template v-else>
            <span>{{ t("batch.dropHint") }}</span>
            <span class="muted mono" style="font-size: 0.72rem">.apk / .ipa</span>
          </template>
        </div>

        <div class="bp-row wrap">
          <input
            v-model="installName"
            type="text"
            class="bp-input"
            :placeholder="t('batch.installNamePlaceholder')"
          />
          <button
            v-if="pkgFile"
            type="button"
            class="ghost bp-btn"
            @click="selectByPlatform(pkgExpectedPlatform)"
          >
            {{ t("batch.matchPlatform", { os: pkgExpectedPlatform === 'android' ? 'Android' : 'iOS' }) }}
          </button>
          <button
            type="button"
            class="primary bp-btn"
            :disabled="!pkgFile || !selectedTargets.length || submitting"
            @click="onStartInstall"
          >
            {{ submitting ? t("batch.submitting") : t("batch.startInstall", { n: selectedTargets.length }) }}
          </button>
        </div>
      </div>

      <!-- 2B. Multi-device Agent Workflow -->
      <div v-else class="bp-builder">
        <div class="bp-toolbar wrap">
          <button type="button" class="ghost bp-btn" @click="addQuickStep('tap')">+ Tap</button>
          <button type="button" class="ghost bp-btn" @click="addQuickStep('swipe')">+ Swipe</button>
          <button type="button" class="ghost bp-btn" @click="addQuickStep('home')">+ Home</button>
          <button type="button" class="ghost bp-btn" @click="addQuickStep('back')">+ Back</button>
          <button type="button" class="ghost bp-btn" @click="addQuickStep('wait')">+ Wait 1s</button>
          <button type="button" class="ghost bp-btn" @click="addQuickStep('screenshot')">+ Shot</button>
          <span class="bp-sep" />
          <button
            v-if="macroSteps.length"
            type="button"
            class="ghost bp-btn"
            @click="importFromMacro"
          >
            {{ t("batch.importDraft", { n: macroSteps.length }) }}
          </button>
          <button type="button" class="ghost bp-btn" @click="jsonInput?.click()">{{ t("replay.import") }}</button>
          <input ref="jsonInput" type="file" accept=".json,application/json" style="display: none" @change="onImportJson" />
          <button type="button" class="ghost bp-btn" :disabled="!wfSteps.length" @click="wfSteps = []">
            {{ t("replay.clear") }}
          </button>
        </div>

        <div class="bp-quick-inputs">
          <div class="bp-quick-box">
            <input
              v-model="appIdInput"
              type="text"
              class="bp-input"
              :placeholder="t('batch.appIdPlaceholder')"
            />
            <button type="button" class="ghost bp-btn" :disabled="!appIdInput.trim()" @click="addAppStep('open_app')">
              + {{ t("batch.openApp") }}
            </button>
            <button type="button" class="ghost bp-btn" :disabled="!appIdInput.trim()" @click="addAppStep('close_app')">
              + {{ t("batch.closeApp") }}
            </button>
          </div>
          <div class="bp-quick-box">
            <input
              v-model="textInput"
              type="text"
              class="bp-input"
              :placeholder="t('batch.textPlaceholder')"
            />
            <label class="bp-check-inline">
              <input v-model="textEnter" type="checkbox" />
              <span class="mono" style="font-size: 0.72rem">Enter</span>
            </label>
            <button type="button" class="ghost bp-btn" :disabled="!textInput" @click="addTextStep">
              + {{ t("batch.addText") }}
            </button>
          </div>
        </div>

        <p v-if="!wfSteps.length" class="muted bp-empty">{{ t("batch.emptyWorkflow") }}</p>
        <div v-else class="bp-wf-list">
          <div v-for="(s, idx) in wfSteps" :key="idx" class="bp-wf-row mono">
            <span class="muted" style="min-width: 18px">{{ idx + 1 }}</span>
            <span class="bp-wf-desc">{{ formatStep(s) }}</span>
            <button type="button" class="ghost bp-del" @click="wfSteps = wfSteps.filter((_, i) => i !== idx)">✕</button>
          </div>
        </div>

        <div class="bp-row wrap">
          <input
            v-model="wfName"
            type="text"
            class="bp-input"
            :placeholder="t('batch.wfNamePlaceholder')"
          />
          <button
            type="button"
            class="primary bp-btn"
            :disabled="!wfSteps.length || !selectedTargets.length || submitting"
            @click="onStartWorkflow"
          >
            {{ submitting ? t("batch.submitting") : t("batch.startWorkflow", { n: selectedTargets.length }) }}
          </button>
        </div>
      </div>
    </section>

    <!-- 3. Jobs & Live Aggregated Logs -->
    <section class="bp-monitor">
      <div class="card bp-card bp-jobs-col">
        <div class="bp-bar">
          <strong>{{ t("batch.jobsTitle") }}</strong>
          <span class="muted mono" style="font-size: 0.72rem">{{ jobs.length }}</span>
        </div>
        <p v-if="!jobs.length" class="muted bp-empty">{{ t("batch.emptyJobs") }}</p>
        <div v-else class="bp-job-list">
          <div
            v-for="j in jobs"
            :key="j.id"
            class="bp-job-item"
            :class="{ active: selectedJob?.id === j.id }"
            @click="selectedJobId = j.id"
          >
            <div class="row between" style="gap: 6px">
              <div class="row" style="gap: 6px; min-width: 0">
                <span class="bp-kind mono">{{ j.kind.toUpperCase() }}</span>
                <strong class="bp-job-name">{{ j.name }}</strong>
              </div>
              <span class="pill mono" :class="statusPill(j.status)">{{ j.status }}</span>
            </div>
            <div class="bp-progress">
              <div class="bp-progress-fill" :class="j.status" :style="{ width: j.progress_pct + '%' }" />
            </div>
            <div class="row between muted mono" style="font-size: 0.7rem">
              <span>ok {{ j.ok_targets }}/{{ j.total_targets }} · {{ j.mode }}</span>
              <button
                v-if="j.status === 'running'"
                type="button"
                class="danger bp-mini-stop"
                @click.stop="stopJob(j.id)"
              >
                {{ t("batch.stop") }}
              </button>
              <span v-else>{{ j.progress_pct }}%</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card bp-card bp-detail-col">
        <div class="bp-bar">
          <strong>{{ selectedJob ? selectedJob.name : t("batch.detailTitle") }}</strong>
          <div v-if="selectedJob" class="row" style="gap: 6px">
            <button
              v-if="selectedJob.status === 'running'"
              type="button"
              class="danger bp-btn"
              @click="stopJob(selectedJob.id)"
            >
              {{ t("batch.stop") }}
            </button>
            <button type="button" class="ghost bp-btn" @click="exportJobLog(selectedJob)">
              {{ t("batch.exportLog") }}
            </button>
          </div>
        </div>

        <p v-if="!selectedJob" class="muted bp-empty">{{ t("batch.selectJobHint") }}</p>
        <template v-else>
          <div class="bp-table-wrap">
            <table class="bp-table">
              <thead>
                <tr>
                  <th>{{ t("batch.colDevice") }}</th>
                  <th>{{ t("batch.colStatus") }}</th>
                  <th>{{ t("batch.colAttempts") }}</th>
                  <th>{{ t("batch.colProgress") }}</th>
                  <th>{{ t("batch.colDetail") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(d, udid) in selectedJob.per_device" :key="udid">
                  <td class="bp-td-dev">{{ labelFor(udid) }}</td>
                  <td>
                    <span class="pill mono" :class="devPill(d.status)">{{ d.status }}</span>
                  </td>
                  <td class="mono">{{ d.attempts }}</td>
                  <td class="mono">{{ d.ok_steps }}/{{ d.total_steps }}</td>
                  <td class="mono bp-td-msg" :class="{ err: !!d.error }" :title="d.error || d.detail">
                    {{ d.error || d.detail || "—" }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="bp-logs mono">
            <div v-for="(l, idx) in selectedJob.logs" :key="idx" class="bp-log-line" :class="l.level">
              <span class="muted">[{{ fmtTime(l.ts) }}]</span>
              <span class="bp-log-dev">[{{ l.udid === "hub" ? "HUB" : labelFor(l.udid) }}]</span>
              <span>{{ l.message }}</span>
            </div>
          </div>
        </template>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useBatch } from "../composables/useBatch";
import { useDevices } from "../composables/useDevices";
import { useMacroRecorder } from "../composables/useMacroRecorder";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const { t } = useUiI18n();
const { devices } = useDevices();
const { steps: macroSteps } = useMacroRecorder();
const { push: pushToast } = useToast();
const {
  jobs,
  selectedJobId,
  selectedJob,
  loading,
  submitting,
  runningCount,
  refreshJobs,
  submitInstall,
  submitWorkflow,
  stopJob,
  startPolling,
  stopPolling,
  exportJobLog,
} = useBatch();

const selectedTargets = ref([]);
const execMode = ref("parallel");
const retries = ref(1);
const modeTab = ref("install");

const pkgInput = ref(null);
const pkgFile = ref(null);
const installName = ref("");
const dragOver = ref(false);

const jsonInput = ref(null);
const wfSteps = ref([]);
const wfName = ref("");
const appIdInput = ref("");
const textInput = ref("");
const textEnter = ref(true);

const pkgExpectedPlatform = computed(() => {
  const name = String(pkgFile.value?.name || "").toLowerCase();
  return name.endsWith(".ipa") ? "ios" : "android";
});

watch(
  devices,
  (list) => {
    if (!selectedTargets.value.length && list.length) {
      selectedTargets.value = list.map((d) => d.udid);
    }
  },
  { immediate: true },
);

function selectAll() {
  selectedTargets.value = devices.value.map((d) => d.udid);
}

function selectByPlatform(platform) {
  selectedTargets.value = devices.value.filter((d) => d.platform === platform).map((d) => d.udid);
}

function onPickPkg(ev) {
  const f = ev.target?.files?.[0];
  ev.target.value = "";
  if (f) _acceptPkg(f);
}

function onDropPkg(ev) {
  dragOver.value = false;
  const f = ev.dataTransfer?.files?.[0];
  if (f) _acceptPkg(f);
}

function _acceptPkg(f) {
  const lower = f.name.toLowerCase();
  if (!lower.endsWith(".apk") && !lower.endsWith(".ipa")) {
    pushToast(t("batch.invalidPkg"), "err");
    return;
  }
  pkgFile.value = f;
}

function formatSize(bytes) {
  const mb = Number(bytes || 0) / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round((bytes || 0) / 1024))} KB`;
}

function addQuickStep(kind) {
  if (kind === "tap") wfSteps.value = [...wfSteps.value, { type: "tap", nx: 0.5, ny: 0.5, delay_ms: 0 }];
  else if (kind === "swipe") wfSteps.value = [...wfSteps.value, { type: "swipe", nx1: 0.5, ny1: 0.75, nx2: 0.5, ny2: 0.25, duration: 0.3, delay_ms: 0 }];
  else if (kind === "home" || kind === "back") wfSteps.value = [...wfSteps.value, { type: "button", name: kind, delay_ms: 0 }];
  else if (kind === "wait") wfSteps.value = [...wfSteps.value, { type: "wait", duration_ms: 1000, delay_ms: 0 }];
  else if (kind === "screenshot") wfSteps.value = [...wfSteps.value, { type: "screenshot", delay_ms: 0 }];
}

function addAppStep(type) {
  const app = appIdInput.value.trim();
  if (!app) return;
  wfSteps.value = [...wfSteps.value, { type, app, delay_ms: 0 }];
}

function addTextStep() {
  if (!textInput.value) return;
  wfSteps.value = [...wfSteps.value, { type: "text", text: textInput.value, enter: textEnter.value, delay_ms: 0 }];
  textInput.value = "";
}

function importFromMacro() {
  wfSteps.value = macroSteps.value.map((s) => ({ ...s }));
  pushToast(t("replay.importedToast", { n: wfSteps.value.length }), "ok");
}

async function onImportJson(ev) {
  const f = ev.target?.files?.[0];
  ev.target.value = "";
  if (!f) return;
  try {
    const parsed = JSON.parse(await f.text());
    const arr = Array.isArray(parsed) ? parsed : parsed?.steps;
    if (!Array.isArray(arr) || !arr.length) throw new Error("Missing steps array");
    wfSteps.value = arr.slice(0, 500);
    if (!Array.isArray(parsed) && parsed?.name) wfName.value = String(parsed.name);
    pushToast(t("replay.importedToast", { n: wfSteps.value.length }), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  }
}

function formatStep(s) {
  if (s.type === "tap" || s.type === "doubletap") return `${s.type} (${s.nx}, ${s.ny})`;
  if (s.type === "swipe") return `swipe (${s.nx1},${s.ny1})→(${s.nx2},${s.ny2})`;
  if (s.type === "open_app" || s.type === "close_app") return `${s.type}: ${s.app || s.bundle_id || s.package}`;
  if (s.type === "button" || s.type === "key") return `${s.type}: ${s.name}`;
  if (s.type === "text") return `text: "${String(s.text).slice(0, 22)}"${s.enter ? " ↵" : ""}`;
  if (s.type === "wait") return `wait ${s.duration_ms}ms`;
  return s.type;
}

async function onStartInstall() {
  try {
    await submitInstall({
      file: pkgFile.value,
      targets: selectedTargets.value,
      mode: execMode.value,
      retries: retries.value,
      name: installName.value.trim(),
    });
    pushToast(t("batch.startedToast"), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  }
}

async function onStartWorkflow() {
  try {
    await submitWorkflow({
      targets: selectedTargets.value,
      steps: wfSteps.value,
      mode: execMode.value,
      retries: retries.value,
      name: wfName.value.trim(),
    });
    pushToast(t("batch.startedToast"), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  }
}

function labelFor(udid) {
  const dev = devices.value.find((d) => d.udid === udid);
  return dev?.marketing || dev?.name || udid.slice(0, 12);
}

function statusPill(st) {
  if (st === "completed") return "on";
  if (st === "failed") return "off";
  if (st === "running" || st === "partial" || st === "stopped") return "warn";
  return "";
}

function devPill(st) {
  if (st === "ok") return "on";
  if (st === "failed") return "off";
  if (st === "running" || st === "stopped") return "warn";
  return "";
}

function fmtTime(sec) {
  if (!sec) return "--:--:--";
  return new Date(Number(sec) * 1000).toLocaleTimeString([], { hour12: false });
}

onMounted(() => {
  refreshJobs(false).catch(() => {});
  startPolling();
});

onUnmounted(() => {
  stopPolling();
});
</script>

<style scoped>
.batch-view { display: flex; flex-direction: column; gap: 12px; max-width: 1280px; }
.bp-head {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
  padding-bottom: 10px; border-bottom: 1px solid var(--border);
}
.bp-title { margin: 0; font-size: 1rem; font-weight: 650; color: var(--text-strong); }
.bp-sub { font-size: 0.78rem; margin-top: 2px; }
.bp-card { display: flex; flex-direction: column; gap: 10px; border-radius: 0; }
.bp-bar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 0.84rem; }
.bp-btn { min-height: 28px; padding: 3px 10px; font-size: 0.76rem; border-radius: 0; }
.bp-sep { width: 1px; height: 18px; background: var(--border); margin: 0 2px; }
.bp-inline-field { display: inline-flex; align-items: center; gap: 5px; font-size: 0.74rem; }
.bp-select { min-height: 28px; padding: 2px 6px; font-size: 0.76rem; }
.bp-empty { margin: 4px 0; font-size: 0.78rem; }

.bp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.bp-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 9px; border: 1px solid var(--border); background: var(--inset);
  cursor: pointer; border-radius: 0; font-size: 0.78rem;
}
.bp-chip.active {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--text-strong);
}
.bp-chip-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bp-chip-node { font-size: 0.68rem; }
.os-badge { font-size: 0.62rem; padding: 1px 5px; border-radius: 0; font-weight: 700; }
.os-badge.android { background: rgba(52, 199, 89, 0.16); color: #34c759; }
.os-badge.ios { background: rgba(79, 124, 255, 0.16); color: #6ea2ff; }

.bp-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); }
.bp-tab {
  min-height: 32px; padding: 0 14px; border: none; border-radius: 0;
  background: transparent; color: var(--muted);
  box-shadow: inset 0 -2px 0 transparent;
}
.bp-tab.active { color: var(--text-strong); font-weight: 600; box-shadow: inset 0 -2px 0 var(--primary); }

.bp-builder { display: flex; flex-direction: column; gap: 10px; }
.bp-drop {
  border: 1px dashed var(--border-strong);
  background: var(--inset);
  padding: 18px 14px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  cursor: pointer; font-size: 0.82rem;
}
.bp-drop.drag, .bp-drop:hover { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, transparent); }
.bp-row { display: flex; align-items: center; gap: 8px; }
.bp-input { flex: 1; min-width: 180px; min-height: 28px; padding: 3px 8px; font-size: 0.78rem; }
.bp-toolbar { display: flex; align-items: center; gap: 6px; }
.bp-quick-inputs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 900px) { .bp-quick-inputs { grid-template-columns: 1fr; } }
.bp-quick-box { display: flex; align-items: center; gap: 6px; }
.bp-check-inline { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; }
.bp-wf-list { max-height: 160px; overflow: auto; display: flex; flex-direction: column; gap: 3px; }
.bp-wf-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 8px; border: 1px solid var(--border); background: var(--inset); font-size: 0.74rem;
}
.bp-wf-desc { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bp-del { min-height: 22px; width: 22px; padding: 0; border: none; font-size: 0.72rem; }

.bp-monitor { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 12px; align-items: start; }
@media (max-width: 960px) { .bp-monitor { grid-template-columns: 1fr; } }
.bp-job-list { display: flex; flex-direction: column; gap: 6px; max-height: 440px; overflow: auto; }
.bp-job-item {
  border: 1px solid var(--border); background: var(--inset); padding: 8px 9px;
  display: flex; flex-direction: column; gap: 6px; cursor: pointer;
}
.bp-job-item.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 10%, transparent); }
.bp-kind {
  font-size: 0.62rem; padding: 1px 4px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted); flex: none;
}
.bp-job-name { font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bp-progress { height: 5px; background: var(--panel); border: 1px solid var(--border); overflow: hidden; }
.bp-progress-fill { height: 100%; background: var(--primary); transition: width 0.2s ease; }
.bp-progress-fill.completed { background: var(--ok); }
.bp-progress-fill.partial, .bp-progress-fill.stopped { background: var(--warn); }
.bp-progress-fill.failed { background: var(--danger); }
.bp-mini-stop { min-height: 20px; padding: 0 6px; font-size: 0.68rem; }

.bp-table-wrap { border: 1px solid var(--border); overflow-x: auto; }
.bp-table { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
.bp-table th, .bp-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
.bp-table th { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; background: var(--surface-2); }
.bp-table tbody tr:last-child td { border-bottom: none; }
.bp-td-dev { font-weight: 600; color: var(--text-strong); }
.bp-td-msg { max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: var(--muted); }
.bp-td-msg.err { color: #fca5a5; }

.bp-logs {
  border: 1px solid var(--border); background: var(--inset);
  padding: 8px; max-height: 230px; overflow: auto;
  display: flex; flex-direction: column; gap: 3px; font-size: 0.71rem;
}
.bp-log-line { display: flex; gap: 6px; word-break: break-word; line-height: 1.35; }
.bp-log-line.warn { color: var(--warn); }
.bp-log-line.error { color: #fca5a5; }
.bp-log-dev { color: var(--primary-2); flex: none; }
</style>
