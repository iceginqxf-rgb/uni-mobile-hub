# 架构设计与双端合并路线图（uni-mobile-hub）

本文档说明如何将 `zhoujun94511/WebAppFlaskauto-iOS`（iOS 底座）与 `zhoujun94511/WebAppFlaskscrcpy`（Android/Scrcpy 引擎）合并为一套统一的 **Android + iOS 云真机与 AI 视觉控制平台**，并原生支持 **Hub + Worker 跨机节点协同**（如 Mac Studio 接 iPhone + Windows 宿主机接多台 Android）。

---

## 一、核心拓扑（Hub + Worker 主从协同）

为了避免“经 Tailscale/LAN 远端代理 `adb` 再重编码 `scrcpy`”带来的延迟与画质损失，同一套代码可同时扮演两种角色：

```mermaid
flowchart LR
    Browser["浏览器 / AI Agent<br/>(统一大厅 & REST/WS)"] --> Hub["Hub 主控节点 (Mac / Linux)<br/>auth + reservations + UI"]
    Hub -->|"本地 USB (go-ios + WDA)"| iPhone["iPhone 真机"]
    Hub -->|"本地 USB (adb + scrcpy)"| LocalAndroid["本地直连 Android"]
    Hub -->|"Node API + 直连媒体流"| Worker["Worker 节点 (Windows / Linux)"]
    Worker -->|"本地 USB + rog-media-relay"| WinAndroid["Windows 挂载的 Android 群"]
```

- **单机模式**：在一台 Mac/Windows/Linux 上同时开启 `ANDROID_ENABLED=1` 与 `IOS_ENABLED=1`，USB 直连机器即可统一管理。
- **Hub + Worker 跨机模式**：
  - **Worker（如 Windows）** 开启 `ANDROID_ENABLED=1`、`NODE_TOKEN=...`，继续利用本地 `scrcpy` + `rog-media-relay.exe` 提供极低延迟 H.264/WebRTC 视频流；
  - **Hub（如 Mac）** 开启 `IOS_ENABLED=1` 并配置 `REMOTE_NODES`，在统一设备大厅中混排展示所有设备；控制请求与媒体信令直达设备所在节点。

---

## 二、七阶段演进架构（Phase 1–7）

### Phase 1：Backend Adapter Registry & 跨机节点聚合
- 在 `services/` 下抽象统一的 `DeviceAdapter` 接口（`discover` / `connect` / `disconnect` / `control` / `stream_info` / `screenshot` / `apps` / `files` / `logs`）。
- 保留现有 `IOSAdapter` 作为 iOS 引擎；新增：
  - `AndroidAdapter`：整合 `WebAppFlaskscrcpy` 的 `scrcpy/` 协议栈与 `adb` 服务；
  - `RemoteNodeAdapter`：拉取并代理远端 Worker 节点上的设备注册、抢占与控制。
- 设备对象统一携带 `platform`（`"android"` / `"ios"`）与 `node_id` 字段。

### Phase 2：前端双引擎视频播放器融合
- 外层统一共用 `DeviceStage.vue`（手机壳、分辨率/方向自适应、`0.0~1.0` 归一化触控坐标映射与防抖手势）。
- 内部 `DeviceScreen.vue` 根据 `device.platform` 动态挂载播放器：
  - `platform === "android"` -> `<AndroidScrcpyPlayer>`（WebRTC / MSE / `rog-media-relay` 低延迟 H.264 流）
  - `platform === "ios"` -> `<IosStreamPlayer>`（WebRTC / Socket.IO MJPEG / HEVC 帧流）

### Phase 3：面板能力差异化适配
- **公共能力**：账号鉴权、设备抢占锁、应用管理（`.apk` / `.ipa`）、文件浏览器、实时日志（`logcat` / `syslog`）。
- **平台特有导航与快捷操作**：
  - Android：返回、Home、多任务、电源、音量、ADBKeyBoard / 剪贴板粘贴输入；
  - iOS：Home、锁屏、AssistiveTouch、截图/WDA 会话重连。

### Phase 4：跨系统群控同步与 AI Agent 原生接口
- 移植 `WebAppFlaskscrcpy` 的群控同步（Sync），支持主控设备的点击/滑动按比例坐标（`0.0~1.0`）跨屏分发到选中设备（兼容 Android + iPhone 混控）。
- 提供标准化 Agent HTTP API（`/api/v1/agent/devices`、`/api/v1/agent/devices/:id/screenshot`、`/api/v1/agent/devices/:id/tap` 等），配合纯视觉自动化工作流直接驱动任意平台真机。

### Phase 5：同源信令中继、跨端输入适配与节点可观测性
- 新增 Scrcpy 同源 WebRTC 信令与 TURN `rtc-config` 中继（`nodes/scrcpy_webrtc_relay.py`、`socketio_handlers/webrtc_events.py`），跨 Tailscale/NAT 环境无需暴露 Worker 端口即可低延迟拉流。
- 统一双端指针/滚轮/缩放手势与方向坐标映射，补全 `GET /api/nodes`、`POST /api/nodes/<node_id>/reconnect` 可观测性接口，以及 CI、Docker Compose、macOS `launchd`、Windows Worker 部署模板。

### Phase 6：Termix 2.0 工作台与 iOS DVT 深化
- 前端重构为 `NavRail` + 可调整设备树侧栏 + 支持流休眠/唤醒的浏览器式多标签 + `1×2`/`2×2` 分屏工作区（带内联主从同步）+ 可折叠 `InspectorDock`（文件/应用/日志）+ 全局 `CommandPalette`（`Cmd/Ctrl+K` / 双击左 `Shift`），支持 5 套预设主题与 0px 直角几何、单机真全屏。
- 后端新增 `ios/dvt_metrics.py` 通过 in-process `pymobiledevice3` DVT `Sysmontap` 与 `DeviceInfo.proclist()` 提供 iOS 实时内存 telemetry 及 `/api/devices/<udid>/running-apps` 多任务切换弹窗，同时消除 STUN 超时与 DDI 重复挂载阻塞。

### Phase 7：节点可观测性、录屏回放、批量自动化与跨端交互增强
- **节点可观测性看板（`NodesPanel.vue` + `api/nodes_api.py`）**：实时汇总本地适配器与远端 Worker 在线状态、RTT 延迟、指数退避倒计时（`retry_in_sec`/`reconnectable`）、推流模式及活跃 FPS/观察者统计。
- **屏幕录制与跨端宏回放（`useScreenRecorder.js` + `services/replay_service.py` + `api/replay_api.py` + `ReplayPanel.vue`）**：支持浏览器端原生 `MediaRecorder` 录屏导出（WebM/MP4），以及按 `0.0~1.0` 归一化坐标录制点击/滑动/文本/按键并在单机/群控组/自定义多机上倍速循环回放（JSON 导入/导出）。
- **多设备批量编排器（`services/batch_service.py` + `api/batch_api.py` + `BatchPanel.vue`）**：支持并行/串行策略、失败自动重试与超时控制的跨机 `.apk`/`.ipa` 批量安装及多步 Agent 动作流编排与日志导出。
- **跨端交互增强（`useTransfers.js` + `useClipboardSync.js`）**：设备画面与 `FilesPanel` 支持拖放 `.apk`/`.ipa` 自动安装或任意文件上传，通过 XHR 提供统一队列实时进度条；支持 `Cmd/Ctrl+Shift+V/C` 快捷读写及 `Cmd/Ctrl+V` 自动推送/键入剪贴板。
