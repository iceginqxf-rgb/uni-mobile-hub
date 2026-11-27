import { ref } from "vue";
import { syncApi } from "../api/sync";

const groups = ref({});
const saving = ref(false);
const loaded = ref(false);

export function useSync() {
  async function refresh() {
    try {
      const res = await syncApi.status();
      groups.value = res?.groups || res?.data?.groups || {};
      loaded.value = true;
    } catch {
      /* ignore when not authed */
    }
    return groups.value;
  }

  function masterOf(udid) {
    if (!udid) return "";
    for (const [m, slaves] of Object.entries(groups.value)) {
      if (Array.isArray(slaves) && slaves.includes(udid)) return m;
    }
    return "";
  }

  function isMaster(udid) {
    return Boolean(udid && Array.isArray(groups.value[udid]) && groups.value[udid].length > 0);
  }

  function isSlave(udid) {
    return Boolean(masterOf(udid));
  }

  function activeMaster() {
    for (const [m, slaves] of Object.entries(groups.value)) {
      if (Array.isArray(slaves) && slaves.length > 0) return m;
    }
    return "";
  }

  async function setGroup(master, slaves) {
    saving.value = true;
    try {
      const res = await syncApi.setGroup(master, slaves);
      groups.value = res?.groups || res?.data?.groups || {};
      loaded.value = true;
      return groups.value;
    } finally {
      saving.value = false;
    }
  }

  async function clearGroup(master) {
    saving.value = true;
    try {
      const res = await syncApi.clearGroup(master);
      groups.value = res?.groups || res?.data?.groups || {};
      return groups.value;
    } finally {
      saving.value = false;
    }
  }

  async function clearAll() {
    saving.value = true;
    try {
      const res = await syncApi.clearAll();
      groups.value = res?.groups || res?.data?.groups || {};
      return groups.value;
    } finally {
      saving.value = false;
    }
  }

  async function setMaster(udid, candidateSlaves = []) {
    if (!udid) return;
    if (isMaster(udid)) {
      return await clearGroup(udid);
    }
    const slaves = candidateSlaves.filter((id) => id && id !== udid);
    if (!slaves.length) return groups.value;
    // Ensure a clean single-master group when reassigning inline in split mode
    if (activeMaster() && activeMaster() !== udid) {
      await clearAll();
    }
    return await setGroup(udid, slaves);
  }

  async function toggleSlave(slaveUdid, fallbackMasterUdid = "") {
    if (!slaveUdid) return;
    const currentOwner = masterOf(slaveUdid);
    if (currentOwner) {
      const remaining = (groups.value[currentOwner] || []).filter((id) => id !== slaveUdid);
      if (remaining.length) return await setGroup(currentOwner, remaining);
      return await clearGroup(currentOwner);
    }
    const targetMaster = activeMaster() || fallbackMasterUdid;
    if (!targetMaster || targetMaster === slaveUdid) return groups.value;
    const existing = Array.isArray(groups.value[targetMaster]) ? groups.value[targetMaster] : [];
    const next = existing.includes(slaveUdid) ? existing : [...existing, slaveUdid];
    return await setGroup(targetMaster, next);
  }

  return {
    groups,
    saving,
    loaded,
    refresh,
    masterOf,
    isMaster,
    isSlave,
    activeMaster,
    setGroup,
    clearGroup,
    clearAll,
    setMaster,
    toggleSlave,
  };
}
