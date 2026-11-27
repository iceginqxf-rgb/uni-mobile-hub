<template>
  <!-- Multi-user: always gated behind login. -->
  <LoginView v-if="auth.state.ready && !auth.state.user" />

  <div v-else-if="auth.state.ready && auth.state.user" class="wb-shell">
    <NavRail
      v-model="activeNav"
      :is-admin="auth.isAdmin.value"
      :sidebar-open="sidebarOpen"
      :offline-nodes="offlineNodes"
      :running-batch="runningBatch"
      @toggle-sidebar="toggleSidebar"
    />

    <DeviceSidebar
      v-if="activeNav === 'devices' && sidebarOpen"
      :devices="devices"
      :active-udid="currentFocusedUdid"
      :open-tabs="openTabs"
      :width="sidebarWidth"
      :loading="devicesLoading"
      @select="openDeviceTab"
      @add-split="onAddToSplit"
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
        :layout-mode="layoutMode"
        :inspector-open="inspectorOpen"
        :devices-loading="devicesLoading"
        :is-admin="auth.isAdmin.value"
        :username="auth.state.user.username"
        :role-label="roleLabel"
        @select="selectTab"
        @close="closeDeviceTab"
        @toggle-sleep="toggleSleepTab"
        @toggle-sidebar="toggleSidebar"
        @set-layout="onSetLayout"
        @toggle-inspector="toggleInspector"
        @open-palette="openPalette"
        @refresh="refreshDevices(true)"
        @logout="doLogout"
      />

      <!-- Compact matching header for Sync / Settings / Admin views -->
      <header v-else class="wb-tabbar">
        <div class="row" style="gap: 8px">
          <strong style="font-size: 0.9rem">{{ sectionTitle }}</strong>
        </div>
        <div class="row" style="gap: 6px">
          <button type="button" class="tb-cmd-btn mono" :title="t('palette.title')" @click="openPalette">⌘K</button>
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

      <main class="wb-workspace" :class="{ 'split-host': activeNav === 'devices' && layoutMode !== 'single' }">
        <AdminPanel v-if="activeNav === 'admin' && auth.isAdmin.value" @close="activeNav = 'devices'" />

        <NodesPanel
          v-else-if="activeNav === 'nodes'"
          @open-device="onPaletteOpenDevice"
          @refresh-devices="refreshDevices(true)"
        />

        <SyncPanel v-else-if="activeNav === 'sync'" />

        <BatchPanel v-else-if="activeNav === 'batch'" />

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
          <!-- Single Mode: Overview Grid OR Persistent Device Tabs -->
          <template v-if="layoutMode === 'single'">
            <DeviceMatrix v-if="activeTab === 'overview'" :devices="devices" @open="openDeviceTab" />

            <template v-else>
              <DeviceDetailView
                v-for="udid in openTabs"
                :key="udid"
                v-show="activeTab === udid"
                :udid="udid"
                :embedded="true"
                :sleeping="!!dormantTabs[udid]"
                :inspector-open="inspectorOpen"
                :auto-connect="true"
                @back="selectTab('overview')"
                @select="openDeviceTab"
                @wake="selectTab(udid)"
              />
            </template>
          </template>

          <!-- Split Mode: Multi-pane workspace + Collapsible Right Inspector Dock -->
          <div v-else class="split-shell">
            <SplitWorkspace
              class="split-stage"
              :devices="devices"
              :panes="splitPanes"
              :mode="layoutMode"
              :ratio="splitRatio"
              :focused-udid="currentFocusedUdid"
              @focus="setFocusedUdid"
              @replace="replaceSplitPane"
              @remove="removeFromSplit"
              @resize-ratio="setSplitRatio"
              @open-single="openDeviceTab"
            />
            <InspectorDock
              v-if="currentFocusedUdid"
              :udid="currentFocusedUdid"
              :open="inspectorOpen"
              @close="toggleInspector"
            />
          </div>
        </template>
      </main>
    </div>
  </div>

  <CommandPalette
    :open="paletteOpen"
    :devices="devices"
    :focused-udid="currentFocusedUdid"
    @close="closePalette"
    @open-device="onPaletteOpenDevice"
    @add-split="onPaletteAddSplit"
    @set-layout="onPaletteSetLayout"
    @select-overview="onPaletteOverview"
    @open-nodes="activeNav = 'nodes'"
    @open-batch="activeNav = 'batch'"
    @toggle-sidebar="toggleSidebar"
    @toggle-inspector="toggleInspector"
  />

  <Toasts />
  <ConfirmDialog />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import DeviceDetailView from "./views/DeviceDetailView.vue";
import LoginView from "./components/LoginView.vue";
import AdminPanel from "./components/AdminPanel.vue";
import BatchPanel from "./components/BatchPanel.vue";
import NodesPanel from "./components/NodesPanel.vue";
import SyncPanel from "./components/SyncPanel.vue";
import DeviceMatrix from "./components/DeviceMatrix.vue";
import NavRail from "./components/NavRail.vue";
import DeviceSidebar from "./components/DeviceSidebar.vue";
import WorkbenchTabs from "./components/WorkbenchTabs.vue";
import SplitWorkspace from "./components/SplitWorkspace.vue";
import InspectorDock from "./components/InspectorDock.vue";
import CommandPalette from "./components/CommandPalette.vue";
import ThemeToggle from "./components/ThemeToggle.vue";
import LanguageSwitcher from "./components/LanguageSwitcher.vue";
import Toasts from "./components/Toasts.vue";
import ConfirmDialog from "./components/ConfirmDialog.vue";
import { useAuth } from "./composables/useAuth";
import { useReservations } from "./composables/useReservations";
import { useBatch } from "./composables/useBatch";
import { useDevices } from "./composables/useDevices";
import { useNodes } from "./composables/useNodes";
import { useSync } from "./composables/useSync";
import { useWorkbench } from "./composables/useWorkbench";
import { useUiI18n } from "./composables/useUiI18n";

