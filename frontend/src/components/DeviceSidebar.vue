<template>
  <aside class="wb-sidebar" :style="{ width: width + 'px' }" aria-label="devices">
    <div class="sb-head">
      <div class="sb-title-row">
        <span class="sb-title">{{ t("workbench.sidebar") }}</span>
        <span class="sb-count mono">{{ liveCount }}/{{ devices.length }}</span>
      </div>
      <div class="row" style="gap: 4px">
        <button class="sb-icon-btn" :title="t('devices.refresh')" :disabled="loading" @click="$emit('refresh')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: loading }">
            <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
          </svg>
        </button>
        <button class="sb-icon-btn" :title="t('workbench.collapseSidebar')" @click="$emit('collapse')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="11 17 6 12 11 7" /><polyline points="18 17 13 12 18 7" />
          </svg>
        </button>
      </div>
    </div>

    <div class="sb-controls">
      <input
        v-model.trim="query"
        type="search"
        class="sb-search"
        :placeholder="t('workbench.searchPlaceholder')"
      />
      <div class="sb-filters">
        <button class="sb-flt" :class="{ active: osFilter === 'all' }" @click="osFilter = 'all'">
          {{ t("devices.filterAll") }}
        </button>
        <button class="sb-flt" :class="{ active: osFilter === 'ios' }" @click="osFilter = 'ios'">
          iOS
        </button>
        <button class="sb-flt" :class="{ active: osFilter === 'android' }" @click="osFilter = 'android'">
          AND
        </button>
      </div>
    </div>

    <div class="sb-tree">
      <p v-if="!grouped.length" class="muted sb-empty">{{ t("workbench.noMatches") }}</p>

      <div v-for="grp in grouped" :key="grp.node" class="sb-group">
        <button type="button" class="sb-group-head" @click="toggleGroup(grp.node)">
          <svg class="sb-chev" :class="{ collapsed: collapsed[grp.node] }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
          <span class="sb-group-name mono">{{ grp.label }}</span>
          <span class="sb-group-cnt mono">{{ grp.items.length }}</span>
        </button>

        <div v-show="!collapsed[grp.node]" class="sb-items">
          <button
            v-for="d in grp.items"
            :key="d.udid"
            type="button"
            class="sb-row"
            :class="{ active: d.udid === activeUdid }"
            :title="`${d.marketing || d.name || d.udid}\n${d.udid}`"
            @click="$emit('select', d.udid)"
          >
            <span class="sb-dot" :class="dotClass(d)" />
            <span class="sb-os mono" :class="d.platform === 'android' ? 'and' : 'ios'">
              {{ d.platform === 'android' ? 'AND' : 'iOS' }}
            </span>
            <span class="sb-meta">
              <span class="sb-name">{{ d.marketing || d.name || d.udid.slice(0, 12) }}</span>
              <span class="sb-sub mono">
                <span>{{ d.os_version || d.ios_version || d.product_type || d.udid.slice(0, 8) }}</span>
                <span v-if="holderText(d.udid)" class="sb-holder" :class="{ mine: isMine(d.udid) }">
                  · {{ holderText(d.udid) }}
                </span>
              </span>
            </span>
            <span v-if="openSet.has(d.udid)" class="sb-tab-mark" :title="t('workbench.tabOpen')" />
          </button>
        </div>
      </div>
    </div>

    <div
      class="wb-resizer"
      :class="{ dragging }"
      role="separator"
      aria-orientation="vertical"
      @pointerdown.prevent="startResize"
    />
  </aside>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref } from "vue";
import { useReservations } from "../composables/useReservations";
import { useUiI18n } from "../composables/useUiI18n";

