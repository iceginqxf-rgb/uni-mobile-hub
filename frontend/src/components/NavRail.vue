<template>
  <nav class="wb-rail" aria-label="primary">
    <img class="nav-brand" src="/logo.svg" alt="" />

    <button
      v-for="it in items"
      :key="it.id"
      class="nav-item"
      :class="{ active: modelValue === it.id }"
      :title="it.label"
      :aria-label="it.label"
      :aria-current="modelValue === it.id ? 'page' : undefined"
      @click="$emit('update:modelValue', it.id)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round" v-html="it.icon" />
      <span
        v-if="it.id === 'nodes' && offlineNodes > 0"
        class="nav-alert-badge mono"
        :title="t('nodes.offlineCount', { n: offlineNodes })"
      >
        {{ offlineNodes > 9 ? "9+" : offlineNodes }}
      </span>
    </button>

    <button
      v-if="modelValue === 'devices'"
      class="nav-item"
      :class="{ active: sidebarOpen }"
      :title="sidebarOpen ? t('workbench.collapseSidebar') : t('workbench.expandSidebar')"
      @click="$emit('toggle-sidebar')"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="9" y1="3" x2="9" y2="21" />
      </svg>
    </button>

    <div class="nav-spacer" />

    <button
      v-if="isAdmin"
      class="nav-item"
      :class="{ active: modelValue === 'admin' }"
      :title="t('app.admin')"
      :aria-label="t('app.admin')"
      :aria-current="modelValue === 'admin' ? 'page' : undefined"
      @click="$emit('update:modelValue', 'admin')"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-4z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    </button>
  </nav>
</template>

<script setup>
import { computed } from "vue";
import { useUiI18n } from "../composables/useUiI18n";

defineProps({
  modelValue: { type: String, default: "devices" },
  isAdmin: { type: Boolean, default: false },
  sidebarOpen: { type: Boolean, default: true },
  offlineNodes: { type: Number, default: 0 },
});
defineEmits(["update:modelValue", "toggle-sidebar"]);
const { t } = useUiI18n();

const items = computed(() => [
  {
    id: "devices",
    label: t("nav.devices"),
    icon: '<rect x="5" y="2" width="14" height="20" rx="3"/><line x1="9" y1="18" x2="15" y2="18"/>',
  },
  {
    id: "nodes",
    label: t("nav.nodes"),
    icon: '<rect x="2" y="3" width="20" height="7" rx="1"/><rect x="2" y="14" width="20" height="7" rx="1"/><line x1="6" y1="6.5" x2="6.01" y2="6.5"/><line x1="6" y1="17.5" x2="6.01" y2="17.5"/>',
  },
  {
    id: "sync",
    label: t("nav.sync"),
    icon: '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  },
  {
    id: "settings",
    label: t("nav.settings"),
    icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 008 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 110-4h.09A1.65 1.65 0 003.6 8a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V2a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V8a1.65 1.65 0 001.51 1H22a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>',
  },
]);
</script>

<style scoped>
.nav-item {
  position: relative;
}
.nav-alert-badge {
  position: absolute;
  top: 3px;
  right: 3px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  font-size: 9px;
  line-height: 14px;
  font-weight: 700;
  text-align: center;
  color: #fff;
  background: var(--danger);
  border-radius: 50%;
}
</style>
