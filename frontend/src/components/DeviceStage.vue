<template>
  <article
    v-if="!compact"
    ref="cardEl"
    class="device-card"
    :class="{ live, 'fill-pane': fillPane, 'is-fullscreen': isFullscreen, 'is-dragover': dragActive }"
    :style="fillPane || isFullscreen ? {} : { '--card-aspect': aspect }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <header class="device-card-head">
      <span class="device-card-title">{{ deviceName }}</span>
      <div class="row" style="gap: 6px">
        <span class="device-card-chip" :class="live ? 'on' : 'off'">
          <span class="dot" />{{ chipText }}
        </span>
        <button
          v-if="clipSync.autoSync.value"
          type="button"
          class="card-clip-btn mono active"
          :title="t('clipSync.autoOnTitle')"
          :aria-label="t('clipSync.autoOnTitle')"
          @click="clipSync.toggleAutoSync()"
        >
          CLIP
        </button>
        <button
          type="button"
          class="card-rec-btn mono"
          :class="{ active: rec.recording.value }"
          :title="rec.recording.value ? t('recorder.stop') : t('recorder.start')"
          :aria-label="rec.recording.value ? t('recorder.stop') : t('recorder.start')"
          @click="toggleRecording"
        >
          <span class="rec-dot" />
          <span v-if="rec.recording.value">{{ formatElapsed(rec.elapsedSec.value) }}</span>
          <span v-else>REC</span>
        </button>
        <button
          type="button"
          class="card-fs-btn"
          :title="isFullscreen ? t('fullscreen.exit') : t('fullscreen.enter')"
          :aria-label="isFullscreen ? t('fullscreen.exit') : t('fullscreen.enter')"
          @click="toggleFullscreen"
        >
          <svg v-if="!isFullscreen" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" />
            <line x1="14" y1="10" x2="21" y2="3" /><line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
      </div>
    </header>

    <DeviceScreen
      :udid="udid"
      :platform="device?.platform || 'ios'"
      :frame="mode === 'jpeg' ? stream.frame.value : ''"
      :stream="activeMediaStream"
      :hevc="mode === 'hevc'"
      :rtc-control="activeRtcControl"
      :on-media="onMedia"
      :fit-parent="fillPane || isFullscreen"
    />

    <!-- Live drag-and-drop transfer progress strip -->
    <div v-if="activeTransfers.length" class="stage-xfer-strip" aria-live="polite">
      <div v-for="xf in activeTransfers" :key="xf.id" class="stage-xfer-item">
        <div class="stage-xfer-meta mono">
          <span class="stage-xfer-badge">{{ xf.kind === 'install' ? 'APP' : 'FILE' }}</span>
          <span class="stage-xfer-name" :title="xf.filename">{{ xf.filename }}</span>
          <span class="stage-xfer-pct">
            {{ xf.status === 'installing' ? t('drop.installing') : `${xf.pct}%` }}
          </span>
        </div>
        <div class="stage-xfer-bar">
          <div class="stage-xfer-fill" :class="{ indeterminate: xf.status === 'installing' }" :style="{ width: `${xf.pct}%` }" />
        </div>
      </div>
    </div>

    <div v-if="dragActive" class="stage-drop-overlay" aria-hidden="true">
      <div class="stage-drop-box mono">
        <strong>{{ t('drop.title') }}</strong>
        <span>{{ t(isAndroid ? 'drop.androidHint' : 'drop.iosHint') }}</span>
      </div>
    </div>

    <footer class="device-card-actions">
      <button v-if="isAndroid" class="card-action" :title="t('control.back')" @click="ctrl.pressButton('back')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
      </button>
      <button class="card-action" :title="t('control.home')" @click="ctrl.pressButton('home')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12l9-9 9 9" /><path d="M5 10v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V10" /></svg>
      </button>
      <button class="card-action" :title="t('control.recent')" @click="onRecent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
      </button>
      <button v-if="!isAndroid" class="card-action" :title="t('control.lock')" @click="ctrl.pressButton('lock')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
      </button>
      <!-- D-pad — summoned as a floating pad above the footer -->
      <button class="card-action" :class="{ active: dpadOpen }" :title="t('quick.dpad')" @click="dpadOpen = !dpadOpen">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="m9 6 3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3" /></svg>
      </button>
      <button v-if="isAndroid" class="card-action" :title="t('control.rotate')" @click="ctrl.pressButton('rotate')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
      </button>
      <button v-if="isAndroid" class="card-action" :title="t('control.power')" @click="ctrl.pressButton('power')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
      </button>
      <span class="card-action-spacer" />
      <button class="card-action" :title="t('control.volUp')" @click="ctrl.pressButton('volumeup')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z" /><path d="M16 9a4 4 0 0 1 0 6" /><path d="M19.5 6.5a8 8 0 0 1 0 11" /></svg>
      </button>
      <button class="card-action" :title="t('control.volDown')" @click="ctrl.pressButton('volumedown')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z" /><path d="M16 9a4 4 0 0 1 0 6" /></svg>
      </button>
      <!-- "更多" — reveals the right-side control drawer (control/automation/apps/files/logs) -->
      <button class="card-action" :class="{ active: moreOpen }" :title="t('control.more')" @click="emit('toggle-more')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="8" x2="20" y2="8" /><line x1="4" y1="16" x2="20" y2="16" /><circle cx="9" cy="8" r="2" fill="currentColor" stroke="none" /><circle cx="15" cy="16" r="2" fill="currentColor" stroke="none" /></svg>
      </button>
    </footer>

    <p v-if="activeError" class="banner err" style="margin: 0; border-radius: 0">
      {{ activeError }}
    </p>

    <!-- MJPEG / Scrcpy Socket.IO provider/fps knobs — only when WebRTC is off -->
    <StreamPanel
      v-if="mode === 'jpeg'"
      :running="stream.running.value"
      :connected="connected"
      :active-provider="stream.provider.value"
      :live-fps="stream.fps.value"
      :error="stream.error.value"
      @start="(o) => stream.start(o.provider, o.fps)"
      @stop="stream.stop()"
    />
  </article>

  <!-- compact (grid tile): bare screen only -->
  <DeviceScreen
    v-else
    :udid="udid"
    :platform="device?.platform || 'ios'"
    :frame="mode === 'jpeg' ? stream.frame.value : ''"
    :stream="activeMediaStream"
    :hevc="false"
    :rtc-control="activeRtcControl"
  />

  <!-- Floating D-pad — summoned from the footer navpad button. Teleported to
       <body> and anchored to the card's outer-right edge (Android-style relative
       positioning) so it never covers the screen. Center is a visual hub only. -->
  <Teleport to="body">
    <transition name="dpad-pop">
      <div v-if="dpadOpen" ref="dpadEl" class="dpad-pop" :style="dpadStyle" role="group" :aria-label="t('quick.dpad')">
        <button class="dpad-close" :title="t('detail.close')" :aria-label="t('detail.close')" @click="dpadOpen = false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </button>
        <button class="dpad-key up" :title="t('quick.up')" @click="dir('up')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 11 12 5 18 11" /><line x1="12" y1="19" x2="12" y2="5" /></svg>
        </button>
        <button class="dpad-key left" :title="t('quick.left')" @click="dir('left')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="11 6 5 12 11 18" /><line x1="19" y1="12" x2="5" y2="12" /></svg>
        </button>
        <span class="dpad-hub" aria-hidden="true" />
        <button class="dpad-key right" :title="t('quick.right')" @click="dir('right')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 6 19 12 13 18" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
        </button>
        <button class="dpad-key down" :title="t('quick.down')" @click="dir('down')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 13 12 19 18 13" /><line x1="12" y1="5" x2="12" y2="19" /></svg>
        </button>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, toRef, watch } from "vue";