const auth = useAuth();
const { t } = useUiI18n();
const { fetchReservations } = useReservations();
const { devices, loading: devicesLoading, refresh: refreshDevices, checkHealth } = useDevices();
const { runningCount: runningBatch } = useBatch();
const { offlineNodes, refresh: refreshNodes } = useNodes();
const { refresh: refreshSync } = useSync();
const {
  sidebarOpen,
  sidebarWidth,
  openTabs,
  activeTab,
  dormantTabs,
  layoutMode,
  splitPanes,
  splitRatio,
  focusedUdid,
  inspectorOpen,
  paletteOpen,
  openDeviceTab,
  closeDeviceTab,
  selectTab,
  toggleSleepTab,
  toggleSidebar,
  setSidebarWidth,
  toggleInspector,
  openPalette,
  closePalette,
  togglePalette,
  setLayoutMode,
  addToSplit,
  removeFromSplit,
  replaceSplitPane,
  setSplitRatio,
  setFocusedUdid,
  reconcileDevices,
} = useWorkbench();

const activeNav = ref("devices");
const sectionTitle = computed(() =>
  activeNav.value === "settings"
    ? t("nav.settings")
    : activeNav.value === "admin"
      ? t("app.admin")
      : activeNav.value === "nodes"
        ? t("nav.nodes")
        : activeNav.value === "batch"
          ? t("nav.batch")
          : t("nav.sync"),
);

const currentFocusedUdid = computed(() => {
  if (layoutMode.value !== "single") {
    if (focusedUdid.value && splitPanes.value.includes(focusedUdid.value)) return focusedUdid.value;
    return splitPanes.value[0] || "";
  }
  if (activeTab.value && activeTab.value !== "overview") return activeTab.value;
  return focusedUdid.value || openTabs.value[0] || "";
});

const ROLE_KEY = { user: "user", admin: "admin", super_admin: "superAdmin" };
const roleLabel = computed(() => t("roles." + (ROLE_KEY[auth.state.user?.role] || "user")));

function onAddToSplit(udid) {
  activeNav.value = "devices";
  addToSplit(udid, devices.value);
}
function onSetLayout(mode) {
  activeNav.value = "devices";
  setLayoutMode(mode, devices.value);
}
function onPaletteOpenDevice(udid) {
  activeNav.value = "devices";
  openDeviceTab(udid);
}
function onPaletteAddSplit(udid) {
  activeNav.value = "devices";
  addToSplit(udid, devices.value);
}
function onPaletteSetLayout(mode) {
  activeNav.value = "devices";
  setLayoutMode(mode, devices.value);
}
function onPaletteOverview() {
  activeNav.value = "devices";
  selectTab("overview");
}

async function doLogout() {
  await auth.logout();
  activeNav.value = "devices";
}

async function loadDevices() {
  await checkHealth();
  await Promise.all([refreshDevices(true), refreshSync(), refreshNodes(true)]);
}
watch(() => auth.state.user, (u) => { if (u) { fetchReservations(); loadDevices(); } });
watch(devices, (list) => { if (list.length) reconcileDevices(list); });

// Global shortcuts: Cmd/Ctrl+K or Double-Shift -> Command Palette; Cmd/Ctrl+B -> Sidebar; Cmd/Ctrl+I -> Inspector.
let lastLeftShiftUp = 0;
let dirtyShiftCombo = false;

function _isEditable(target) {
  const tag = (target?.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || Boolean(target?.isContentEditable);
}

function onGlobalKeyDown(ev) {
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") {
    ev.preventDefault();
    togglePalette();
    return;
  }
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "b" && activeNav.value === "devices") {
    ev.preventDefault();
    toggleSidebar();
    return;
  }
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "i" && activeNav.value === "devices") {
    ev.preventDefault();
    toggleInspector();
    return;
  }
  if (ev.code === "ShiftLeft") {
    if (ev.repeat) return;
  } else {
    dirtyShiftCombo = true;
    lastLeftShiftUp = 0;
  }
}

function onGlobalKeyUp(ev) {
  if (ev.code !== "ShiftLeft" || ev.repeat) return;
  if (dirtyShiftCombo || ev.ctrlKey || ev.metaKey || ev.altKey || _isEditable(ev.target)) {
    dirtyShiftCombo = false;
    lastLeftShiftUp = 0;
    return;
  }
  const now = performance.now();
  if (now - lastLeftShiftUp <= 320) {
    lastLeftShiftUp = 0;
    openPalette();
  } else {
    lastLeftShiftUp = now;
  }
}

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeyDown);
  window.addEventListener("keyup", onGlobalKeyUp);
  await auth.checkAuth();
  if (auth.state.user) { fetchReservations(); loadDevices(); }
  auth.state.ready = true;
});
onUnmounted(() => {
  window.removeEventListener("keydown", onGlobalKeyDown);
  window.removeEventListener("keyup", onGlobalKeyUp);
});
</script>

<style scoped>
.tb-icon-btn {
  min-height: 28px; height: 28px; width: 28px; padding: 0;
  border-radius: 0; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.tb-icon-btn:hover { color: var(--text-strong); border-color: var(--border-strong); background: var(--surface-1); }
.tb-cmd-btn {
  min-height: 28px; height: 28px; padding: 0 7px; font-size: 0.72rem; font-weight: 600;
  border-radius: 0; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.tb-cmd-btn:hover { color: var(--text-strong); border-color: var(--border-strong); background: var(--surface-1); }

.wb-workspace.split-host {
  padding: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.split-shell {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: 8px;
  overflow: hidden;
}
.split-stage {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}
</style>
