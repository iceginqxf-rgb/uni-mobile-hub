import { http } from "./http";

const base = (udid) => `/api/devices/${encodeURIComponent(udid)}`;

export const appsApi = {
  list: (udid) => http.get(`${base(udid)}/apps`),
  running: (udid, system = false) =>
    http.get(`${base(udid)}/running-apps${system ? "?system=1" : ""}`),
  uninstall: (udid, bundle_id) =>
    http.post(`${base(udid)}/apps/uninstall`, { bundle_id }),
  install: (udid, file, onProgress) => {
    const fd = new FormData();
    fd.append("file", file);
    const url = `${base(udid)}/apps/install`;
    return typeof onProgress === "function"
      ? http.postFormWithProgress(url, fd, onProgress)
      : http.postForm(url, fd);
  },
};
