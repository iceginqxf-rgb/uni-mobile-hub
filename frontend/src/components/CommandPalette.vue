<template>
  <Teleport to="body">
    <div v-if="open" class="cp-backdrop" role="dialog" aria-modal="true" :aria-label="t('palette.title')" @click.self="$emit('close')">
      <div class="cp-box">
        <div class="cp-input-row">
          <svg class="cp-search-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref="inputEl"
            v-model="query"
            type="search"
            class="cp-input"
            :placeholder="t('palette.placeholder')"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="runSelected"
            @keydown.esc.prevent="$emit('close')"
          />
          <span class="cp-kbd mono">ESC</span>
        </div>

        <div class="cp-list">
          <p v-if="!items.length" class="muted cp-empty">{{ t("palette.empty") }}</p>
          <button
            v-for="(item, idx) in items"
            :key="item.id"
            type="button"
            class="cp-item"
            :class="{ active: idx === selectedIdx }"
            @mouseenter="selectedIdx = idx"
            @click="execute(item)"
          >
            <span class="cp-group mono">{{ item.group }}</span>
            <span class="cp-label">{{ item.label }}</span>
            <span v-if="item.hint" class="cp-hint mono">{{ item.hint }}</span>
          </button>
        </div>

        <footer class="cp-foot mono">
          <span>↑↓ {{ t("palette.navHint") }}</span>
          <span>↵ {{ t("palette.runHint") }}</span>
          <span>⌘K / 2×Shift</span>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { controlApi } from "../api/control";
import { useClipboardSync } from "../composables/useClipboardSync";
import { useTheme } from "../composables/useTheme";
import { useSync } from "../composables/useSync";
import { useTaskSwitcher } from "../composables/useTaskSwitcher";
import { useToast } from "../composables/useToast";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  open: { type: Boolean, default: false },
  devices: { type: Array, default: () => [] },
  focusedUdid: { type: String, default: "" },
});
const emit = defineEmits([
  "close",
  "open-device",
  "add-split",
  "set-layout",
  "select-overview",
  "open-nodes",
  "open-batch",
  "toggle-sidebar",
  "toggle-inspector",
]);

const { t } = useUiI18n();
const { themes, setTheme } = useTheme();
const { clearAll: clearAllSync } = useSync();
const clipSync = useClipboardSync();
const { openTaskSwitcher } = useTaskSwitcher();
const { push: toast } = useToast();

const inputEl = ref(null);
const query = ref("");
const selectedIdx = ref(0);

const focusedDev = computed(() => props.devices.find((d) => d.udid === props.focusedUdid));
const focusedLabel = computed(
  () => focusedDev.value?.marketing || focusedDev.value?.name || (props.focusedUdid ? props.focusedUdid.slice(0, 10) : ""),
);

