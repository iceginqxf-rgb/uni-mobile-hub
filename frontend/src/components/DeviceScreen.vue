<template>
  <div
    class="screen-wrap"
    :data-platform="platform"
    @pointerdown.prevent="onDown"
    @pointermove.prevent="onMove"
    @pointerup.prevent="onUp"
    @pointercancel="onCancel"
    @wheel.prevent="onWheel"
    @dblclick.prevent="onDblClick"
  >
    <div class="screen-stage">
      <canvas
        v-if="hevc"
        ref="mediaRef"
        class="screen-img"
      />
      <video
        v-else-if="stream"
        ref="mediaRef"
        class="screen-img"
        autoplay
        playsinline
        muted
        draggable="false"
      />
      <img
        v-else-if="frame"
        ref="mediaRef"
        class="screen-img"
        :src="frame"
        draggable="false"
      />
      <div v-else class="screen-empty muted">
        <img class="screen-empty-glyph" src="/placeholder-mobile.svg" alt="" />
        <span>{{ t("stream.noFrame") }}</span>
      </div>
      <span
        v-if="ripple"
        class="touch-dot"
        :class="{ drag: ripple.drag }"
        :style="{ left: ripple.x + 'px', top: ripple.y + 'px' }"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from "vue";
import { useControl } from "../composables/useControl";
import { useUiI18n } from "../composables/useUiI18n";

const { t } = useUiI18n();

const props = defineProps({
  udid: { type: String, required: true },
  platform: { type: String, default: "ios" },
  frame: { type: String, default: "" },
  stream: { type: Object, default: null }, // MediaStream (WebRTC) or null
  hevc: { type: Boolean, default: false }, // WebCodecs canvas (native HEVC)
  rtcControl: { type: Function, default: null }, // send input over the RTC data channel
  onMedia: { type: Function, default: null }, // receives the canvas/video/img element
});

const { tap, swipe, longPress, doubleTap, pressButton } = useControl(props.udid);
const mediaRef = ref(null);
const ripple = ref(null);
let rippleTimer = null;

watch(mediaRef, (el) => props.onMedia?.(el), { immediate: true });

// Bind the WebRTC MediaStream to the <video> whenever it (re)appears.
watch(
  () => props.stream,
  async (s) => {
    await nextTick();
    const el = mediaRef.value;
    if (!el || !("srcObject" in el)) return;
    el.srcObject = s || null;
    if (s) el.play?.().catch(() => {});
  },
  { immediate: true },
);

const TAP_MAX_DIST = 10;
const TAP_MAX_MS = 400;
const LONG_PRESS_MS = 500;
let start = null;
let liveTouch = false;
let usedLiveTouchAt = 0;
let lastMoveAt = 0;

function showRipple(x, y, drag = false, autoFadeMs = 0) {
  if (rippleTimer) {
    clearTimeout(rippleTimer);
    rippleTimer = null;
  }
  ripple.value = { x: Math.round(x), y: Math.round(y), drag };
  if (autoFadeMs > 0) {
    rippleTimer = setTimeout(() => {
      ripple.value = null;
    }, autoFadeMs);
  }
}

function point(ev) {
  const el = mediaRef.value;
  const rect = el.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
  const y = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
  return {
    x,
    y,
    w: rect.width,
    h: rect.height,
    vw: el.videoWidth || el.naturalWidth || 0,
    vh: el.videoHeight || el.naturalHeight || 0,
  };
}

function onDown(ev) {
  if (!mediaRef.value) return;
  const p = point(ev);
  start = { ...p, t: performance.now() };
  mediaRef.value.setPointerCapture?.(ev.pointerId);
  showRipple(p.x, p.y, true);

  // Android Scrcpy node: stream real-time touch events (DOWN/MOVE/UP) over the
  // unreliable "input" DataChannel for zero-latency finger tracking.
  if (props.platform === "android" && props.rtcControl) {
    const sent = props.rtcControl({
      type: "touch",
      action: 0,
      x: p.x,
      y: p.y,
      display_width: p.w,
      display_height: p.h,
      video_width: p.vw,
      video_height: p.vh,
    });
    if (sent) {
      liveTouch = true;
      usedLiveTouchAt = performance.now();
      return;
    }
  }
  liveTouch = false;
}

function onMove(ev) {
  if (!start || !mediaRef.value) return;
  const p = point(ev);
  showRipple(p.x, p.y, true);
  if (!liveTouch || !props.rtcControl) return;
  const now = performance.now();
  if (now - lastMoveAt < 16) return;
  lastMoveAt = now;
  props.rtcControl({
    type: "touch",
    action: 2,
    x: p.x,
    y: p.y,
    display_width: p.w,
    display_height: p.h,
    video_width: p.vw,
    video_height: p.vh,
  });
}

