<template>
  <header class="wb-tabbar">
    <div class="tb-tabs" role="tablist" :aria-label="t('workbench.tabsLabel')">
      <button
        v-if="!sidebarOpen"
        type="button"
        class="tb-icon-btn"
        :title="t('workbench.expandSidebar')"
        @click="$emit('toggle-sidebar')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="9" y1="3" x2="9" y2="21" />
        </svg>
      </button>

      <!-- Pinned Overview Tab -->
      <button
        type="button"
        class="wb-tab"
        :class="{ active: activeTab === 'overview' }"
        role="tab"
        :aria-selected="activeTab === 'overview'"
        @click="$emit('select', 'overview')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
        <span>{{ t("workbench.overview") }}</span>
      </button>

      <!-- Open Device Tabs -->
      <div
        v-for="udid in openTabs"
        :key="udid"
        class="wb-tab wb-dev-tab"
        :class="{ active: activeTab === udid, dormant: !!dormantTabs[udid] }"
        role="tab"
        :aria-selected="activeTab === udid"
        :title="tabTitle(udid)"
        @click="$emit('select', udid)"
      >
        <span class="tab-dot" :class="dotClass(udid)" />
        <span class="tab-os mono" :class="isAndroid(udid) ? 'and' : 'ios'">
          {{ isAndroid(udid) ? 'AND' : 'iOS' }}
        </span>
        <span class="tab-label">{{ tabName(udid) }}</span>
        <button
          type="button"
          class="tab-mini-btn"
          :title="dormantTabs[udid] ? t('workbench.wakeTab') : t('workbench.sleepTab')"
          @click.stop="$emit('toggle-sleep', udid)"
        >
          {{ dormantTabs[udid] ? "▶" : "⏸" }}
        </button>
        <button
          type="button"
          class="tab-mini-btn"
          :title="t('workbench.closeTab')"
          @click.stop="$emit('close', udid)"
        >
          ✕
        </button>
      </div>
    </div>

    <div class="tb-utils">
      <button
        type="button"
        class="tb-icon-btn"
        :disabled="devicesLoading"
        :title="t('devices.refresh')"
        @click="$emit('refresh')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: devicesLoading }">
          <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
        </svg>
      </button>
      <span class="pill mono" :class="isAdmin ? 'warn' : 'on'" :title="username">{{ roleLabel }}</span>
      <ThemeToggle />
      <LanguageSwitcher />
      <button type="button" class="tb-icon-btn" :title="t('app.logout')" @click="$emit('logout')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
        </svg>
      </button>
    </div>
  </header>
</template>

<script setup>
import ThemeToggle from "./ThemeToggle.vue";
import LanguageSwitcher from "./LanguageSwitcher.vue";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  devices: { type: Array, default: () => [] },
  openTabs: { type: Array, default: () => [] },
  activeTab: { type: String, default: "overview" },
  dormantTabs: { type: Object, default: () => ({}) },
  sidebarOpen: { type: Boolean, default: true },
  devicesLoading: { type: Boolean, default: false },
  isAdmin: { type: Boolean, default: false },
  username: { type: String, default: "" },
  roleLabel: { type: String, default: "" },
});

defineEmits(["select", "close", "toggle-sleep", "toggle-sidebar", "refresh", "logout"]);

const { t } = useUiI18n();

const findDev = (udid) => props.devices.find((d) => d.udid === udid);
const isAndroid = (udid) => findDev(udid)?.platform === "android";
const tabName = (udid) => {
  const d = findDev(udid);
  return d?.marketing || d?.name || udid.slice(0, 10);
};
const tabTitle = (udid) => `${tabName(udid)} (${udid})`;
const dotClass = (udid) => {
  if (props.dormantTabs[udid]) return "dormant";
  const d = findDev(udid);
  return d && (d.connected || d.streaming) ? "on" : "idle";
};
</script>

<style scoped>
.tb-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
  overflow-x: auto;
  scrollbar-width: none;
}
.tb-tabs::-webkit-scrollbar { display: none; }

.wb-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  min-height: 28px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex: 0 0 auto;
  user-select: none;
  transition: background .14s, color .14s, border-color .14s;
}
.wb-tab svg { width: 13px; height: 13px; flex: none; }
.wb-tab:hover { background: var(--surface-1); color: var(--text); }
.wb-tab.active {
  background: var(--surface-1);
  border-color: var(--border-strong);
  color: var(--text-strong);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--primary);
}
.wb-tab.dormant { opacity: 0.65; }

.tab-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); flex: none; }
.tab-dot.on { background: var(--ok); }
.tab-dot.dormant { background: var(--warn); }

.tab-os { font-size: 0.62rem; font-weight: 700; padding: 0 4px; border-radius: 3px; }
.tab-os.and { background: rgba(34, 197, 94, 0.14); color: var(--ok); }
.tab-os.ios { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--primary-2); }
.tab-label { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }

.tab-mini-btn {
  min-height: 18px; width: 18px; height: 18px; padding: 0; border-radius: 4px;
  border: none; background: transparent; color: var(--muted); font-size: 0.68rem;
}
.tab-mini-btn:hover { background: var(--panel-2); color: var(--text-strong); }

.tb-utils { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.tb-icon-btn {
  min-height: 28px; height: 28px; width: 28px; padding: 0;
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.tb-icon-btn:hover:not(:disabled) { color: var(--text-strong); border-color: var(--border-strong); background: var(--surface-1); }
.tb-icon-btn svg { width: 14px; height: 14px; }
.tb-icon-btn svg.spin { animation: topbar-spin 0.8s linear infinite; }
</style>
