<template>
  <div class="card">
    <strong>{{ t("control.title") }}</strong>

    <div v-if="!isAndroid" class="block">
      <label class="muted">{{ t("control.systemAlert") }}</label>
      <div class="row">
        <button @click="checkAlert">{{ t("control.check") }}</button>
        <button v-if="alert.present" class="primary" @click="doAlert('accept')">{{ t("control.accept") }}</button>
        <button v-if="alert.present" @click="doAlert('dismiss')">{{ t("control.dismiss") }}</button>
      </div>
      <span v-if="alert.present" class="muted" style="font-size: 0.72rem">{{ alert.text }}</span>
      <span v-else-if="alertChecked" class="muted" style="font-size: 0.72rem">{{ t("control.noAlert") }}</span>
    </div>

    <div class="block">
      <label class="muted">{{ t("control.textInput") }}</label>
      <div class="row">
        <input v-model="text" style="flex: 1; min-width: 0" :placeholder="t('control.typePlaceholder')" @keyup.enter="sendText" />
        <button class="primary" @click="sendText">{{ t("control.send") }}</button>
      </div>
      <div class="row" style="flex-wrap: wrap; margin-top: 6px">
        <button @click="ctrl.sendKey('backspace')" :title="t('control.backspace')">⌫</button>
        <button @click="ctrl.sendKey('enter')" :title="t('control.return')">{{ t("control.enter") }}</button>
        <button @click="ctrl.sendKey('space')">{{ t("control.space") }}</button>
        <template v-if="isAndroid">
          <button @click="ctrl.sendKey('back')">{{ t("control.back") }}</button>
          <button @click="ctrl.sendKey('home')">{{ t("control.home") }}</button>
          <button @click="ctrl.sendKey('recent')">{{ t("control.recent") }}</button>
        </template>
      </div>
    </div>

    <div class="block">
      <label class="muted">{{ t("control.app") }}</label>
      <div class="row">
        <SelectMenu
          v-model="bundleId"
          :options="appOptions"
          :placeholder="appsLoading ? t('apps.loading') : t('control.noApps')"
          :empty-text="appsLoading ? t('apps.loading') : t('control.noApps')"
          style="flex: 1; min-width: 0"
        />
        <button class="card-action" :title="t('apps.refresh')" :disabled="appsLoading" @click="loadApps">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: appsLoading }"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
        </button>
      </div>
      <div class="row" style="margin-top: 6px">
        <button @click="doLaunch" :disabled="!bundleId">{{ t("control.launch") }}</button>
        <button @click="doTerminate" :disabled="!bundleId">{{ t("control.terminate") }}</button>
      </div>
    </div>

    <div class="block">
      <label class="muted">{{ t("control.clipboard") }}</label>
      <div class="row">
        <input v-model="clip" style="flex: 1; min-width: 0" :placeholder="t('control.clipPlaceholder')" @keyup.enter="pushClip" />
        <button class="primary" @click="pushClip">{{ t("control.push") }}</button>
        <button @click="pullClip">{{ t("control.pull") }}</button>
      </div>
      <div class="row clip-actions">
        <button type="button" class="clip-sync-btn" :disabled="clipSync.busy.value" @click="pushBrowserClip">
          <span>{{ t("clipSync.pushFromHost") }}</span>
          <kbd class="mono">⌘⇧V</kbd>
        </button>
        <button type="button" class="clip-sync-btn" :disabled="clipSync.busy.value" @click="pullToBrowserClip">
          <span>{{ t("clipSync.pullToHost") }}</span>
          <kbd class="mono">⌘⇧C</kbd>
        </button>
      </div>
      <div class="clip-toggles">
        <label class="clip-check">
          <input
            type="checkbox"
            :checked="clipSync.autoSync.value"
            @change="clipSync.setAutoSync($event.target.checked)"
          />
          <span>{{ t("clipSync.autoSyncLabel") }}</span>
        </label>
        <label class="clip-check">
          <input
            type="checkbox"
            :checked="clipSync.autoType.value"
            @change="clipSync.setAutoType($event.target.checked)"
          />
          <span>{{ t("clipSync.autoTypeLabel") }}</span>
        </label>
      </div>
      <span v-if="!isAndroid" class="muted" style="font-size: 0.72rem">
        {{ t("control.clipHint") }}
      </span>
    </div>

    <div class="block">
      <div class="row">
        <button @click="doScreenshot">{{ t("control.screenshot") }}</button>
        <button v-if="ctrl.lastScreenshot.value" @click="downloadShot">{{ t("control.download") }}</button>
      </div>
      <img v-if="ctrl.lastScreenshot.value" :src="ctrl.lastScreenshot.value" class="shot" />
    </div>

    <p v-if="ctrl.error.value" class="banner err">{{ ctrl.error.value }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useControl } from "../composables/useControl";
