import { http } from "./http";

const base = (udid) => `/api/devices/${encodeURIComponent(udid)}`;

export const filesApi = {
  tree: (udid, path = ".") =>
    http.get(`${base(udid)}/files/tree?path=${encodeURIComponent(path)}`),
  // pull is a raw streaming download — return the URL for the browser to fetch.
  pullUrl: (udid, path) => `${base(udid)}/files/pull?path=${encodeURIComponent(path)}`,
  // inline=1 streams with the file's mimetype (no attachment) so the browser
  // previews images/audio/video in a new tab.
  previewUrl: (udid, path) => `${base(udid)}/files/pull?inline=1&path=${encodeURIComponent(path)}`,
  push: (udid, file, dst_path, onProgress) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dst_path", dst_path);
    const url = `${base(udid)}/files/push`;
    return typeof onProgress === "function"
      ? http.postFormWithProgress(url, fd, onProgress)
      : http.postForm(url, fd);
  },
};
