import { ref } from "vue";

const taskSwitcherUdid = ref("");

export function openTaskSwitcher(udid) {
  taskSwitcherUdid.value = udid || "";
}

export function closeTaskSwitcher() {
  taskSwitcherUdid.value = "";
}

export function useTaskSwitcher() {
  return { taskSwitcherUdid, openTaskSwitcher, closeTaskSwitcher };
}
