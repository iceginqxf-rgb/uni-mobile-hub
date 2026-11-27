import { ref } from "vue";
import { useSocket } from "./useSocket";
import { devicesApi } from "../api/devices";

// Same-origin Hub WebRTC signaling relay for remote Scrcpy worker nodes.
// WebAppFlaskscrcpy creates its own server-side "input" DataChannel
// (ordered=false, maxRetransmits=0) during handle_offer, so the browser MUST
// accept it via `ondatachannel` rather than sending on a client-created one.
export function useScrcpyStream(udid) {
  const { on, emit } = useSocket();
  const stream = ref(null);
  const running = ref(false);
  const error = ref("");

  let pc = null;
  let bootstrapChannel = null;
  let inputChannel = null;
  let devSize = { w: 1080, h: 2400 };
  let negId = 0;
  let timeoutHandle = null;
  let fallbackCb = null;
  const disposers = [];

  function _clearTimeout() {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
      timeoutHandle = null;
    }
  }

  function _cleanup() {
    negId += 1;
    _clearTimeout();
    if (pc) {
      try { pc.close(); } catch { /* ignore */ }
      pc = null;
    }
    bootstrapChannel = null;
    inputChannel = null;
    fallbackCb = null;
    stream.value = null;
    running.value = false;
  }

  function _mapPoint(x, y, dw, dh, vw, vh) {
    const tw = vw || devSize.w;
    const th = vh || devSize.h;
    if (!dw || !dh) return { x: Math.round(x), y: Math.round(y) };
    return {
      x: Math.max(0, Math.min(tw - 1, Math.round((x / dw) * tw))),
      y: Math.max(0, Math.min(th - 1, Math.round((y / dh) * th))),
    };
  }

  function sendControl(msg) {
    if (!inputChannel || inputChannel.readyState !== "open") return false;
    const t = msg?.type;
    if (t === "touch") {
      const pt = _mapPoint(msg.x, msg.y, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      inputChannel.send(JSON.stringify({ t: "touch", x: pt.x, y: pt.y, action: msg.action }));
      return true;
    }
    if (t === "scroll") {
      const pt = _mapPoint(msg.x, msg.y, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      inputChannel.send(JSON.stringify({ t: "scroll", x: pt.x, y: pt.y, h: msg.h || 0, v: msg.v || 0 }));
      return true;
    }
    if (t === "tap" || t === "doubletap") {
      const pt = _mapPoint(msg.x, msg.y, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      const fire = () => {
        inputChannel.send(JSON.stringify({ t: "touch", x: pt.x, y: pt.y, action: 0 }));
        setTimeout(() => {
          if (inputChannel?.readyState === "open") {
            inputChannel.send(JSON.stringify({ t: "touch", x: pt.x, y: pt.y, action: 1 }));
          }
        }, 25);
      };
      fire();
      if (t === "doubletap") setTimeout(fire, 90);
      return true;
    }
    if (t === "longpress") {
      const pt = _mapPoint(msg.x, msg.y, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      const ms = Math.max(400, Math.round((msg.duration || 0.8) * 1000));
      inputChannel.send(JSON.stringify({ t: "touch", x: pt.x, y: pt.y, action: 0 }));
      setTimeout(() => {
        if (inputChannel?.readyState === "open") {
          inputChannel.send(JSON.stringify({ t: "touch", x: pt.x, y: pt.y, action: 1 }));
        }
      }, ms);
      return true;
    }
    if (t === "swipe") {
      const p1 = _mapPoint(msg.x1, msg.y1, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      const p2 = _mapPoint(msg.x2, msg.y2, msg.display_width, msg.display_height, msg.video_width, msg.video_height);
      inputChannel.send(JSON.stringify({
        t: "swipe",
        startX: p1.x,
        startY: p1.y,
        endX: p2.x,
        endY: p2.y,
        duration: Math.max(50, Math.round((msg.duration || 0.3) * 1000)),
      }));
      return true;
    }
    return false;
  }

  function _triggerFallback(reason, expectedId) {
    if (expectedId !== undefined && expectedId !== negId) return;
    const cb = fallbackCb;
    _cleanup();
    cb?.(reason);
  }

  async function start(_endpoint, onFallback, deviceGeometry) {
    error.value = "";
    _cleanup();
    if (deviceGeometry?.w && deviceGeometry?.h) {
      devSize = { w: deviceGeometry.w, h: deviceGeometry.h };
    }
    fallbackCb = onFallback || null;

    const myId = negId;
    let rtcOpts = { iceServers: [] };
    try {
      const cfg = await devicesApi.rtcConfig(udid);
      if (myId !== negId) return;
      if (cfg && Array.isArray(cfg.iceServers)) {
        rtcOpts = {
          iceServers: cfg.iceServers,
          ...(cfg.iceTransportPolicy ? { iceTransportPolicy: cfg.iceTransportPolicy } : {}),
        };
      }
    } catch { /* fall back to host ICE */ }

    const myPc = new RTCPeerConnection(rtcOpts);
    pc = myPc;
    // Include an SCTP m=application section in our offer; the server pushes its
    // own "input" DataChannel over `ondatachannel`. Keep "bootstrap" off `inputChannel`.
    bootstrapChannel = myPc.createDataChannel("bootstrap");
    myPc.ondatachannel = (ev) => {
      if (pc !== myPc) return;
      if (ev.channel?.label === "input") {
        inputChannel = ev.channel;
      }
    };
    myPc.addTransceiver("video", { direction: "recvonly" });

    timeoutHandle = setTimeout(() => {
      if (!running.value) {
        _triggerFallback("scrcpy webrtc timeout", myId);
      }
    }, 10000);

    myPc.ontrack = (ev) => {
      if (pc !== myPc) return;
      _clearTimeout();
      stream.value = ev.streams[0] || new MediaStream([ev.track]);
      running.value = true;
    };
    myPc.onicecandidate = (ev) => {
      if (pc !== myPc || !ev.candidate) return;
      emit("scrcpy:webrtc:ice", {
        udid,
        candidate: ev.candidate.candidate,
        sdpMid: ev.candidate.sdpMid,
        sdpMLineIndex: ev.candidate.sdpMLineIndex,
      });
    };
    myPc.onconnectionstatechange = () => {
      if (pc === myPc && ["failed", "closed"].includes(myPc.connectionState)) {
        _triggerFallback(`scrcpy webrtc ${myPc.connectionState}`, myId);
      }
    };

    try {
      const offer = await myPc.createOffer();
      await myPc.setLocalDescription(offer);
      if (myId !== negId || pc !== myPc) return;
      emit("scrcpy:webrtc:offer", { udid, sdp: myPc.localDescription.sdp });
    } catch (e) {
      _triggerFallback(e?.message || "createOffer failed", myId);
    }
  }

  function bind() {
    disposers.push(
      on("scrcpy:webrtc:answer", async (d) => {
        if (!pc || d?.udid !== udid) return;
        if (pc.signalingState !== "have-local-offer") return;
        const myId = negId;
        try {
          await pc.setRemoteDescription({ sdp: d.sdp, type: d.type || "answer" });
        } catch (e) {
          _triggerFallback(e?.message || "setRemoteDescription failed", myId);
        }
      }),
      on("scrcpy:webrtc:ice", async (d) => {
        if (!pc || !d?.candidate || d?.udid !== udid) return;
        try {
          await pc.addIceCandidate({
            candidate: d.candidate,
            sdpMid: d.sdpMid,
            sdpMLineIndex: d.sdpMLineIndex,
          });
        } catch { /* ignore late ICE */ }
      }),
      on("scrcpy:webrtc:closed", (d) => {
        if (d?.udid && d.udid !== udid) return;
        _triggerFallback(d?.reason || "closed", negId);
      }),
    );
  }

  function stop() {
    emit("scrcpy:webrtc:close", { udid });
    _cleanup();
  }

  function dispose() {
    disposers.forEach((off) => off && off());
    disposers.length = 0;
    stop();
  }

  bind();
  return { stream, running, error, start, stop, dispose, sendControl };
}
