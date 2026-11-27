<template>
  <aside v-if="open && udid" class="idock" role="region" :aria-label="t('inspector.title')">
    <header class="idock-head">
      <div class="row" style="gap: 6px; min-width: 0; flex: 1">
        <span class="idock-os mono" :class="isAndroid ? 'and' : 'ios'">{{ isAndroid ? "AND" : "iOS" }}</span>
        <strong class="idock-name">{{ devName }}</strong>
      </div>
      <button type="button" class="idock-close" :title="t('detail.close')" @click="$emit('close')">✕</button>
    </header>

    <div class="idock-tabs" role="tablist">
      <button
        v-for="tb in tabs"
        :key="tb.key"
        type="button"
        class="idock-tab"
        :class="{ active: tab === tb.key }"
        role="tab"
        :aria-selected="tab === tb.key"
        @click="tab = tb.key"
      >
        {{ tb.label }}
      </button>
    </div>

    <div class="idock-body">
      <div v-show="tab === 'info'" class="idock-stack">
        <ReservationCard :udid="udid" />
        <DeviceInfoCard :udid="udid" />
        <QuickActionsCard :udid="udid" />
      </div>
      <ControlPanel v-show="tab === 'control'" :udid="udid" />
      <ReplayPanel v-show="tab === 'replay'" :udid="udid" />
      <AutomationPanel v-if="!isAndroid" v-show="tab === 'automation'" :udid="udid" />
      <AppsPanel v-show="tab === 'apps'" :udid="udid" />
      <FilesPanel v-show="tab === 'files'" :udid="udid" />
      <LogPanel v-show="tab === 'logs'" :udid="udid" :connected="!!device?.connected" />
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import ReservationCard from "./ReservationCard.vue";
import DeviceInfoCard from "./DeviceInfoCard.vue";
import QuickActionsCard from "./QuickActionsCard.vue";
import ControlPanel from "./ControlPanel.vue";
import ReplayPanel from "./ReplayPanel.vue";
import AutomationPanel from "./AutomationPanel.vue";
import AppsPanel from "./AppsPanel.vue";
import FilesPanel from "./FilesPanel.vue";
import LogPanel from "./LogPanel.vue";
import { useDevices } from "../composables/useDevices";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  udid: { type: String, required: true },
  open: { type: Boolean, default: true },
});
defineEmits(["close"]);

const { t } = useUiI18n();
const { devices } = useDevices();

const device = computed(() => devices.value.find((d) => d.udid === props.udid));
const isAndroid = computed(() => device.value?.platform === "android");
const devName = computed(() => device.value?.marketing || device.value?.name || props.udid.slice(0, 12));

const tab = ref("info");
const tabs = computed(() =>
  [
    { key: "info", label: t("inspector.info") },
    { key: "control", label: t("control.title") },
    { key: "replay", label: t("replay.tab") },
    { key: "automation", label: t("automation.title") },
    { key: "apps", label: t("apps.title") },
    { key: "files", label: t("files.title") },
    { key: "logs", label: t("logs.title") },
  ].filter((tb) => !(isAndroid.value && tb.key === "automation")),
);

watch(isAndroid, (and) => {
  if (and && tab.value === "automation") tab.value = "control";
});
</script>

<style scoped>
.idock {
  width: 340px;
  flex: 0 0 340px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border-left: 1px solid var(--border);
  overflow: hidden;
}
.idock-head {
  height: 36px;
  flex: 0 0 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px 0 10px;
  border-bottom: 1px solid var(--border);
}
.idock-os {
  font-size: 0.62rem;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 0;
  flex: none;
}
.idock-os.and { background: rgba(34, 197, 94, 0.14); color: var(--ok); }
.idock-os.ios { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--primary-2); }
.idock-name {
  font-size: 0.82rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.idock-close {
  min-height: 24px;
  height: 24px;
  width: 24px;
  padding: 0;
  border-radius: 0;
}
.idock-tabs {
  display: flex;
  overflow-x: auto;
  border-bottom: 1px solid var(--border);
  scrollbar-width: none;
}
.idock-tabs::-webkit-scrollbar { display: none; }
.idock-tab {
  flex: 1 0 auto;
  min-height: 30px;
  height: 30px;
  padding: 0 8px;
  font-size: 0.76rem;
  border: none;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  box-shadow: inset 0 -2px 0 transparent;
}
.idock-tab:hover:not(.active) { color: var(--text); background: var(--surface-2); }
.idock-tab.active {
  color: var(--text-strong);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--primary);
}
.idock-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px;
}
.idock-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
@media (max-width: 1120px) {
  .idock {
    position: fixed;
    right: 0;
    top: var(--tabbar-h);
    bottom: 0;
    z-index: 45;
    box-shadow: var(--shadow);
  }
}
</style>
