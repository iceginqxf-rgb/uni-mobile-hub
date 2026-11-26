import { ref } from "vue";
import { io } from "socket.io-client";

// Direct WebRTC client for remote Scrcpy worker nodes (bypasses the Hub for
// media when the browser can reach streamEndpoint.base_url directly). Falls back
// seamlessly via onFallback() when direct signaling/ICE cannot establish.
export function useScrcpyStream(udid) {
  const stream = ref(null);
  const running = ref(false);
  const error = ref("");

  let pc = null;
  let sock = null;
  let inputChannel = null;
  let devSize = { w: 1080, h: 2400 };
  let remoteId = udid;
  let negId = 0;

  function _cleanup() {
    negId += 1;
    if (pc) {
      try { pc.close(); } catch { /* ignore */ }
      pc = null;
    }
    if (sock) {
      try { sock.disconnect(); } catch { /* ignore */ }
      sock = null;
    }
    inputChannel = null;
    stream.value = null;
    running.value = false;
  }

  function _mapPoint(x, y, dw, dh) {
    if (!dw || !dh) return { x: Math.round(x), y: Math.round(y) };
    return {
      x: Math.round((x / dw) * devSize.w),
      y: Math.round((y / dh) * devSize.h),
    };
  }

  function sendControl(msg) {
    if (!inputChannel || inputChannel.readyState !== "open") return false;
    const t = msg?.type;
    if (t === "tap" || t === "doubletap") {
      const pt = _mapPoint(msg.x, msg.y, msg.display_width, msg.display_height);
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
    if (t === "swipe") {
      const p1 = _mapPoint(msg.x1, msg.y1, msg.display_width, msg.display_height);
      const p2 = _mapPoint(msg.x2, msg.y2, msg.display_width, msg.display_height);
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

  async function start(endpoint, onFallback, deviceGeometry) {
    error.value = "";
    _cleanup();
    if (deviceGeometry?.w && deviceGeometry?.h) {
      devSize = { w: deviceGeometry.w, h: deviceGeometry.h };
    }
    remoteId = endpoint?.remote_udid || udid;
    const baseUrl = (endpoint?.base_url || "").replace(/\/+$/, "");
    if (!baseUrl) {
      onFallback?.("missing endpoint base_url");
      return;
    }

    const myId = negId;
    const mySock = io(baseUrl, {
      transports: ["polling"],
      withCredentials: true,
      reconnectionAttempts: 2,
      timeout: 5000,
    });
    sock = mySock;

    const myPc = new RTCPeerConnection({ iceServers: [] });
    pc = myPc;
    inputChannel = myPc.createDataChannel("input");
    myPc.addTransceiver("video", { direction: "recvonly" });

    let fellBack = false;
    const fallback = (reason) => {
      if (fellBack || myId !== negId) return;
      fellBack = true;
      _cleanup();
      onFallback?.(reason);
    };

    myPc.ontrack = (ev) => {
      if (pc !== myPc) return;
      stream.value = ev.streams[0] || new MediaStream([ev.track]);
      running.value = true;
    };
    myPc.onicecandidate = (ev) => {
      if (pc !== myPc || !ev.candidate || sock !== mySock) return;
      mySock.emit("webrtc:ice", {
        device_id: remoteId,
        candidate: ev.candidate.candidate,
        sdpMid: ev.candidate.sdpMid,
        sdpMLineIndex: ev.candidate.sdpMLineIndex,
      });
    };
    myPc.onconnectionstatechange = () => {
      if (pc === myPc && ["failed", "disconnected", "closed"].includes(myPc.connectionState)) {
        running.value = false;
      }
    };

    mySock.on("connect_error", (err) => fallback(err?.message || "direct connect failed"));
    mySock.on("webrtc:closed", (d) => fallback(d?.reason || "closed"));
    mySock.on("webrtc:answer", async (d) => {
      if (!pc || pc !== myPc || (d?.device_id && d.device_id !== remoteId)) return;
      if (myPc.signalingState !== "have-local-offer") return;
      try {
        await myPc.setRemoteDescription({ sdp: d.sdp, type: d.type || "answer" });
      } catch (e) {
        fallback(e?.message || "setRemoteDescription failed");
      }
    });
    mySock.on("webrtc:ice", async (d) => {
      if (!pc || pc !== myPc || !d?.candidate || (d?.device_id && d.device_id !== remoteId)) return;
      try {
        await myPc.addIceCandidate({
          candidate: d.candidate,
          sdpMid: d.sdpMid,
          sdpMLineIndex: d.sdpMLineIndex,
        });
      } catch { /* ignore late ICE */ }
    });

    mySock.on("connect", async () => {
      if (myId !== negId || pc !== myPc) return;
      try {
        const offer = await myPc.createOffer();
        await myPc.setLocalDescription(offer);
        if (myId !== negId || pc !== myPc) return;
        mySock.emit("webrtc:offer", { device_id: remoteId, sdp: myPc.localDescription.sdp });
      } catch (e) {
        fallback(e?.message || "createOffer failed");
      }
    });
  }

  function stop() {
    if (sock) {
      try { sock.emit("webrtc:close", { device_id: remoteId }); } catch { /* ignore */ }
    }
    _cleanup();
  }

  function dispose() {
    stop();
  }

  return { stream, running, error, start, stop, dispose, sendControl };
}
