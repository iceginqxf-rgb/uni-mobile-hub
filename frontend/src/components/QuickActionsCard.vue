<template>
  <div class="card">
    <strong>{{ t("quick.title") }}</strong>

    <template v-if="isAndroid">
      <label class="muted" style="font-size: 0.72rem; display: block; margin-top: 10px">{{ t("quick.androidNav") }}</label>
      <div class="row" style="flex-wrap: wrap; gap: 6px; margin-top: 4px">
        <button @click="ctrl.pressButton('back')">{{ t("control.back") }}</button>
        <button @click="ctrl.pressButton('recent')">{{ t("control.recent") }}</button>
        <button @click="ctrl.pressButton('wake')">{{ t("control.wake") }}</button>
        <button @click="ctrl.pressButton('sleep')">{{ t("control.sleep") }}</button>
        <button @click="ctrl.pressButton('rotate')">{{ t("control.rotate") }}</button>
        <button @click="ctrl.pressButton('power')">{{ t("control.power") }}</button>
      </div>
    </template>

    <!-- Accessibility software-button toggles via go-ios. -->
    <template v-else>
      <div class="row" style="flex-wrap: wrap; gap: 6px; margin-top: 8px">
        <button @click="ctrl.pressButton('home')">{{ t("control.home") }}</button>
        <button @click="ctrl.pressButton('recent')">{{ t("control.recent") }}</button>
        <button @click="ctrl.pressButton('lock')">{{ t("control.lock") }}</button>
      </div>
      <label class="muted" style="font-size: 0.72rem; display: block; margin-top: 10px">{{ t("quick.accessibility") }}</label>
      <div class="row" style="flex-wrap: wrap; gap: 6px; margin-top: 4px">
        <button @click="toggleA11y('assistivetouch')">{{ t("quick.assistiveTouch") }}</button>
        <button @click="toggleA11y('voiceover')">{{ t("quick.voiceOver") }}</button>
        <button @click="toggleA11y('zoom')">{{ t("quick.zoom") }}</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useControl } from "../composables/useControl";
import { useDevices } from "../composables/useDevices";
import { useUiI18n } from "../composables/useUiI18n";

import { useToast } from "../composables/useToast";

const props = defineProps({ udid: { type: String, required: true } });
const { t } = useUiI18n();
const { devices } = useDevices();
const isAndroid = computed(() => devices.value.find((d) => d.udid === props.udid)?.platform === "android");
const ctrl = useControl(props.udid);
const { push: toast } = useToast();

const A11Y_LABEL = {
  assistivetouch: "quick.assistiveTouch",
  voiceover: "quick.voiceOver",
  zoom: "quick.zoom",
};
async function toggleA11y(feature) {
  const r = await ctrl.accessibility(feature, "toggle");
  if (r) toast(`${t(A11Y_LABEL[feature])} · ${r.enabled ? t("quick.on") : t("quick.off")}`);
}
</script>
