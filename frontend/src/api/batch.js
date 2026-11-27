import { http } from "./http";

export const batchApi = {
  install: ({ file, targets, mode = "parallel", retries = 0, name = "" }) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("targets", JSON.stringify(targets || []));
    fd.append("mode", mode);
    fd.append("retries", String(retries));
    if (name) fd.append("name", name);
    return http.postForm("/api/batch/install", fd);
  },
  workflow: (payload) => http.post("/api/batch/workflow", payload),
  listJobs: () => http.get("/api/batch/jobs"),
  getJob: (jobId) => http.get(`/api/batch/jobs/${encodeURIComponent(jobId)}`),
  stopJob: (jobId) => http.post(`/api/batch/jobs/${encodeURIComponent(jobId)}/stop`, {}),
};