import DeviceScreen from "./DeviceScreen.vue";
import StreamPanel from "./StreamPanel.vue";
import { useStream } from "../composables/useStream";
import { useWebRTC } from "../composables/useWebRTC";
import { useScrcpyStream } from "../composables/useScrcpyStream";
import { useHevcStream, browserSupportsHevc, iosSupportsHevc } from "../composables/useHevcStream";
import { useDevices } from "../composables/useDevices";
import { useControl } from "../composables/useControl";
import { useScreenRecorder } from "../composables/useScreenRecorder";
import { useTransfers } from "../composables/useTransfers";
import { useClipboardSync } from "../composables/useClipboardSync";
import { useToast } from "../composables/useToast";
import { openTaskSwitcher } from "../composables/useTaskSwitcher";
import { useUiI18n } from "../composables/useUiI18n";

const { t } = useUiI18n();
const { push: pushToast } = useToast();

const props = defineProps({
  udid: { type: String, required: true },
  connected: { type: Boolean, default: false },
  compact: { type: Boolean, default: false }, // grid tile: screen only, no chrome
  moreOpen: { type: Boolean, default: false }, // highlight footer "更多" when drawer is open
  fillPane: { type: Boolean, default: false }, // stretch inside split pane
});
const emit = defineEmits(["toggle-more"]);