function onUp(ev) {
  if (!start || !mediaRef.value) return;
  const p = point(ev);
  showRipple(p.x, p.y, false, 220);

  if (liveTouch && props.rtcControl) {
    props.rtcControl({
      type: "touch",
      action: 1,
      x: p.x,
      y: p.y,
      display_width: p.w,
      display_height: p.h,
      video_width: p.vw,
      video_height: p.vh,
    });
    liveTouch = false;
    usedLiveTouchAt = performance.now();
    start = null;
    return;
  }

  const dist = Math.hypot(p.x - start.x, p.y - start.y);
  const dt = performance.now() - start.t;

  // iPhone Home-bar bottom-edge swipe up: route quick/tall gestures directly
  // to WDA's /wda/homescreen because iOS blocks synthetic W3C touch gestures in
  // the system bottom-edge Home indicator zone.
  if (props.platform === "ios" && p.h > 0 && start.y >= p.h * 0.88) {
    const dy = start.y - p.y;
    const dx = Math.abs(p.x - start.x);
    if (dy >= p.h * 0.10 && dy > dx * 1.2) {
      if (dt < 480 || dy >= p.h * 0.30) {
        pressButton("home");
      } else {
        swipe(
          Math.round(start.x),
          Math.round(p.h - 1),
          Math.round(p.x),
          Math.round(p.h * 0.58),
          p.w,
          p.h,
          0.35,
          0.55,
        );
      }
      start = null;
      return;
    }
  }

  if (dist <= TAP_MAX_DIST && dt <= TAP_MAX_MS) {
    const msg = { type: "tap", x: Math.round(p.x), y: Math.round(p.y), display_width: p.w, display_height: p.h, video_width: p.vw, video_height: p.vh };
    if (!(props.rtcControl && props.rtcControl(msg))) tap(msg.x, msg.y, p.w, p.h);
  } else if (dist <= TAP_MAX_DIST && dt >= LONG_PRESS_MS) {
    const dur = Math.min(3.0, dt / 1000);
    const msg = { type: "longpress", x: Math.round(p.x), y: Math.round(p.y), display_width: p.w, display_height: p.h, video_width: p.vw, video_height: p.vh, duration: dur };
    if (!(props.rtcControl && props.rtcControl(msg))) longPress(msg.x, msg.y, p.w, p.h, dur);
  } else {
    const dur = Math.min(1.0, Math.max(0.1, dt / 1000));
    const msg = {
      type: "swipe",
      x1: Math.round(start.x),
      y1: Math.round(start.y),
      x2: Math.round(p.x),
      y2: Math.round(p.y),
      display_width: p.w,
      display_height: p.h,
      video_width: p.vw,
      video_height: p.vh,
      duration: dur,
    };
    if (!(props.rtcControl && props.rtcControl(msg)))
      swipe(msg.x1, msg.y1, msg.x2, msg.y2, p.w, p.h, dur);
  }
  start = null;
}

function onCancel(ev) {
  if (liveTouch && props.rtcControl && start && mediaRef.value) {
    const p = point(ev);
    props.rtcControl({
      type: "touch",
      action: 1,
      x: p.x,
      y: p.y,
      display_width: p.w,
      display_height: p.h,
      video_width: p.vw,
      video_height: p.vh,
    });
  }
  liveTouch = false;
  start = null;
  ripple.value = null;
}

function onWheel(ev) {
  if (!mediaRef.value || props.platform !== "android" || !props.rtcControl) return;
  const p = point(ev);
  props.rtcControl({
    type: "scroll",
    x: p.x,
    y: p.y,
    display_width: p.w,
    display_height: p.h,
    video_width: p.vw,
    video_height: p.vh,
    h: ev.deltaX ? Math.sign(-ev.deltaX) * 2 : 0,
    v: ev.deltaY ? Math.sign(-ev.deltaY) * 3 : 0,
  });
}

function onDblClick(ev) {
  if (!mediaRef.value) return;
  // Live touch tracking already sent both real tap DOWN/UP pairs natively.
  if (props.platform === "android" && performance.now() - usedLiveTouchAt < 650) return;
  const p = point(ev);
  const msg = { type: "doubletap", x: Math.round(p.x), y: Math.round(p.y), display_width: p.w, display_height: p.h, video_width: p.vw, video_height: p.vh };
  if (!(props.rtcControl && props.rtcControl(msg))) doubleTap(msg.x, msg.y, p.w, p.h);
}
</script>

<style scoped>
.screen-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  background: radial-gradient(120% 80% at 50% 0%, #0e1626, #05080f);
  border: 1px solid var(--border);
  border-radius: 18px;
  overflow: hidden;
  min-height: 260px;
  padding: 10px;
  box-shadow: var(--shadow), inset 0 0 0 1px rgba(255, 255, 255, 0.03);
}
.screen-stage {
  position: relative;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  max-width: 100%;
}
.screen-img {
  max-width: 100%;
  max-height: min(78vh, calc(100vh - 348px));
  display: block;
  border-radius: 8px;
  touch-action: none;
  user-select: none;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5);
}
.touch-dot {
  position: absolute;
  width: 24px;
  height: 24px;
  margin-left: -12px;
  margin-top: -12px;
  border-radius: 50%;
  border: 2px solid rgba(96, 165, 250, 0.9);
  background: rgba(59, 130, 246, 0.28);
  pointer-events: none;
  transition: opacity 0.18s ease, transform 0.12s ease;
  transform: scale(0.95);
}
.touch-dot.drag {
  transform: scale(1.1);
  border-color: rgba(255, 255, 255, 0.92);
}
.screen-empty {
  padding: 60px 20px;
  text-align: center;
  font-size: 0.86rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
.screen-empty-glyph {
  width: 64px;
  height: auto;
  opacity: 0.7;
}
</style>
