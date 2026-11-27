import { computed, ref } from "vue";
import { batchApi } from "../api/batch";

const jobs = ref([]);
const selectedJobId = ref("");
const loading = ref(false);
const submitting = ref(false);

const runningCount = computed(() => jobs.value.filter((j) => j.status === "running").length);
const selectedJob = computed(
  () => jobs.value.find((j) => j.id === selectedJobId.value) || jobs.value[0] || null,
);

let _pollTimer = null;
let _consumers = 0;

function _stopTimer() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

export function useBatch() {
  async function refreshJobs(silent = false) {
    if (!silent) loading.value = true;
    try {
      const data = await batchApi.listJobs();
      jobs.value = data?.jobs || [];
      if (!selectedJobId.value && jobs.value.length) {
        selectedJobId.value = jobs.value[0].id;
      }
      return jobs.value;
    } finally {
      if (!silent) loading.value = false;
    }
  }

  async function submitInstall(opts) {
    submitting.value = true;
    try {
      const res = await batchApi.install(opts);
      const job = res?.job;
      if (job) {
        selectedJobId.value = job.id;
        await refreshJobs(true);
      }
      return job;
    } finally {
      submitting.value = false;
    }
  }

  async function submitWorkflow(payload) {
    submitting.value = true;
    try {
      const res = await batchApi.workflow(payload);
      const job = res?.job;
      if (job) {
        selectedJobId.value = job.id;
        await refreshJobs(true);
      }
      return job;
    } finally {
      submitting.value = false;
    }
  }

  async function stopJob(jobId) {
    const res = await batchApi.stopJob(jobId);
    await refreshJobs(true);
    return res?.job || null;
  }

  function startPolling() {
    _consumers += 1;
    if (_pollTimer) return;
    _pollTimer = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      if (runningCount.value > 0) {
        refreshJobs(true).catch(() => {});
      }
    }, 1000);
  }

  function stopPolling() {
    _consumers = Math.max(0, _consumers - 1);
    if (_consumers === 0) _stopTimer();
  }

  function exportJobLog(job) {
    if (!job) return;
    const lines = [
      `# uni-mobile-hub batch report`,
      `id: ${job.id}`,
      `name: ${job.name}`,
      `kind: ${job.kind}`,
      `mode: ${job.mode} (retries=${job.retries})`,
      `status: ${job.status} (${job.progress_pct}%)`,
      `targets: ${(job.targets || []).join(", ")}`,
      ``,
      `## Per-Device Summary`,
      ...Object.entries(job.per_device || {}).map(
        ([u, d]) =>
          `${u}\tstatus=${d.status}\tattempts=${d.attempts}\tsteps=${d.ok_steps}/${d.total_steps}\tduration=${d.duration_ms}ms\t${d.error || d.detail || ""}`,
      ),
      ``,
      `## Logs`,
      ...(job.logs || []).map((l) => {
        const ts = new Date(Number(l.ts || 0) * 1000).toISOString();
        return `${ts} [${String(l.level || "info").toUpperCase()}] [${l.udid}] ${l.message}`;
      }),
    ];
    const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `batch-${job.id}.log`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return {
    jobs,
    selectedJobId,
    selectedJob,
    loading,
    submitting,
    runningCount,
    refreshJobs,
    submitInstall,
    submitWorkflow,
    stopJob,
    startPolling,
    stopPolling,
    exportJobLog,
  };
}
