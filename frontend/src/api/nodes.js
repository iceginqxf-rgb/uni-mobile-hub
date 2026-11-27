import { http } from "./http";

export const nodesApi = {
  list: () => http.get("/api/nodes"),
  reconnect: (nodeId) => http.post(`/api/nodes/${encodeURIComponent(nodeId)}/reconnect`, {}),
};
