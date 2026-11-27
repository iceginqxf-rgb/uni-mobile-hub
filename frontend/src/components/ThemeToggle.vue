<template>
  <!-- Multi-card preset selector (Settings view) -->
  <div v-if="labeled" class="theme-grid" role="radiogroup" :aria-label="t('settings.theme')">
    <button
      v-for="preset in themes"
      :key="preset.id"
      type="button"
      class="theme-card"
      :class="{ active: theme === preset.id }"
      role="radio"
      :aria-checked="theme === preset.id"
      @click="setTheme(preset.id)"
    >
      <span class="tc-preview" :style="{ background: preset.bg, borderColor: preset.accent }">
        <span class="tc-panel" :style="{ background: preset.panel }" />
        <span class="tc-dot" :style="{ background: preset.accent }" />
      </span>
      <span class="tc-label">{{ t("themes." + preset.id) }}</span>
    </button>
  </div>

  <!-- Compact popover selector (Topbar / Login toolbar) -->
  <div v-else ref="wrapEl" class="theme-pop-wrap">
    <button
      class="tb-icon-btn"
      type="button"
      :title="t('settings.theme') + ': ' + t('themes.' + theme)"
      :aria-label="t('settings.theme')"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="tc-swatch" :style="{ background: activePreset.accent }" />
      <svg v-if="activePreset.isLight" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" />
        <path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" />
        <path d="M2 12h2" /><path d="M20 12h2" />
        <path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" />
      </svg>
      <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
      </svg>
    </button>

    <div v-if="open" class="theme-pop" role="menu">
      <button
        v-for="preset in themes"
        :key="preset.id"
        type="button"
        class="theme-opt"
        :class="{ active: theme === preset.id }"
        role="menuitemradio"
        :aria-checked="theme === preset.id"
        @click="pick(preset.id)"
      >
        <span class="tc-chip" :style="{ background: preset.bg, borderColor: preset.accent }">
          <span class="tc-chip-dot" :style="{ background: preset.accent }" />
        </span>
        <span class="theme-opt-name">{{ t("themes." + preset.id) }}</span>
        <span v-if="theme === preset.id" class="theme-check">✓</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useTheme } from "../composables/useTheme";
import { useUiI18n } from "../composables/useUiI18n";

defineProps({ labeled: { type: Boolean, default: false } });

const { theme, themes, setTheme } = useTheme();
const { t } = useUiI18n();
const open = ref(false);
const wrapEl = ref(null);

const activePreset = computed(() => themes.find((p) => p.id === theme.value) || themes[0]);

function pick(id) {
  setTheme(id);
  open.value = false;
}

function onDocClick(ev) {
  if (open.value && wrapEl.value && !wrapEl.value.contains(ev.target)) {
    open.value = false;
  }
}
function onKey(ev) {
  if (open.value && ev.key === "Escape") open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDocClick);
  window.addEventListener("keydown", onKey);
});
onUnmounted(() => {
  document.removeEventListener("pointerdown", onDocClick);
  window.removeEventListener("keydown", onKey);
});
</script>

<style scoped>
.theme-pop-wrap { position: relative; display: inline-flex; }
.tb-icon-btn {
  min-height: 28px; height: 28px; padding: 0 8px; gap: 5px;
  border-radius: 0; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.tb-icon-btn:hover { color: var(--text-strong); border-color: var(--border-strong); background: var(--surface-1); }
.tb-icon-btn svg { width: 14px; height: 14px; }
.tc-swatch { width: 7px; height: 7px; border-radius: 0; flex: none; }

.theme-pop {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 90;
  min-width: 172px; padding: 4px;
  background: var(--panel-solid); border: 1px solid var(--border-strong);
  border-radius: 0; box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: 2px;
}
.theme-opt {
  min-height: 30px; width: 100%; justify-content: flex-start; padding: 4px 8px;
  border: 1px solid transparent; border-radius: 0; background: transparent;
  font-size: 0.8rem; color: var(--text); gap: 8px;
}
.theme-opt:hover { background: var(--surface-1); border-color: transparent; }
.theme-opt.active { background: var(--surface-1); border-color: var(--primary); color: var(--text-strong); font-weight: 600; }
.theme-opt-name { flex: 1; text-align: left; }
.theme-check { color: var(--primary); font-size: 0.78rem; }
.tc-chip {
  width: 16px; height: 16px; border-radius: 0; border: 1px solid;
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.tc-chip-dot { width: 6px; height: 6px; border-radius: 0; }

.theme-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 8px;
}
.theme-card {
  flex-direction: column; align-items: stretch; gap: 7px;
  padding: 8px; min-height: 0; border-radius: 0;
  border: 1px solid var(--border); background: var(--inset);
}
.theme-card:hover { border-color: var(--border-strong); background: var(--surface-2); }
.theme-card.active { border-color: var(--primary); background: var(--surface-1); }
.tc-preview {
  height: 34px; border-radius: 0; border: 1px solid; padding: 5px;
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
}
.tc-panel { flex: 1; height: 100%; border-radius: 0; opacity: 0.9; }
.tc-dot { width: 10px; height: 10px; border-radius: 0; flex: none; }
.tc-label { font-size: 0.78rem; font-weight: 600; text-align: left; color: var(--text); }
</style>