const isFullscreen = ref(false);
async function toggleFullscreen() {
  const el = cardEl.value;
  if (!isFullscreen.value) {
    isFullscreen.value = true;
    try {
      if (el && el.requestFullscreen && document.fullscreenElement !== el) {
        await el.requestFullscreen();
      }
    } catch {
      /* fixed overlay fallback remains active */
    }
  } else {
    isFullscreen.value = false;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
    } catch {
      /* ignore */
    }
  }
}
function onNativeFullscreenChange() {
  if (!document.fullscreenElement && isFullscreen.value) {
    // Only exit if user pressed browser Esc out of native fullscreen
    isFullscreen.value = false;
  }
}
function onFullscreenKey(ev) {
  if (ev.key === "Escape" && isFullscreen.value) {
    toggleFullscreen();
  }
}
function onFullscreenCmd(ev) {
  if (ev.detail?.udid === props.udid) toggleFullscreen();
}
function onRecordCmd(ev) {
  if (ev.detail?.udid === props.udid) toggleRecording();
}
onMounted(() => {
  document.addEventListener("fullscreenchange", onNativeFullscreenChange);
  window.addEventListener("keydown", onFullscreenKey);
  window.addEventListener("umh:fullscreen", onFullscreenCmd);
  window.addEventListener("umh:record", onRecordCmd);
});
defineExpose({ toggleFullscreen });

const { devices, webrtcEnabled, hevcAvailable } = useDevices();

const stream = useStream(props.udid);
const rtc = useWebRTC(props.udid);
const scrcpyRtc = useScrcpyStream(props.udid);
const hevc = useHevcStream(props.udid);
const ctrl = useControl(props.udid);
const rec = useScreenRecorder();
const clipSync = useClipboardSync();
const { activeFor, uploadFile } = useTransfers();
const activeTransfers = activeFor(toRef(props, "udid"));
const dragDepth = ref(0);
const dragActive = computed(() => dragDepth.value > 0);
const mediaEl = ref(null);
// "" until health + connect decide. Grid never uses HEVC.
const mode = ref("");

const activeMediaStream = computed(() => {
  if (mode.value === "webrtc") return rtc.stream.value;
  if (mode.value === "scrcpy-rtc") return scrcpyRtc.stream.value;
  return null;
});
const activeRtcControl = computed(() => {
  if (mode.value === "webrtc") return rtc.sendControl;
  if (mode.value === "scrcpy-rtc") return scrcpyRtc.sendControl;
  return null;
});
const activeError = computed(() => hevc.error.value || rtc.error.value || scrcpyRtc.error.value || stream.error.value || rec.error.value);

