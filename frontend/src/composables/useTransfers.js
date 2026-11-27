import { computed, reactive, ref, unref } from "vue";
import { appsApi } from "../api/apps";
import { filesApi } from "../api/files";

const MAX_ITEMS = 30;
const transfers = ref([]);
let seq = 0;

function _pushItem(entry) {
  const item = reactive(entry);
  transfers.value = [item, ...transfers.value].slice(0, MAX_ITEMS);
  return item;
}

/**
 * Shared per-device upload & drag-and-drop installer queue.
 * Syncs live progress across DeviceStage and Inspector FilesPanel.
 */
export function useTransfers() {
  function transfersFor(udid) {
    return computed(() => {
      const target = unref(udid);
      if (!target) return [];
      return transfers.value.filter((x) => x.udid === target);
    });
  }

  function activeFor(udid) {
    const list = transfersFor(udid);
    return computed(() =>
      list.value.filter((x) => x.status === "uploading" || x.status === "installing"),
    );
  }

  async function uploadFile(udid, file, { isAndroid = false, dstDir = "", forceFile = false } = {}) {
    if (!udid || !file) return null;
    const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
    const isPkg = !forceFile && (ext === "apk" || ext === "ipa");

    if (isPkg) {
      if ((ext === "apk" && !isAndroid) || (ext === "ipa" && isAndroid)) {
        const err = new Error(
          ext === "apk"
            ? ".apk packages require an Android device"
            : ".ipa packages require an iOS device",
        );
        err.code = "PLATFORM_MISMATCH";
        throw err;
      }
      const item = _pushItem({
        id: `xf-${Date.now()}-${++seq}`,
        udid,
        filename: file.name,
        kind: "install",
        sizeBytes: file.size || 0,
        pct: 0,
        status: "uploading",
        dstPath: "",
        error: "",
        createdAt: Date.now(),
      });
      try {
        await appsApi.install(udid, file, (pct) => {
          item.pct = pct;
          if (pct >= 100) item.status = "installing";
        });
        item.pct = 100;
        item.status = "done";
        window.dispatchEvent(new CustomEvent("umh:apps-updated", { detail: { udid } }));
        return item;
      } catch (e) {
        item.status = "error";
        item.error = e?.message || String(e);
        throw e;
      }
    }

    const fallbackDir = isAndroid ? "/sdcard/Download" : "Downloads";
    const dir = (dstDir || fallbackDir).replace(/\/+$/, "");
    const dstPath = dir ? `${dir}/${file.name}` : file.name;
    const item = _pushItem({
      id: `xf-${Date.now()}-${++seq}`,
      udid,
      filename: file.name,
      kind: "file",
      sizeBytes: file.size || 0,
      pct: 0,
      status: "uploading",
      dstPath,
      error: "",
      createdAt: Date.now(),
    });
    try {
      await filesApi.push(udid, file, dstPath, (pct) => {
        item.pct = pct;
      });
      item.pct = 100;
      item.status = "done";
      window.dispatchEvent(new CustomEvent("umh:files-updated", { detail: { udid, dstPath } }));
      return item;
    } catch (e) {
      item.status = "error";
      item.error = e?.message || String(e);
      throw e;
    }
  }

  function clearCompleted(udid) {
    const target = unref(udid);
    transfers.value = transfers.value.filter(
      (x) => (target && x.udid !== target) || (x.status === "uploading" || x.status === "installing"),
    );
  }

  function removeTransfer(id) {
    transfers.value = transfers.value.filter((x) => x.id !== id);
  }

  return {
    transfers,
    transfersFor,
    activeFor,
    uploadFile,
    clearCompleted,
    removeTransfer,
  };
}
