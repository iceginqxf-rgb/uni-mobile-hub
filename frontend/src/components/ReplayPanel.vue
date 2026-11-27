<template>
  <div class="rp-wrap">
    <!-- 1. Trajectory Recorder Controls -->
    <section class="rp-box">
      <div class="rp-head">
        <strong>{{ t("replay.recorderTitle") }}</strong>
        <span class="mono muted rp-count">{{ t("replay.stepCount", { n: steps.length }) }}</span>
      </div>

      <div class="rp-row">
        <button
          type="button"
          class="rp-btn"
          :class="isRecHere ? 'rec-active' : 'primary'"
          @click="toggleRec"
        >
          <span class="rp-dot" :class="{ live: isRecHere }" />
          {{ isRecHere ? t("replay.stopRec") : t("replay.startRec") }}
        </button>
        <button type="button" class="ghost rp-btn" @click="addWait(1000)">+1s</button>
        <button type="button" class="ghost rp-btn" :disabled="!steps.length" @click="clearSteps">
          {{ t("replay.clear") }}
        </button>
      </div>

      <div class="rp-row">
        <input
          v-model="draftName"
          type="text"
          class="rp-input"
          :placeholder="t('replay.namePlaceholder')"
        />
        <button type="button" class="ghost rp-btn" :disabled="!steps.length" @click="onSave">
          {{ t("replay.save") }}
        </button>
      </div>

      <div class="rp-row">
        <button type="button" class="ghost rp-btn" :disabled="!steps.length" @click="exportJson">
          {{ t("replay.export") }}
        </button>
        <button type="button" class="ghost rp-btn" @click="fileInput?.click()">
          {{ t("replay.import") }}
        </button>
        <input ref="fileInput" type="file" accept=".json,application/json" style="display: none" @change="onImportFile" />
      </div>
    </section>

    <!-- 2. Steps List -->
    <section class="rp-box">
      <div class="rp-head">
        <strong>{{ t("replay.stepsTitle") }}</strong>
      </div>
      <p v-if="!steps.length" class="muted rp-empty">{{ t("replay.emptySteps") }}</p>
      <div v-else class="rp-steps">
        <div v-for="(s, idx) in steps" :key="idx" class="rp-step-row mono">
          <span class="rp-step-idx">{{ idx + 1 }}</span>
          <span class="rp-step-desc">{{ formatStep(s) }}</span>
          <span v-if="s.delay_ms" class="muted rp-step-delay">+{{ s.delay_ms }}ms</span>
          <button
            type="button"
            class="ghost rp-del"
            :aria-label="t('replay.removeStep')"
            @click="removeStep(idx)"
          >
            ✕
          </button>
        </div>
      </div>
    </section>

    <!-- 3. Runner & Targets -->
    <section class="rp-box">
      <div class="rp-head">
        <strong>{{ t("replay.runnerTitle") }}</strong>
      </div>

      <div class="rp-row wrap">
        <button
          type="button"
          class="ghost rp-btn"
          :class="{ active: targetMode === 'current' }"
          @click="targetMode = 'current'"
        >
          {{ t("replay.targetCurrent") }}
        </button>
        <button
          v-if="syncTargets.length > 1"
          type="button"
          class="ghost rp-btn"
          :class="{ active: targetMode === 'sync' }"
          @click="targetMode = 'sync'"
        >
          {{ t("replay.targetSync", { n: syncTargets.length }) }}
        </button>
        <button
          v-if="devices.length > 1"
          type="button"
          class="ghost rp-btn"
          :class="{ active: targetMode === 'custom' }"
          @click="initCustomTargets"
        >
          {{ t("replay.targetCustom") }}
        </button>
      </div>

      <div v-if="targetMode === 'custom'" class="rp-targets">
        <label v-for="d in devices" :key="d.udid" class="rp-target-item">
          <input v-model="customTargets" type="checkbox" :value="d.udid" />
          <span class="os-badge mono" :class="d.platform === 'android' ? 'android' : 'ios'">
            {{ d.platform === "android" ? "AND" : "iOS" }}
          </span>
          <span class="rp-target-name">{{ d.marketing || d.name || d.udid }}</span>
        </label>
      </div>

      <div class="rp-row">
        <label class="rp-field">
          <span class="muted">{{ t("replay.speed") }}</span>
          <select v-model.number="speed" class="rp-select mono">
            <option :value="0.5">0.5×</option>
            <option :value="1">1×</option>
            <option :value="1.5">1.5×</option>
            <option :value="2">2×</option>
          </select>
        </label>
        <label class="rp-field">
          <span class="muted">{{ t("replay.loops") }}</span>
          <input v-model.number="loops" type="number" min="1" max="20" class="rp-num mono" />
        </label>
        <span style="flex: 1" />
        <button
          v-if="running"
          type="button"
          class="danger rp-btn"
          @click="stopReplay"
        >
          {{ t("replay.stop") }}
        </button>
        <button
          v-else
          type="button"
          class="primary rp-btn"
          :disabled="!steps.length || !resolvedTargets.length"
          @click="onRun"
        >
          {{ t("replay.run") }}
        </button>
      </div>

      <div v-if="activeJob" class="rp-job">
        <div class="rp-row between mono" style="font-size: 0.72rem">
          <span>
            {{ activeJob.status.toUpperCase() }} · {{ activeJob.current_step }} / {{ activeJob.total_steps }}
          </span>
          <span>{{ activeJob.progress_pct }}%</span>
        </div>
        <div class="rp-progress">
          <div class="rp-progress-fill" :class="activeJob.status" :style="{ width: activeJob.progress_pct + '%' }" />
        </div>
        <div class="rp-dev-stats">
          <div v-for="(st, devId) in activeJob.per_device" :key="devId" class="rp-stat-row mono">
            <span class="rp-stat-name">{{ labelFor(devId) }}</span>
            <span class="rp-ok">ok:{{ st.ok }}</span>
            <span v-if="st.errors" class="rp-err" :title="st.last_error">err:{{ st.errors }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 4. Saved Library -->
    <section v-if="savedMacros.length" class="rp-box">
      <div class="rp-head">
        <strong>{{ t("replay.libraryTitle") }}</strong>
        <span class="mono muted rp-count">{{ savedMacros.length }}</span>
      </div>
      <div class="rp-lib">
        <div v-for="m in savedMacros" :key="m.id" class="rp-lib-row">
          <button type="button" class="ghost rp-lib-load" @click="loadMacro(m.id)">
            <span class="rp-lib-name">{{ m.name }}</span>
            <span class="mono muted" style="font-size: 0.68rem">{{ m.steps.length }}s</span>
          </button>
          <button type="button" class="ghost rp-del" @click="deleteMacro(m.id)">✕</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useDevices } from "../composables/useDevices";
