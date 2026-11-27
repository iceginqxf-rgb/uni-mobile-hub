import { ref } from "vue";

const MIME_CANDIDATES = [
  { mime: "video/mp4;codecs=avc1.42E01E", ext: "mp4" },
  { mime: "video/mp4", ext: "mp4" },
  { mime: "video/webm;codecs=vp9", ext: "webm" },
  { mime: "video/webm;codecs=vp8", ext: "webm" },
  { mime: "video/webm", ext: "webm" },
];

function _pickMime() {
  if (typeof MediaRecorder === "undefined") return null;
  for (const item of MIME_CANDIDATES) {
    try {
      if (!MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(item.mime)) {
        return item;
      }
    } catch {
      /* try next */
    }
  }
  return { mime: "", ext: "webm" };
}

function _safeSlug(name) {
  return String(name || "device")
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32) || "device";
}

function _timestampTag() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  );
}

export function useScreenRecorder() {
  const recording = ref(false);
  const elapsedSec = ref(0);
  const error = ref("");
  const lastClip = ref(null); // { filename, sizeBytes, ext, url }

  let _recorder = null;
  let _chunks = [];
  let _timer = null;
  let _paintTimer = null;
  let _ownedStream = null;
  let _onSavedCb = null;

  function _clearTimers() {
    if (_timer) {
      clearInterval(_timer);
      _timer = null;
    }
    if (_paintTimer) {
      clearInterval(_paintTimer);
      _paintTimer = null;
    }
    if (_ownedStream) {
      try {
        _ownedStream.getTracks().forEach((tr) => tr.stop());
      } catch {
        /* ignore */
      }
      _ownedStream = null;
    }
  }

  function _captureFromImg(imgEl) {
    const w = imgEl.naturalWidth || imgEl.clientWidth || 720;
    const h = imgEl.naturalHeight || imgEl.clientHeight || 1280;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    const draw = () => {
      if (!recording.value || !imgEl.complete || !imgEl.naturalWidth) return;
      try {
        ctx.drawImage(imgEl, 0, 0, canvas.width, canvas.height);
      } catch {
        /* ignore transient cross-frame decode */
      }
    };
    draw();
    _paintTimer = setInterval(draw, 40); // ~25 fps
    return canvas.captureStream(25);
  }

  function _triggerDownload(blob, filename) {
    if (lastClip.value?.url) {
      try {
        URL.revokeObjectURL(lastClip.value.url);
      } catch {
        /* ignore */
      }
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return url;
  }

  function start({ mediaStream = null, mediaEl = null, deviceName = "device", onSaved = null } = {}) {
    if (recording.value) return false;
    error.value = "";
    const picked = _pickMime();
    if (!picked) {
      error.value = "MediaRecorder unsupported in this browser";
      return false;
    }

    let sourceStream = null;
    try {
      if (mediaStream && mediaStream.getVideoTracks && mediaStream.getVideoTracks().length > 0) {
        sourceStream = mediaStream;
      } else if (mediaEl && typeof mediaEl.captureStream === "function") {
        sourceStream = mediaEl.captureStream(30);
        _ownedStream = sourceStream;
      } else if (mediaEl && mediaEl.tagName === "IMG") {
        recording.value = true;
        sourceStream = _captureFromImg(mediaEl);
        _ownedStream = sourceStream;
      }
    } catch (e) {
      recording.value = false;
      _clearTimers();
      error.value = e?.message || "Failed to capture video stream";
      return false;
    }

    if (!sourceStream) {
      recording.value = false;
      _clearTimers();
      error.value = "No active video stream to record";
      return false;
    }

    _chunks = [];
    _onSavedCb = onSaved;
    const recOpts = picked.mime ? { mimeType: picked.mime } : undefined;
    try {
      _recorder = new MediaRecorder(sourceStream, recOpts);
    } catch (e) {
      recording.value = false;
      _clearTimers();
      error.value = e?.message || "Unable to start MediaRecorder";
      return false;
    }

    const chosenExt = picked.ext;
    const chosenName = `umh-${_safeSlug(deviceName)}-${_timestampTag()}.${chosenExt}`;
    const chosenMime = _recorder.mimeType || picked.mime || `video/${chosenExt}`;

    _recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) _chunks.push(ev.data);
    };
    _recorder.onstop = () => {
      recording.value = false;
      _clearTimers();
      const blob = new Blob(_chunks, { type: chosenMime });
      _chunks = [];
      _recorder = null;
      if (blob.size > 0) {
        const url = _triggerDownload(blob, chosenName);
        const info = { filename: chosenName, sizeBytes: blob.size, ext: chosenExt, url };
        lastClip.value = info;
        _onSavedCb?.(info);
      }
    };
    _recorder.onerror = (ev) => {
      error.value = ev?.error?.message || "Recorder error";
      stop();
    };

    recording.value = true;
    elapsedSec.value = 0;
    _timer = setInterval(() => {
      elapsedSec.value += 1;
    }, 1000);
    _recorder.start(500);
    return true;
  }

  function stop() {
    if (!recording.value && !_recorder) {
      _clearTimers();
      return;
    }
    recording.value = false;
    try {
      if (_recorder && _recorder.state !== "inactive") {
        _recorder.stop();
        return;
      }
    } catch {
      /* ignore */
    }
    _clearTimers();
    _recorder = null;
  }

  function dispose() {
    stop();
    if (lastClip.value?.url) {
      try {
        URL.revokeObjectURL(lastClip.value.url);
      } catch {
        /* ignore */
      }
      lastClip.value = null;
    }
  }

  return { recording, elapsedSec, error, lastClip, start, stop, dispose };
}
