<template>
  <!-- Multi-user: always gated behind login. -->
  <LoginView v-if="auth.state.ready && !auth.state.user" />

  <div v-else-if="auth.state.ready && auth.state.user" class="wb-shell">
    <NavRail
      v-model="activeNav"
      :is-admin="auth.isAdmin.value"
      :sidebar-open="sidebarOpen"
      @toggle-sidebar="toggleSidebar"
    />

    <DeviceSidebar
      v-if="activeNav === 'devices' && sidebarOpen"
      :devices="devices"
      :active-udid="activeTab === 'overview' ? '' : activeTab"
      :open-tabs="openTabs"
      :width="sidebarWidth"
      :loading="devicesLoading"
      @select="openDeviceTab"
      @refresh="refreshDevices(true)"
      @collapse="toggleSidebar"
      @resize="setSidebarWidth"
    />

    <div class="wb-main">
      <!-- Workbench browser-style Tab Bar when in Devices workspace -->
      <WorkbenchTabs
        v-if="activeNav === 'devices'"
        :devices="devices"
        :open-tabs="openTabs"
        :active-tab="activeTab"
        :dormant-tabs="dormantTabs"
        :sidebar-open="sidebarOpen"
        :devices-loading="devicesLoading"
        :is-admin="auth.isAdmin.value"
        :username="auth.state.user.username"
        :role-label="roleLabel"
        @select="selectTab"
        @close="closeDeviceTab"
        @toggle-sleep="toggleSleepTab"
        @toggle-sidebar="toggleSidebar"
        @refresh="refreshDevices(true)"
        @logout="doLogout"
      />

      <!-- Compact matching header for Sync / Settings / Admin views -->
      <header v-else class="wb-tabbar">
        <div class="row" style="gap: 8px">
          <strong style="font-size: 0.9rem">{{ sectionTitle }}</strong>
        </div>
        <div class="row" style="gap: 6px">
          <span class="pill mono" :class="auth.isAdmin.value ? 'warn' : 'on'" :title="auth.state.user.username">
            {{ roleLabel }}
          </span>
          <ThemeToggle />
          <LanguageSwitcher />
          <button type="button" class="tb-icon-btn" :title="t('app.logout')" @click="doLogout">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </header>

      <main class="wb-workspace">
        <AdminPanel v-if="activeNav === 'admin' && auth.isAdmin.value" @close="activeNav = 'devices'" />

        <SyncPanel v-else-if="activeNav === 'sync'" />

        <div v-else-if="activeNav === 'settings'" class="device-grid" style="grid-template-columns: minmax(0, 620px)">
          <div class="card">
            <strong>{{ t("settings.title") }}</strong>
            <div class="block">
              <label class="muted">{{ t("settings.theme") }}</label>
              <ThemeToggle :labeled="true" />
            </div>
            <div class="block">
              <label class="muted">{{ t("settings.language") }}</label>
              <div><LanguageSwitcher /></div>
            </div>
            <div class="block">
              <label class="muted">{{ t("settings.about") }}</label>
              <div class="muted mono" style="font-size: 0.78rem">{{ t("app.title") }} · {{ t("app.subtitle") }}</div>
            </div>
          </div>
        </div>

        <template v-else>
          <!-- Overview Grid (v-if so grid tiles never compete for WebRTC streams) -->
          <DeviceMatrix v-if="activeTab === 'overview'" :devices="devices" @open="openDeviceTab" />

          <!-- Persistent Open Device Tabs (v-show keeps live streams & drawer state) -->
          <template v-for="udid in openTabs" :key="udid">
            <DeviceDetailView
              v-show="activeTab === udid"
              :udid="udid"
              :embedded="true"
              :sleeping="!!dormantTabs[udid]"
              :auto-connect="true"
              @back="selectTab('overview')"
              @select="openDeviceTab"
              @wake="selectTab(udid)"
            />
          </template>
        </template>
      </main>
    </div>
  </div>

  <Toasts />
  <ConfirmDialog />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import DeviceDetailView from "./views/DeviceDetailView.vue";
import LoginView from "./components/LoginView.vue";
import AdminPanel from "./components/AdminPanel.vue";
import SyncPanel from "./components/SyncPanel.vue";
import DeviceMatrix from "./components/DeviceMatrix.vue";
import NavRail from "./components/NavRail.vue";
import DeviceSidebar from "./components/DeviceSidebar.vue";
import WorkbenchTabs from "./components/WorkbenchTabs.vue";
import ThemeToggle from "./components/ThemeToggle.vue";
import LanguageSwitcher from "./components/LanguageSwitcher.vue";
import Toasts from "./components/Toasts.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import { useAuth } from "./composables/useAuth";
import { useReservations } from "./composables/useReservations";
import { useDevices } from "./composables/useDevices";
import { useWorkbench } from "./composables/useWorkbench";
import { useUiI18n } from "./composables/useUiI18n";

const auth = useAuth();
const { t } = useUiI18n();
const { fetchReservations } = useReservations();
const { devices, loading: devicesLoading, refresh: refreshDevices, checkHealth } = useDevices();
const {
  sidebarOpen,
  sidebarWidth,
  openTabs,
  activeTab,
  dormantTabs,
  openDeviceTab,
  closeDeviceTab,
  selectTab,
  toggleSleepTab,
  toggleSidebar,
  setSidebarWidth,
  reconcileDevices,
} = useWorkbench();

const activeNav = ref("devices");
const sectionTitle = computed(() =>
  activeNav.value === "settings" ? t("nav.settings") : activeNav.value === "admin" ? t("app.admin") : t("nav.sync"),
);

const ROLE_KEY = { user: "user", admin: "admin", super_admin: "superAdmin" };
const roleLabel = computed(() => t("roles." + (ROLE_KEY[auth.state.user?.role] || "user")));

async function doLogout() {
  await auth.logout();
  activeNav.value = "devices";
}

async function loadDevices() {
  await checkHealth();
  await refreshDevices(true);
}
watch(() => auth.state.user, (u) => { if (u) { fetchReservations(); loadDevices(); } });
watch(devices, (list) => { if (list.length) reconcileDevices(list); });

function onGlobalKey(ev) {
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "b" && activeNav.value === "devices") {
    ev.preventDefault();
    toggleSidebar();
  }
}

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKey);
  await auth.checkAuth();
  if (auth.state.user) { fetchReservations(); loadDevices(); }
  auth.state.ready = true;
});
onUnmounted(() => {
  window.removeEventListener("keydown", onGlobalKey);
});
</script>

<style scoped>
.tb-icon-btn {
  min-height: 28px; height: 28px; width: 28px; padding: 0;
  border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.tb-icon-btn:hover { color: var(--text-strong); border-color: var(--border-strong); background: var(--surface-1); }
</style>