function onMedia(el) {
  mediaEl.value = el;
  hevc.bind(el);
}

function formatElapsed(sec) {
  const s = Math.max(0, Number(sec || 0));
  const m = String(Math.floor(s / 60)).padStart(2, "0");
  const r = String(s % 60).padStart(2, "0");
  return `${m}:${r}`;
}

function toggleRecording() {
  if (rec.recording.value) {
    rec.stop();
    return;
  }
  const ok = rec.start({
    mediaStream: activeMediaStream.value,
    mediaEl: mediaEl.value,
    deviceName: deviceName.value,
    onSaved: (clip) => {
      const kb = Math.max(1, Math.round((clip.sizeBytes || 0) / 1024));
      pushToast(t("recorder.saved", { file: clip.filename, kb }), "ok");
    },
  });
  if (ok) {
    pushToast(t("recorder.started"), "ok");
  } else if (rec.error.value) {
    pushToast(rec.error.value, "err");
  }
}

function useJpeg(prov = "mjpeg") {
  mode.value = "jpeg";
  if (!stream.running.value) stream.start(prov);
}

function useWebRtc() {
  mode.value = "webrtc";
  rtc.start();
}

function leaveHevc(serverProvider) {
  // Server already moved to MJPEG/screenshot: keep that socket stream unless
  // WebRTC is on, in which case WebRTC owns the JPEG provider itself.
  if (webrtcEnabled.value) {
    stream.stop();
    useWebRtc();
    return;
  }
  if (serverProvider === "mjpeg" || serverProvider === "screenshot") {
    mode.value = "jpeg";
    return;
  }
  useJpeg();
}
hevc.setFallback(leaveHevc);

const device = computed(() => devices.value.find((d) => d.udid === props.udid));
const isAndroid = computed(() => device.value?.platform === "android");
function onRecent() {
  if (isAndroid.value) ctrl.pressButton("recent");
  else openTaskSwitcher(props.udid);
}

function _hasFiles(ev) {
  const types = ev.dataTransfer?.types;
  return Boolean(types && Array.from(types).includes("Files"));
}
function onDragEnter(ev) {
  if (!_hasFiles(ev)) return;
  dragDepth.value += 1;
}
function onDragOver(ev) {
  if (!_hasFiles(ev)) return;
  if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
}
function onDragLeave(ev) {
  if (!_hasFiles(ev) && dragDepth.value === 0) return;
  dragDepth.value = Math.max(0, dragDepth.value - 1);
}
async function onDrop(ev) {
  dragDepth.value = 0;
  const files = Array.from(ev.dataTransfer?.files || []);
  if (!files.length) return;
  if (!props.connected) {
    pushToast(t("drop.notConnected"), "err");
    return;
  }
  for (const file of files) {
    try {
      const item = await uploadFile(props.udid, file, { isAndroid: isAndroid.value });
      if (item?.kind === "install") {
        pushToast(t("drop.installDone", { name: file.name }), "ok");
      } else if (item) {
        pushToast(t("drop.uploadDone", { name: file.name, dst: item.dstPath }), "ok");
      }
    } catch (e) {
      if (e?.code === "PLATFORM_MISMATCH") {
        pushToast(
          t("drop.platformMismatch", { name: file.name, os: isAndroid.value ? "Android" : "iOS" }),
          "err",
        );
      } else {
        pushToast(e?.message || t("errors.generic"), "err");
      }
    }
  }
}
const streamEndpoint = computed(() => device.value?.stream_endpoint || null);
// Prefer the marketing name ("iPhone 15 Pro Max") over the lockdown DeviceName
// (typically just "iPhone" if the user never renamed the device). Backend stamps
// `marketing` onto every device in /api/devices via IOSDevice.to_dict().
const deviceName = computed(() => device.value?.marketing || device.value?.name || props.udid.slice(0, 14));
// Card hugs the device aspect ratio (w/h); fall back to a modern-phone portrait.
const aspect = computed(() => {
  const w = device.value?.screen_width, h = device.value?.screen_height;
  return w && h ? +(w / h).toFixed(4) : 0.49;
});
// Floating D-pad (footer-summoned). iOS has no hardware arrows, so directions
// are WDA swipes from screen-center on a normalized 1000×1000 box (the backend
// maps proportionally to device pixels). There is no center action — the hub is
// a visual anchor only (mirrors Android's `dpad-hub`).
const dpadOpen = ref(false);
const dpadEl = ref(null);
const cardEl = ref(null);
const dpadStyle = ref({});
const B = 1000, C = 500, NEAR = 320, FAR = 680;
function dir(d) {
  const m = {
    up: [C, FAR, C, NEAR],
    down: [C, NEAR, C, FAR],
    left: [FAR, C, NEAR, C],
    right: [NEAR, C, FAR, C],
  }[d];
  if (m) ctrl.swipe(m[0], m[1], m[2], m[3], B, B, 0.18);
}

