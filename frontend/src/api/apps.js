import { http } from "./http";

const base = (udid) => `/api/devices/${encodeURIComponent(udid)}`;

export const appsApi = {
  list: (udid) => http.get(`${base(udid)}/apps`),
  running: (udid, system = false) =>
    http.get(`${base(udid)}/running-apps${system ? "?system=1" : ""}`),
  uninstall: (udid, bundle_id) =>
    http.post(`${base(udid)}/apps/uninstall`, { bundle_id }),
  install: (udid, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return http.postForm(`${base(udid)}/apps/install`, fd);
  },
};