import { useMacroRecorder } from "../composables/useMacroRecorder";
import { useSync } from "../composables/useSync";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  udid: { type: String, required: true },
});

const { t } = useUiI18n();
const { devices } = useDevices();
const { groups } = useSync();
const { push: pushToast } = useToast();
const {
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
} = useMacroRecorder();

const fileInput = ref(null);
const targetMode = ref("current");
const customTargets = ref([]);
const speed = ref(1);
const loops = ref(1);

const isRecHere = computed(() => recordingUdid.value === props.udid);
const syncTargets = computed(() => {
  const slaves = groups.value?.[props.udid] || [];
  return slaves.length ? [props.udid, ...slaves] : [props.udid];
});

const resolvedTargets = computed(() => {
  if (targetMode.value === "sync") return syncTargets.value;
  if (targetMode.value === "custom") return customTargets.value;
  return props.udid ? [props.udid] : [];
});

function initCustomTargets() {
  targetMode.value = "custom";
  if (!customTargets.value.length) customTargets.value = [props.udid];
}

function toggleRec() {
  if (isRecHere.value) stopRecording();
  else startRecording(props.udid);
}

function labelFor(udid) {
  const dev = devices.value.find((d) => d.udid === udid);
  return dev?.marketing || dev?.name || udid.slice(0, 10);
}

function formatStep(s) {
  if (s.type === "tap" || s.type === "doubletap") {
    return `${s.type} (${Number(s.nx).toFixed(2)}, ${Number(s.ny).toFixed(2)})`;
  }
  if (s.type === "longpress") {
    return `longpress (${Number(s.nx).toFixed(2)}, ${Number(s.ny).toFixed(2)}) ${s.duration}s`;
  }
  if (s.type === "swipe") {
    return `swipe (${Number(s.nx1).toFixed(2)},${Number(s.ny1).toFixed(2)})→(${Number(s.nx2).toFixed(2)},${Number(s.ny2).toFixed(2)})`;
  }
  if (s.type === "button" || s.type === "key") return `${s.type}: ${s.name}`;
  if (s.type === "text") return `text: "${String(s.text).slice(0, 20)}"`;
  if (s.type === "wait") return `wait ${s.duration_ms}ms`;
  return s.type;
}