const props = defineProps({
  devices: { type: Array, default: () => [] },
  activeUdid: { type: String, default: "" },
  openTabs: { type: Array, default: () => [] },
  width: { type: Number, default: 256 },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(["select", "refresh", "collapse", "resize"]);

const { t } = useUiI18n();
const { get: getReservation } = useReservations();

const query = ref("");
const osFilter = ref("all");
const collapsed = reactive({});
const dragging = ref(false);

const openSet = computed(() => new Set(props.openTabs));
const liveCount = computed(() => props.devices.filter((d) => d.connected || d.streaming).length);

const filtered = computed(() => {
  const q = query.value.toLowerCase();
  return props.devices.filter((d) => {
    if (osFilter.value === "android" && d.platform !== "android") return false;
    if (osFilter.value === "ios" && d.platform === "android") return false;
    if (!q) return true;
    return (
      (d.marketing || "").toLowerCase().includes(q) ||
      (d.name || "").toLowerCase().includes(q) ||
      (d.udid || "").toLowerCase().includes(q) ||
      (d.node_id || "").toLowerCase().includes(q) ||
      (d.product_type || "").toLowerCase().includes(q)
    );
  });
});

const grouped = computed(() => {
  const map = new Map();
  for (const d of filtered.value) {
    const node = d.node_id || "local";
    if (!map.has(node)) map.set(node, []);
    map.get(node).push(d);
  }
  const entries = Array.from(map.entries()).sort(([a], [b]) => {
    if (a === "local") return -1;
    if (b === "local") return 1;
    return a.localeCompare(b);
  });
  return entries.map(([node, items]) => ({
    node,
    label: node === "local" ? t("workbench.localNode") : node,
    items,
  }));
});

function toggleGroup(node) {
  collapsed[node] = !collapsed[node];
}

function dotClass(d) {
  if (d.streaming || d.connected) return "on";
  const r = getReservation(d.udid);
  if (r && !r.is_mine) return "warn";
  return "idle";
}

function isMine(udid) {
  return !!getReservation(udid)?.is_mine;
}

function holderText(udid) {
  const r = getReservation(udid);
  if (!r) return "";
  return r.is_mine ? t("reservation.yours") : r.username;
}

let startX = 0;
let startW = 256;
function onMove(ev) {
  if (!dragging.value) return;
  emit("resize", startW + (ev.clientX - startX));
}
function onUp() {
  if (!dragging.value) return;
  dragging.value = false;
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("pointerup", onUp);
}
function startResize(ev) {
  dragging.value = true;
  startX = ev.clientX;
  startW = props.width;
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}
onUnmounted(onUp);
</script>

<style scoped>
.sb-head {
  height: var(--tabbar-h);
  flex: 0 0 var(--tabbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px 0 12px;
  border-bottom: 1px solid var(--border);
}
.sb-title-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.sb-title { font-size: 0.78rem; font-weight: 650; text-transform: uppercase; letter-spacing: 0.4px; color: var(--muted); }
.sb-count { font-size: 0.72rem; color: var(--muted); background: var(--surface-2); border: 1px solid var(--border); padding: 1px 6px; border-radius: 999px; }
.sb-icon-btn {
  min-height: 26px; height: 26px; width: 26px; padding: 0;
  border-radius: 5px; border: 1px solid transparent; background: transparent; color: var(--muted);
}
.sb-icon-btn:hover:not(:disabled) { background: var(--surface-1); border-color: var(--border); color: var(--text-strong); }
.sb-icon-btn svg { width: 14px; height: 14px; }
.sb-icon-btn svg.spin { animation: topbar-spin 0.8s linear infinite; }

.sb-controls {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sb-search { width: 100%; min-height: 28px; height: 28px; padding: 2px 8px; font-size: 0.8rem; }
.sb-filters { display: flex; gap: 4px; }
.sb-flt {
  flex: 1; min-height: 24px; height: 24px; padding: 0 6px; font-size: 0.72rem; font-weight: 600;
  border-radius: 5px; background: var(--inset); border: 1px solid var(--border); color: var(--muted);
}
.sb-flt.active {
  background: color-mix(in srgb, var(--primary) 16%, transparent);
  border-color: color-mix(in srgb, var(--primary) 45%, transparent);
  color: var(--text-strong);
}

.sb-tree { flex: 1; overflow: auto; padding: 6px; display: flex; flex-direction: column; gap: 6px; }
.sb-empty { text-align: center; font-size: 0.78rem; padding: 20px 8px; margin: 0; }
.sb-group { display: flex; flex-direction: column; gap: 2px; }
.sb-group-head {
  width: 100%; min-height: 26px; height: 26px; padding: 0 6px; justify-content: flex-start; gap: 5px;
  background: transparent; border: none; border-radius: 5px; color: var(--muted); font-size: 0.72rem; font-weight: 600;
}
.sb-group-head:hover { background: var(--surface-1); color: var(--text); }
.sb-chev { width: 12px; height: 12px; transition: transform 0.14s ease; flex: none; }
.sb-chev.collapsed { transform: rotate(-90deg); }
.sb-group-name { flex: 1; text-align: left; overflow: hidden; text-overflow: ellipsis; }
.sb-group-cnt { font-size: 0.68rem; color: var(--muted); }

.sb-items { display: flex; flex-direction: column; gap: 2px; padding-left: 4px; }
.sb-row {
  width: 100%; min-height: 40px; padding: 5px 8px; justify-content: flex-start; gap: 7px;
  border: 1px solid transparent; border-radius: 6px; background: transparent; text-align: left;
}
.sb-row:hover { background: var(--surface-1); border-color: transparent; }
.sb-row.active {
  background: color-mix(in srgb, var(--primary) 14%, transparent);
  border-color: color-mix(in srgb, var(--primary) 40%, transparent);
}
.sb-dot { width: 6px; height: 6px; border-radius: 50%; flex: none; background: var(--muted); opacity: 0.55; }
.sb-dot.on { background: var(--ok); opacity: 1; box-shadow: 0 0 0 2px color-mix(in srgb, var(--ok) 22%, transparent); }
.sb-dot.warn { background: var(--warn); opacity: 1; }

.sb-os {
  font-size: 0.64rem; font-weight: 700; padding: 1px 4px; border-radius: 4px; flex: none;
}
.sb-os.and { background: rgba(34, 197, 94, 0.14); color: var(--ok); }
.sb-os.ios { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--primary-2); }

.sb-meta { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 1px; }
.sb-name { font-size: 0.8rem; font-weight: 600; color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sb-sub { font-size: 0.68rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sb-holder { color: var(--warn); }
.sb-holder.mine { color: var(--ok); }
.sb-tab-mark { width: 5px; height: 5px; border-radius: 50%; background: var(--primary); flex: none; }
</style>