// Anchor the D-pad to the card's OUTER-right edge (fall back to outer-left, then
// to floating over the lower-right corner on viewports too narrow for either),
// vertically aligned to the lower third of the card so it sits within thumb
// reach. Re-runs on resize/scroll + a ResizeObserver on the stage so it tracks
// the card when the control drawer pushes the layout. Mirrors Android's JS
// relative-positioning (CSS Anchor Positioning isn't in Safari/FF yet).
const GAP = 12, PAD_W = 132, MARGIN = 8;
function positionDpad() {
  const card = cardEl.value;
  if (!dpadOpen.value || !card) return;
  const r = card.getBoundingClientRect();
  const pad = dpadEl.value?.getBoundingClientRect();
  const w = pad?.width || PAD_W;
  const h = pad?.height || PAD_W;
  const vw = window.innerWidth, vh = window.innerHeight;

  let left;
  if (r.right + GAP + w <= vw - MARGIN) left = r.right + GAP;        // right of card
  else if (r.left - GAP - w >= MARGIN) left = r.left - GAP - w;       // left of card
  else left = Math.min(r.right - w - GAP, vw - w - MARGIN);           // overlay lower-right

  // Sit in the card's lower third (thumb reach), clamped to the viewport.
  let top = r.top + r.height * 0.62 - h / 2;
  top = Math.max(MARGIN, Math.min(top, vh - h - MARGIN));
  left = Math.max(MARGIN, Math.min(left, vw - w - MARGIN));
  dpadStyle.value = { top: `${Math.round(top)}px`, left: `${Math.round(left)}px` };
}

let _raf = 0;
function scheduleReposition() {
  if (_raf) return;
  _raf = requestAnimationFrame(() => { _raf = 0; positionDpad(); });
}
let _ro = null;
function bindRepositionListeners() {
  window.addEventListener("resize", scheduleReposition);
  window.addEventListener("scroll", scheduleReposition, true);
  if (cardEl.value && "ResizeObserver" in window) {
    _ro = new ResizeObserver(scheduleReposition);
    // Observe the stage cell (parent) so a drawer-induced layout shift retracks.
    _ro.observe(cardEl.value);
    if (cardEl.value.parentElement) _ro.observe(cardEl.value.parentElement);
  }
}
function unbindRepositionListeners() {
  window.removeEventListener("resize", scheduleReposition);
  window.removeEventListener("scroll", scheduleReposition, true);
  _ro?.disconnect();
  _ro = null;
}
watch(dpadOpen, async (open) => {
  if (open) {
    await nextTick();
    positionDpad();
    positionDpad(); // 2nd pass now that the element has a measured size
    bindRepositionListeners();
  } else {
    unbindRepositionListeners();
  }
});

