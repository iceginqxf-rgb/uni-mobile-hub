<template>
  <label class="lang" :title="t('preferences.language')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" /><path d="M2 12h20" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
    <select :value="locale" :aria-label="t('preferences.language')" @change="setLocale($event.target.value)">
      <option v-for="opt in availableLocales" :key="opt" :value="opt">{{ labels[opt] || opt }}</option>
    </select>
  </label>
</template>

<script setup>
import { computed } from "vue";
import { useUiI18n } from "../composables/useUiI18n";

const { locale, availableLocales, setLocale, t } = useUiI18n();
const NATIVE = { en: "English", "zh-CN": "简体中文", "zh-TW": "繁體中文" };
const labels = computed(() => NATIVE);
</script>

<style scoped>
.lang {
  display: inline-flex; align-items: center; gap: 4px; height: 28px; padding: 0 4px 0 8px;
  border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--muted);
}
.lang:hover { border-color: var(--border-strong); color: var(--text); }
.lang:focus-within { border-color: var(--primary); }
.lang svg { width: 13px; height: 13px; flex: none; }
.lang select {
  min-height: 0; height: 24px; font-size: 0.78rem; border: none;
  background: transparent; color: var(--text); padding: 0 4px; box-shadow: none;
}
.lang select:focus { outline: none; box-shadow: none; }
</style>
