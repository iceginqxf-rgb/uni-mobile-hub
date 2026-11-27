import { reactive } from "vue";
import { reservationsApi } from "../api/reservations";
import { useSocket } from "./useSocket";
import { useAuth } from "./useAuth";

// Shared reservation state (module singleton): device_id → reservation.
const state = reactive({
  byDevice: {},
  maxMinutes: 240,
  defaultMinutes: 60,
  loaded: false,
});
let _bound = false;
let _refetchTimer = null;

export function useReservations() {
  const { on } = useSocket();

  async function fetchReservations() {
    try {
      const d = await reservationsApi.list();
      const map = {};
      for (const r of d.reservations || []) map[r.device_id] = r;
      state.byDevice = map;
      state.maxMinutes = d.max_minutes ?? state.maxMinutes;
      state.defaultMinutes = d.default_minutes ?? state.defaultMinutes;
      state.loaded = true;
    } catch {
      /* not logged in / auth off — leave empty */
    }
  }

  function _debouncedRefetch() {
    clearTimeout(_refetchTimer);
    _refetchTimer = setTimeout(fetchReservations, 120);
  }

  async function claim(deviceId, minutes) {
    await reservationsApi.claim(deviceId, minutes || state.defaultMinutes);
    await fetchReservations();
  }
  async function release(deviceId) {
    await reservationsApi.release(deviceId);
    await fetchReservations();
  }

  // Live updates: any claim/release anywhere → refetch.
  if (!_bound) {
    _bound = true;
    on("reservation_changed", _debouncedRefetch);
    on("device_released", _debouncedRefetch);
  }

  const get = (deviceId) => state.byDevice[deviceId] || null;

  // Consistent reservation gate in UI: EVERY user (including admin) clicks
  // 占用 to unlock a device's stream & control surface, preventing accidental
  // unreserved manipulation while keeping admin multi-device & force-release.
  function canControl(deviceId) {
    return !!get(deviceId)?.is_mine;
  }

  return { state, fetchReservations, claim, release, get, canControl };
}