const live = computed(() => {
  if (mode.value === "hevc") return hevc.running.value;
  if (mode.value === "webrtc") return rtc.running.value;
  if (mode.value === "scrcpy-rtc") return scrcpyRtc.running.value;
  return stream.running.value;
});
const chipText = computed(() => {
  if (mode.value === "hevc") {
    return hevc.running.value ? t("stream.live") + " · HEVC" : t("stream.connecting");
  }
  if (mode.value === "webrtc") {
    const label = isAndroid.value ? "Scrcpy" : "WebRTC";
    return rtc.running.value ? `${t("stream.live")} · ${label}` : t("stream.connecting");
  }
  if (mode.value === "scrcpy-rtc") {
    return scrcpyRtc.running.value ? t("stream.live") + " · Scrcpy Node" : t("stream.connecting");
  }
  return stream.running.value ? t("stream.live") : t("stream.connecting");
});

async function pickTransport() {
  if (!props.connected || mode.value) return;
  if (isAndroid.value) {
    const ep = streamEndpoint.value;
    if (ep?.mode === "remote_scrcpy") {
      mode.value = "scrcpy-rtc";
      scrcpyRtc.start(
        ep,
        () => {
          if (!props.connected) return;
          if (webrtcEnabled.value) useWebRtc();
          else useJpeg("scrcpy");
        },
        { w: device.value?.screen_width || 1080, h: device.value?.screen_height || 2400 },
      );
      return;
    }
    if (webrtcEnabled.value) useWebRtc();
    else useJpeg("scrcpy");
    return;
  }
  // Single-device iOS stage: HEVC -> WebRTC -> MJPEG.
  const version = device.value?.ios_version || "";
  if (!props.compact && hevcAvailable.value === true && iosSupportsHevc(version)) {
    const ok = await browserSupportsHevc();
    if (!props.connected || mode.value) return;
    if (ok) {
      mode.value = "hevc";
      hevc.start();
      return;
    }
  }
  if (!props.compact && hevcAvailable.value === null) return;
  if (webrtcEnabled.value) useWebRtc();
  else useJpeg("mjpeg");
}

watch(
  () => props.connected,
  (isConnected) => {
    if (!isConnected) {
      rec.stop();
      scrcpyRtc.stop();
      rtc.stop();
      hevc.stop();
      stream.stop();
      mode.value = "";
      return;
    }
    pickTransport();
  },
  { immediate: true },
);
watch([hevcAvailable, webrtcEnabled], () => {
  if (props.connected) pickTransport();
});

onUnmounted(() => {
  rec.dispose();
  hevc.stop();
  hevc.dispose();
  scrcpyRtc.stop();
  scrcpyRtc.dispose();
  stream.stop();
  stream.dispose();
  rtc.stop();
  rtc.dispose();
  unbindRepositionListeners();
  document.removeEventListener("fullscreenchange", onNativeFullscreenChange);
  window.removeEventListener("keydown", onFullscreenKey);
  window.removeEventListener("umh:fullscreen", onFullscreenCmd);
  window.removeEventListener("umh:record", onRecordCmd);
  if (document.fullscreenElement === cardEl.value) {
    document.exitFullscreen?.().catch(() => {});
  }
});
</script>

<style scoped>
.device-card { position: relative; }
.card-clip-btn {
  min-height: 22px; height: 22px; padding: 0 6px;
  font-size: 0.64rem; font-weight: 700;
  border-radius: 0; border: 1px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 16%, transparent);
  color: var(--primary-2);
}
.card-clip-btn:hover { background: color-mix(in srgb, var(--primary) 26%, transparent); }
.card-rec-btn {
  min-height: 22px; height: 22px; padding: 0 7px; gap: 5px;
  font-size: 0.66rem; font-weight: 700;
  border-radius: 0; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.card-rec-btn:hover { color: var(--text-strong); border-color: var(--primary); }
.card-rec-btn .rec-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--danger); }
.card-rec-btn.active {
  color: #fca5a5;
  border-color: rgba(239, 68, 68, 0.55);
  background: rgba(239, 68, 68, 0.14);
}
.card-rec-btn.active .rec-dot { animation: rec-pulse 1s ease-in-out infinite; }
@keyframes rec-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
.card-fs-btn {
  min-height: 22px; height: 22px; width: 24px; padding: 0;
  border-radius: 0; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--muted);
}
.card-fs-btn:hover { color: var(--text-strong); border-color: var(--primary); }
.card-fs-btn svg { width: 12px; height: 12px; }