import { useClipboardSync } from "../composables/useClipboardSync";
import { useDevices } from "../composables/useDevices";
import { useUiI18n } from "../composables/useUiI18n";
import { useToast } from "../composables/useToast";
import { appsApi } from "../api/apps";
import SelectMenu from "./SelectMenu.vue";

const props = defineProps({ udid: { type: String, required: true } });
const { t } = useUiI18n();
const { push: toast } = useToast();
const { devices } = useDevices();
const clipSync = useClipboardSync();
const isAndroid = computed(() => devices.value.find((d) => d.udid === props.udid)?.platform === "android");
const ctrl = useControl(props.udid);
const text = ref("");
const bundleId = ref("");

// Installed apps for the launch/terminate picker (replaces free-text bundle id).
const apps = ref([]);
const appsLoading = ref(false);
const appOptions = computed(() =>
  apps.value.map((a) => ({ value: a.bundle_id, label: `${a.name} · ${a.bundle_id}` })),
);
async function loadApps() {
  appsLoading.value = true;
  try {
    const d = await appsApi.list(props.udid);
    apps.value = (d.apps || []).sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    // Keep current selection if still present, else pick the first app.
    if (!apps.value.some((a) => a.bundle_id === bundleId.value)) {
      bundleId.value = apps.value[0]?.bundle_id || "";
    }
  } catch {
    /* not connected / WDA down — leave empty; the refresh button retries */
  } finally {
    appsLoading.value = false;
  }
}
onMounted(loadApps);
const clip = ref("");
const alert = ref({ present: false, text: "", buttons: [] });
const alertChecked = ref(false);

async function checkAlert() {
  alert.value = await ctrl.getAlert();
  alertChecked.value = true;
}
async function doAlert(action) {
  await ctrl.alertAction(action);
  await checkAlert();
}

async function sendText() {
  if (!text.value) return;
  await ctrl.input(text.value);
  text.value = "";
  if (!ctrl.error.value) toast(t("toast.textSent"));
}

async function pushClip() {
  if (!clip.value) return;
  if (await ctrl.pushClipboard(clip.value)) toast(t("toast.clipPushed"));
}

async function doScreenshot() {
  if (await ctrl.screenshot()) toast(t("toast.screenshotSaved"));
}
async function doLaunch() {
  if (!bundleId.value) return;
  await ctrl.launch(bundleId.value);
  if (!ctrl.error.value) toast(t("toast.launched"));
}
async function doTerminate() {
  if (!bundleId.value) return;
  await ctrl.terminate(bundleId.value);
  if (!ctrl.error.value) toast(t("toast.terminated"));
}
async function pullClip() {
  const r = await ctrl.pullClipboard();
  clip.value = r.text || "";
  if (!r.available && !r.text) ctrl.error.value = t("control.clipEmpty");
}

async function pushBrowserClip() {
  ctrl.error.value = "";
  try {
    const res = await clipSync.pushFromBrowser(props.udid);
    if (res?.text) clip.value = res.text;
    toast(res?.typed ? t("clipSync.pushedAndTypedToast") : t("clipSync.pushedToast"), "ok");
  } catch (e) {
    ctrl.error.value = e?.message || t("errors.generic");
    toast(ctrl.error.value, "err");
  }
}

async function pullToBrowserClip() {
  ctrl.error.value = "";
  try {
    const text = await clipSync.pullToBrowser(props.udid);
    clip.value = text;
    toast(t("clipSync.pulledToast"), "ok");
  } catch (e) {
    ctrl.error.value = e?.message || t("control.clipEmpty");
    toast(ctrl.error.value, "err");
  }
}

function downloadShot() {
  const url = ctrl.lastScreenshot.value;
  if (!url) return;
  const a = document.createElement("a");
  a.href = url;
  a.download = `screenshot-${props.udid.slice(0, 8)}-${Date.now()}.jpg`;
  a.click();
}
</script>

<style scoped>
.block { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.shot { margin-top: 8px; max-width: 100%; border: 1px solid var(--border); border-radius: 0; }
.clip-actions { gap: 6px; flex-wrap: wrap; }
.clip-sync-btn {
  flex: 1 1 auto;
  justify-content: space-between;
  gap: 6px;
  min-height: 28px;
  padding: 2px 8px;
  font-size: 0.75rem;
  border-radius: 0;
}
.clip-sync-btn kbd {
  font-size: 0.65rem;
  color: var(--muted);
  border: 1px solid var(--border);
  padding: 0 4px;
}
.clip-toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 2px 0;
}
.clip-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.74rem;
  color: var(--text);
  cursor: pointer;
}
.clip-check input {
  width: 13px;
  height: 13px;
  min-height: 0;
  border-radius: 0;
  accent-color: var(--primary);
}
</style>
