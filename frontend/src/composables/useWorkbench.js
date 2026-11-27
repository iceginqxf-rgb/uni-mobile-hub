import { reactive, ref, watch } from "vue";

const STORAGE_KEY = "umh-workbench-v1";
const MIN_W = 200;
const MAX_W = 400;
const clampW = (n) => Math.max(MIN_W, Math.min(MAX_W, Math.round(Number(n) || 256)));
const clampRatio = (r) => Math.max(0.25, Math.min(0.75, Number(r) || 0.5));
const VALID_LAYOUTS = ["single", "split-2", "split-grid"];

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
const layoutMode = ref(VALID_LAYOUTS.includes(saved.layoutMode) ? saved.layoutMode : "single");
const splitPanes = ref(Array.isArray(saved.splitPanes) ? saved.splitPanes.filter((x) => typeof x === "string" && x).slice(0, 4) : []);
const splitRatio = ref(clampRatio(saved.splitRatio));
const focusedUdid = ref(typeof saved.focusedUdid === "string" ? saved.focusedUdid : "");
const inspectorOpen = ref(saved.inspectorOpen !== undefined ? Boolean(saved.inspectorOpen) : true);
const paletteOpen = ref(false);
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
        layoutMode: layoutMode.value,
        splitPanes: splitPanes.value,
        splitRatio: splitRatio.value,
        focusedUdid: focusedUdid.value,
        inspectorOpen: inspectorOpen.value,
      }),
    );
  } catch {
    /* ignore */
  }
}

watch(
  [sidebarOpen, sidebarWidth, openTabs, activeTab, layoutMode, splitPanes, splitRatio, focusedUdid, inspectorOpen],
  _persist,
  { deep: true },
);

export function useWorkbench() {
  function openDeviceTab(udid) {
    if (!udid) return;
    if (!openTabs.value.includes(udid)) {
      openTabs.value = [...openTabs.value, udid];
    }
    delete dormantTabs[udid];
    activeTab.value = udid;
    focusedUdid.value = udid;
    layoutMode.value = "single";
  }

  function closeDeviceTab(udid) {
    const idx = openTabs.value.indexOf(udid);
    if (idx === -1) return;
    const next = openTabs.value.filter((id) => id !== udid);
    openTabs.value = next;
    delete dormantTabs[udid];
    if (activeTab.value === udid) {
      const nextId = next[idx - 1] || next[idx] || "overview";
      activeTab.value = nextId;
      if (nextId !== "overview") focusedUdid.value = nextId;
      else if (focusedUdid.value === udid) focusedUdid.value = next[0] || "";
    }
  }

  function selectTab(id) {
    const next = id || "overview";
    activeTab.value = next;
    layoutMode.value = "single";
    if (next !== "overview") {
      delete dormantTabs[next];
      focusedUdid.value = next;
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

  function toggleInspector() {
    inspectorOpen.value = !inspectorOpen.value;
  }

  function openPalette() {
    paletteOpen.value = true;
  }
  function closePalette() {
    paletteOpen.value = false;
  }
  function togglePalette() {
    paletteOpen.value = !paletteOpen.value;
  }

  function setLayoutMode(mode, allDevices = []) {
    if (!VALID_LAYOUTS.includes(mode)) return;
    layoutMode.value = mode;
    if (mode === "single") {
      if (activeTab.value === "overview" && focusedUdid.value && openTabs.value.includes(focusedUdid.value)) {
        activeTab.value = focusedUdid.value;
      }
      return;
    }
    const targetCount = mode === "split-2" ? 2 : Math.min(4, Math.max(2, (allDevices || []).length || 2));
    const ordered = [];
    const pushUnique = (id) => {
      if (id && !ordered.includes(id) && ordered.length < 4) ordered.push(id);
    };
    pushUnique(focusedUdid.value);
    for (const id of splitPanes.value) pushUnique(id);
    if (activeTab.value && activeTab.value !== "overview") pushUnique(activeTab.value);
    for (const id of openTabs.value) pushUnique(id);
    for (const d of allDevices || []) pushUnique(d.udid);

    splitPanes.value = ordered.slice(0, mode === "split-2" ? 2 : Math.max(ordered.length, targetCount));
    if (splitPanes.value.length && !splitPanes.value.includes(focusedUdid.value)) {
      focusedUdid.value = splitPanes.value[0];
    }
  }

  function addToSplit(udid, allDevices = []) {
    if (!udid) return;
    if (layoutMode.value === "single") {
      const seed = activeTab.value !== "overview" ? activeTab.value : focusedUdid.value;
      const next = [];
      if (seed && seed !== udid) next.push(seed);
      next.push(udid);
      if (next.length < 2) {
        const other = (allDevices || []).find((d) => d.udid !== udid)?.udid;
        if (other) next.push(other);
      }
      splitPanes.value = next.slice(0, 4);
      layoutMode.value = splitPanes.value.length > 2 ? "split-grid" : "split-2";
      focusedUdid.value = udid;
      return;
    }
    if (!splitPanes.value.includes(udid)) {
      const next = [...splitPanes.value, udid].slice(0, 4);
      splitPanes.value = next;
      if (next.length > 2) layoutMode.value = "split-grid";
    }
    focusedUdid.value = udid;
  }

  function removeFromSplit(udid) {
    const next = splitPanes.value.filter((id) => id !== udid);
    splitPanes.value = next;
    if (next.length < 2) {
      const rem = next[0] || "";
      layoutMode.value = "single";
      if (rem) {
        if (!openTabs.value.includes(rem)) openTabs.value = [...openTabs.value, rem];
        activeTab.value = rem;
        focusedUdid.value = rem;
      }
      return;
    }
    if (next.length === 2 && layoutMode.value === "split-grid") {
      layoutMode.value = "split-2";
    }
    if (focusedUdid.value === udid) {
      focusedUdid.value = next[0] || "";
    }
  }

  function replaceSplitPane(idx, udid) {
    if (!udid || idx < 0 || idx >= splitPanes.value.length) return;
    const prev = splitPanes.value[idx];
    if (prev === udid) return;
    const next = [...splitPanes.value];
    const dupIdx = next.indexOf(udid);
    if (dupIdx !== -1) {
      next[dupIdx] = prev;
    }
    next[idx] = udid;
    splitPanes.value = next;
    focusedUdid.value = udid;
  }

  function setSplitRatio(r) {
    splitRatio.value = clampRatio(r);
  }

  function setFocusedUdid(udid) {
    if (udid) focusedUdid.value = udid;
  }

  function reconcileDevices(devices) {
    const valid = new Set((devices || []).map((d) => d.udid));
    if (!valid.size) return;
    const keptTabs = openTabs.value.filter((id) => valid.has(id));
    if (keptTabs.length !== openTabs.value.length) {
      openTabs.value = keptTabs;
      for (const id of Object.keys(dormantTabs)) {
        if (!valid.has(id)) delete dormantTabs[id];
      }
      if (activeTab.value !== "overview" && !valid.has(activeTab.value)) {
        activeTab.value = keptTabs[0] || "overview";
      }
    }
    const keptPanes = splitPanes.value.filter((id) => valid.has(id));
    if (keptPanes.length !== splitPanes.value.length) {
      splitPanes.value = keptPanes;
      if (layoutMode.value !== "single" && keptPanes.length < 2) {
        layoutMode.value = "single";
      }
    }
    if (focusedUdid.value && !valid.has(focusedUdid.value)) {
      focusedUdid.value = keptPanes[0] || keptTabs[0] || "";
    }
  }

  return {
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
  };
}