function onSave() {
  const saved = saveMacro(draftName.value);
  if (saved) pushToast(t("replay.savedToast", { name: saved.name }), "ok");
}

async function onImportFile(ev) {
  const file = ev.target?.files?.[0];
  if (!file) return;
  try {
    const n = importJson(await file.text());
    pushToast(t("replay.importedToast", { n }), "ok");
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  } finally {
    ev.target.value = "";
  }
}

async function onRun() {
  try {
    await runReplay({
      targets: resolvedTargets.value,
      speed: speed.value,
      loops: loops.value,
      name: draftName.value,
    });
  } catch (e) {
    pushToast(e?.message || t("errors.generic"), "err");
  }
}
</script>

<style scoped>
.rp-wrap { display: flex; flex-direction: column; gap: 10px; }
.rp-box {
  background: var(--inset);
  border: 1px solid var(--border);
  border-radius: 0;
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.rp-head { display: flex; align-items: center; justify-content: space-between; font-size: 0.78rem; }
.rp-count { font-size: 0.7rem; }
.rp-row { display: flex; align-items: center; gap: 6px; }
.rp-row.wrap { flex-wrap: wrap; }
.rp-row.between { justify-content: space-between; }
.rp-btn { min-height: 26px; padding: 2px 9px; font-size: 0.74rem; border-radius: 0; }
.rp-btn.active { border-color: var(--primary); color: var(--text-strong); background: color-mix(in srgb, var(--primary) 16%, transparent); }
.rp-btn.rec-active {
  background: rgba(239, 68, 68, 0.16);
  border-color: rgba(239, 68, 68, 0.55);
  color: #fca5a5;
}
.rp-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.rp-dot.live { background: var(--danger); animation: rp-pulse 1s ease-in-out infinite; }
@keyframes rp-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
.rp-input { flex: 1; min-width: 0; min-height: 26px; padding: 3px 8px; font-size: 0.76rem; }
.rp-empty { margin: 2px 0; font-size: 0.74rem; line-height: 1.4; }
.rp-steps { max-height: 170px; overflow: auto; display: flex; flex-direction: column; gap: 3px; }
.rp-step-row {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 6px; border: 1px solid var(--border); background: var(--panel);
  font-size: 0.7rem;
}
.rp-step-idx { color: var(--muted); min-width: 16px; }
.rp-step-desc { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rp-step-delay { font-size: 0.66rem; }
.rp-del { min-height: 20px; width: 20px; padding: 0; font-size: 0.68rem; border: none; }
.rp-targets { display: flex; flex-direction: column; gap: 4px; max-height: 110px; overflow: auto; }
.rp-target-item {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 6px; border: 1px solid var(--border); background: var(--panel);
  font-size: 0.74rem; cursor: pointer;
}
.rp-target-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.os-badge { font-size: 0.62rem; padding: 1px 4px; border-radius: 0; font-weight: 700; }
.os-badge.android { background: rgba(52, 199, 89, 0.16); color: #34c759; }
.os-badge.ios { background: rgba(79, 124, 255, 0.16); color: #6ea2ff; }
.rp-field { display: flex; align-items: center; gap: 4px; font-size: 0.72rem; }
.rp-select, .rp-num { min-height: 26px; padding: 2px 6px; font-size: 0.74rem; }
.rp-num { width: 50px; }
.rp-job { display: flex; flex-direction: column; gap: 5px; padding-top: 4px; border-top: 1px solid var(--border); }
.rp-progress { height: 6px; background: var(--panel); border: 1px solid var(--border); overflow: hidden; }
.rp-progress-fill { height: 100%; background: var(--primary); transition: width 0.2s ease; }
.rp-progress-fill.completed { background: var(--ok); }
.rp-progress-fill.stopped { background: var(--warn); }
.rp-progress-fill.failed { background: var(--danger); }
.rp-dev-stats { display: flex; flex-direction: column; gap: 3px; }
.rp-stat-row { display: flex; align-items: center; gap: 8px; font-size: 0.68rem; }
.rp-stat-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rp-ok { color: var(--ok); }
.rp-err { color: var(--danger); }
.rp-lib { display: flex; flex-direction: column; gap: 4px; max-height: 130px; overflow: auto; }
.rp-lib-row { display: flex; align-items: center; gap: 4px; }
.rp-lib-load {
  flex: 1; min-width: 0; min-height: 26px; padding: 3px 8px;
  justify-content: space-between; text-align: left; font-size: 0.74rem;
}
.rp-lib-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