const allItems = computed(() => {
  const list = [];

  for (const d of props.devices) {
    const label = d.marketing || d.name || d.udid;
    const os = d.platform === "android" ? "AND" : "iOS";
    list.push({
      id: `dev-${d.udid}`,
      group: t("palette.grpDevice"),
      label: `${label} (${os})`,
      hint: d.node_id && d.node_id !== "local" ? d.node_id : d.udid.slice(0, 8),
      run: () => emit("open-device", d.udid),
    });
    if (props.devices.length > 1) {
      list.push({
        id: `split-add-${d.udid}`,
        group: t("palette.grpSplit"),
        label: `${t("palette.addToSplit")}: ${label}`,
        hint: os,
        run: () => emit("add-split", d.udid),
      });
    }
  }

  if (props.focusedUdid) {
    const udid = props.focusedUdid;
    const isAnd = focusedDev.value?.platform === "android";
    list.push(
      {
        id: "act-fs",
        group: t("palette.grpControl"),
        label: `${t("fullscreen.toggle")} (${focusedLabel.value})`,
        hint: "FS",
        run: () => window.dispatchEvent(new CustomEvent("umh:fullscreen", { detail: { udid } })),
      },
      {
        id: "act-rec",
        group: t("palette.grpControl"),
        label: `${t("recorder.toggle")} (${focusedLabel.value})`,
        hint: "REC",
        run: () => window.dispatchEvent(new CustomEvent("umh:record", { detail: { udid } })),
      },
      {
        id: "act-home",
        group: t("palette.grpControl"),
        label: `${t("control.home")} (${focusedLabel.value})`,
        hint: "HOME",
        run: () => controlApi.button(udid, "home").then(() => toast(t("control.home"), "ok")),
      },
      {
        id: "act-recent",
        group: t("palette.grpControl"),
        label: `${t("control.recent")} (${focusedLabel.value})`,
        hint: "APPS",
        run: () => (isAnd ? controlApi.button(udid, "recent") : openTaskSwitcher(udid)),
      },
      {
        id: "act-lock",
        group: t("palette.grpControl"),
        label: `${isAnd ? t("control.power") : t("control.lock")} (${focusedLabel.value})`,
        hint: "LOCK",
        run: () => controlApi.button(udid, isAnd ? "power" : "lock"),
      },
      {
        id: "act-shot",
        group: t("palette.grpControl"),
        label: `${t("control.screenshot")} (${focusedLabel.value})`,
        hint: "PNG",
        run: () => controlApi.screenshot(udid).then(() => toast(t("toast.screenshotSaved"), "ok")),
      },
      {
        id: "act-clip-push",
        group: t("palette.grpControl"),
        label: `${t("clipSync.pushFromHost")} (${focusedLabel.value})`,
        hint: "⌘⇧V",
        run: () =>
          clipSync
            .pushFromBrowser(udid)
            .then((res) =>
              toast(res?.typed ? t("clipSync.pushedAndTypedToast") : t("clipSync.pushedToast"), "ok"),
            ),
      },
      {
        id: "act-clip-pull",
        group: t("palette.grpControl"),
        label: `${t("clipSync.pullToHost")} (${focusedLabel.value})`,
        hint: "⌘⇧C",
        run: () => clipSync.pullToBrowser(udid).then(() => toast(t("clipSync.pulledToast"), "ok")),
      },
    );
  }

  list.push(
    {
      id: "ws-overview",
      group: t("palette.grpWorkspace"),
      label: t("workbench.overview"),
      hint: "GRID",
      run: () => emit("select-overview"),
    },
    {
      id: "ws-nodes",
      group: t("palette.grpWorkspace"),
      label: t("nodes.title"),
      hint: "NODES",
      run: () => emit("open-nodes"),
    },
    {
      id: "ws-batch",
      group: t("palette.grpWorkspace"),
      label: t("batch.title"),
      hint: "BATCH",
      run: () => emit("open-batch"),
    },
    {
      id: "ws-single",
      group: t("palette.grpWorkspace"),
      label: t("split.single"),
      hint: "1×1",
      run: () => emit("set-layout", "single"),
    },
    {
      id: "ws-split2",
      group: t("palette.grpWorkspace"),
      label: t("split.sideBySide"),
      hint: "1×2",
      run: () => emit("set-layout", "split-2"),
    },
    {
      id: "ws-splitgrid",
      group: t("palette.grpWorkspace"),
      label: t("split.quadGrid"),
      hint: "2×2",
      run: () => emit("set-layout", "split-grid"),
    },
    {
      id: "ws-sidebar",
      group: t("palette.grpWorkspace"),
      label: t("workbench.collapseSidebar"),
      hint: "⌘B",
      run: () => emit("toggle-sidebar"),
    },
    {
      id: "ws-inspector",
      group: t("palette.grpWorkspace"),
      label: t("inspector.toggle"),
      hint: "⌘I",
      run: () => emit("toggle-inspector"),
    },
    {
      id: "ws-clear-sync",
      group: t("palette.grpWorkspace"),
      label: t("sync.clearAll"),
      hint: "SYNC",
      run: () => clearAllSync().then(() => toast(t("sync.cleared"), "ok")),
    },
    {
      id: "ws-clip-auto",
      group: t("palette.grpWorkspace"),
      label: t("clipSync.toggleAuto"),
      hint: clipSync.autoSync.value ? "ON" : "OFF",
      run: () => {
        const next = clipSync.toggleAutoSync();
        toast(next ? t("clipSync.autoEnabledToast") : t("clipSync.autoDisabledToast"), "ok");
      },
    },
  );

  for (const preset of themes) {
    list.push({
      id: `theme-${preset.id}`,
      group: t("palette.grpTheme"),
      label: t("themes." + preset.id),
      hint: preset.id,
      run: () => setTheme(preset.id),
    });
  }

  return list;
});

const items = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return allItems.value;
  return allItems.value.filter(
    (it) =>
      it.label.toLowerCase().includes(q) ||
      it.group.toLowerCase().includes(q) ||
      (it.hint || "").toLowerCase().includes(q),
  );
});

watch(items, () => {
  selectedIdx.value = 0;
});

watch(
  () => props.open,
  async (v) => {
    if (!v) return;
    query.value = "";
    selectedIdx.value = 0;
    await nextTick();
    inputEl.value?.focus();
  },
);

function move(delta) {
  if (!items.value.length) return;
  selectedIdx.value = (selectedIdx.value + delta + items.value.length) % items.value.length;
}

function execute(item) {
  if (!item) return;
  emit("close");
  Promise.resolve(item.run?.()).catch((e) => toast(e?.message || t("errors.generic"), "err"));
}

function runSelected() {
  execute(items.value[selectedIdx.value]);
}
</script>

<style scoped>
.cp-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(0, 0, 0, 0.58);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: min(14vh, 110px);
  padding-inline: 16px;
}
.cp-box {
  width: min(580px, 100%);
  max-height: min(72vh, 520px);
  display: flex;
  flex-direction: column;
  background: var(--panel-solid);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.cp-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.cp-search-ic { width: 15px; height: 15px; color: var(--muted); flex: none; }
.cp-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  padding: 4px 0;
  min-height: 28px;
  font-size: 0.9rem;
}
.cp-input:focus { outline: none; box-shadow: none; }
.cp-kbd {
  font-size: 0.66rem;
  color: var(--muted);
  border: 1px solid var(--border);
  padding: 1px 5px;
}
.cp-list {
  flex: 1;
  overflow: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cp-empty { text-align: center; padding: 20px; font-size: 0.82rem; margin: 0; }
.cp-item {
  width: 100%;
  min-height: 32px;
  padding: 5px 10px;
  justify-content: flex-start;
  gap: 10px;
  border: 1px solid transparent;
  border-radius: 0;
  background: transparent;
  text-align: left;
}
.cp-item.active {
  background: color-mix(in srgb, var(--primary) 16%, transparent);
  border-color: var(--primary);
  color: var(--text-strong);
}
.cp-group {
  font-size: 0.66rem;
  padding: 1px 5px;
  background: var(--inset);
  border: 1px solid var(--border);
  color: var(--muted);
  flex: none;
  min-width: 58px;
  text-align: center;
}
.cp-label { flex: 1; font-size: 0.84rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cp-hint { font-size: 0.7rem; color: var(--muted); flex: none; }
.cp-foot {
  display: flex;
  justify-content: space-between;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  font-size: 0.68rem;
  color: var(--muted);
}
</style>