.device-card.fill-pane {
  max-width: none;
  width: 100%;
  height: 100%;
  flex: 1 1 auto;
  min-height: 0;
}
.device-card.fill-pane :deep(.screen-wrap) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.device-card.is-fullscreen,
.device-card:fullscreen {
  position: fixed;
  inset: 0;
  z-index: 80;
  width: 100vw;
  height: 100vh;
  max-width: none;
  margin: 0;
  background: var(--bg);
}
.device-card.is-fullscreen :deep(.screen-wrap),
.device-card:fullscreen :deep(.screen-wrap) {
  flex: 1 1 auto;
  min-height: 0;
  background: #000;
}

/* Floating D-pad — fixed-positioned (coords set in JS), anchored beside the card
   so it never covers the screen. No center action: the hub is a visual anchor. */
.dpad-pop {
  position: fixed; z-index: 95;
  display: grid; grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(3, 1fr);
  gap: 6px; width: 132px; aspect-ratio: 1; padding: 8px;
  background: var(--panel-solid); border: 1px solid var(--border-strong);
  border-radius: 0; box-shadow: var(--shadow);
}
.dpad-key { min-height: 0; height: 100%; padding: 0; display: flex; align-items: center; justify-content: center; }
.dpad-key svg { width: 18px; height: 18px; }
.dpad-close {
  grid-area: 1 / 3; align-self: start; justify-self: end;
  min-height: 0; width: 22px; height: 22px; padding: 0; border-radius: 0;
  display: flex; align-items: center; justify-content: center; color: var(--muted);
}
.dpad-close svg { width: 13px; height: 13px; }
.dpad-close:hover { color: var(--text-strong); }
.dpad-key.up { grid-area: 1 / 2; }
.dpad-key.left { grid-area: 2 / 1; }
.dpad-key.right { grid-area: 2 / 3; }
.dpad-key.down { grid-area: 3 / 2; }
.dpad-hub { grid-area: 2 / 2; align-self: center; justify-self: center; width: 12px; height: 12px; border-radius: 0; background: var(--border-strong); }
.dpad-pop-enter-active, .dpad-pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.dpad-pop-enter-from, .dpad-pop-leave-to { opacity: 0; transform: scale(0.92); }

.stage-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 25;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(9, 9, 11, 0.78);
  border: 2px dashed var(--primary);
  pointer-events: none;
}
.stage-drop-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px 16px;
  background: var(--panel-solid);
  border: 1px solid var(--primary);
  border-radius: 0;
  text-align: center;
  font-size: 0.78rem;
  color: var(--text-strong);
}
.stage-drop-box span {
  font-size: 0.72rem;
  color: var(--muted);
}

.stage-xfer-strip {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 10px;
  background: var(--surface-2);
  border-top: 1px solid var(--border);
}
.stage-xfer-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.stage-xfer-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
}
.stage-xfer-badge {
  padding: 0 4px;
  border: 1px solid var(--primary);
  color: var(--primary-2);
  font-size: 0.62rem;
  flex: none;
}
.stage-xfer-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-strong);
}
.stage-xfer-pct {
  color: var(--primary-2);
  flex: none;
}
.stage-xfer-bar {
  height: 3px;
  background: var(--inset);
  border: 1px solid var(--border);
  border-radius: 0;
  overflow: hidden;
}
.stage-xfer-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.12s linear;
}
.stage-xfer-fill.indeterminate {
  animation: xfer-pulse 1.1s ease-in-out infinite;
}
@keyframes xfer-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>
