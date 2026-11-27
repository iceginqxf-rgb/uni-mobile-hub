import { reactive, ref, watch } from "vue";

const STORAGE_KEY = "umh-workbench-v1";
const MIN_W = 200;
const MAX_W = 400;
const clampW = (n) => Math.max(MIN_W, Math.min(MAX_W, Math.round(Number(n) || 256)));

function _load() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

const saved = _load();
const sidebarOpen = ref(saved.sidebarOpen !== undefined ? Boolean(saved.sidebarOpen) : true);
const sidebarWidth = ref(clampW(saved.sidebarWidth));
const openTabs = ref(Array.isArray(saved.openTabs) ? saved.openTabs.filter((x) => typeof x === "string" && x) : []);
const activeTab = ref(typeof saved.activeTab === "string" && saved.activeTab ? saved.activeTab : "overview");
const dormantTabs = reactive({});

function _persist() {
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        sidebarOpen: sidebarOpen.value,
        sidebarWidth: sidebarWidth.value,
        openTabs: openTabs.value,
        activeTab: activeTab.value,
      }),
    );
  } catch {
    /* ignore */
  }
}

watch([sidebarOpen, sidebarWidth, openTabs, activeTab], _persist, { deep: true });

export function useWorkbench() {
  function openDeviceTab(udid) {
    if (!udid) return;
    if (!openTabs.value.includes(udid)) {
      openTabs.value = [...openTabs.value, udid];
    }
    delete dormantTabs[udid];
    activeTab.value = udid;
  }

  function closeDeviceTab(udid) {
    const idx = openTabs.value.indexOf(udid);
    if (idx === -1) return;
    const next = openTabs.value.filter((id) => id !== udid);
    openTabs.value = next;
    delete dormantTabs[udid];
    if (activeTab.value === udid) {
      activeTab.value = next[idx - 1] || next[idx] || "overview";
    }
  }

  function selectTab(id) {
    activeTab.value = id || "overview";
    if (id && id !== "overview") {
      delete dormantTabs[id];
    }
  }

  function toggleSleepTab(udid) {
    if (!udid) return;
    if (dormantTabs[udid]) delete dormantTabs[udid];
    else dormantTabs[udid] = true;
  }

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value;
  }

  function setSidebarWidth(w) {
    sidebarWidth.value = clampW(w);
  }

  function reconcileDevices(devices) {
    const valid = new Set((devices || []).map((d) => d.udid));
    if (!valid.size) return;
    const kept = openTabs.value.filter((id) => valid.has(id));
    if (kept.length !== openTabs.value.length) {
      openTabs.value = kept;
      for (const id of Object.keys(dormantTabs)) {
        if (!valid.has(id)) delete dormantTabs[id];
      }
      if (activeTab.value !== "overview" && !valid.has(activeTab.value)) {
        activeTab.value = kept[0] || "overview";
      }
    }
  }

  return {
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
  };
}
