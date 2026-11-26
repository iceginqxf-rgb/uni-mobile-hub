import { http } from "./http";

export const syncApi = {
  status: () => http.get("/api/sync/status"),
  setGroup: (master, slaves) => http.post("/api/sync/group", { master, slaves }),
  clearGroup: (master) => http.del(`/api/sync/group/${encodeURIComponent(master)}`),
  clearAll: () => http.del("/api/sync/group"),
};
