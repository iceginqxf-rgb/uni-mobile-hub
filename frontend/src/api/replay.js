import { http } from "./http";

export const replayApi = {
  run: (payload) => http.post("/api/replay/run", payload),
  listJobs: () => http.get("/api/replay/jobs"),
  getJob: (jobId) => http.get(`/api/replay/jobs/${encodeURIComponent(jobId)}`),
  stopJob: (jobId) => http.post(`/api/replay/jobs/${encodeURIComponent(jobId)}/stop`, {}),
};
