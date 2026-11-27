// Tiny fetch wrapper that understands the backend's unified envelope:
//   success: { success:true, data, message }
//   failure: { success:false, code, message, detail }
// Throws an Error (with .code/.detail) on failure so callers can try/catch.

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let payload = {};
  try {
    payload = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok || payload.success === false) {
    const err = new Error(payload.message || `Request failed (${res.status})`);
    err.code = payload.code || "HTTP_ERROR";
    err.detail = payload.detail || {};
    throw err;
  }
  return payload.data;
}

// Multipart upload (e.g. .ipa). No Content-Type header → the browser sets the
// multipart boundary itself.
async function postForm(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  let payload = {};
  try {
    payload = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok || payload.success === false) {
    const err = new Error(payload.message || `Request failed (${res.status})`);
    err.code = payload.code || "HTTP_ERROR";
    err.detail = payload.detail || {};
    throw err;
  }
  return payload.data;
}

// Multipart upload with optional XHR progress callback (pct, loaded, total).
function postFormWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path, true);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && typeof onProgress === "function") {
        const pct = Math.min(100, Math.round((ev.loaded / ev.total) * 100));
        onProgress(pct, ev.loaded, ev.total);
      }
    };
    xhr.onload = () => {
      let payload = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* non-JSON */
      }
      if (xhr.status < 200 || xhr.status >= 300 || payload.success === false) {
        const err = new Error(payload.message || `Request failed (${xhr.status})`);
        err.code = payload.code || "HTTP_ERROR";
        err.detail = payload.detail || {};
        reject(err);
        return;
      }
      resolve(payload.data);
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(formData);
  });
}

export const http = {
  get: (p) => request("GET", p),
  post: (p, body) => request("POST", p, body),
  put: (p, body) => request("PUT", p, body),
  del: (p) => request("DELETE", p),
  postForm,
  postFormWithProgress,
};
