# uni-mobile-hub

统一的 **Android（Scrcpy） + iOS（WDA / go-ios）** Web 真机控制台与 AI 视觉自动化底座。

本项目基于优秀的开源项目 [`zhoujun94511/WebAppFlaskauto-iOS`](https://github.com/zhoujun94511/WebAppFlaskauto-iOS) 与 [`zhoujun94511/WebAppFlaskscrcpy`](https://github.com/zhoujun94511/WebAppFlaskscrcpy) 合并二开构建，目标是用一套统一的前后端控制台，同时纳管跨机器/跨系统的真机设备（例如 Mac 上的 iPhone 与 Windows/Linux 上的 Android）。

---

## 核心特性与设计目标

- **双端统一底座**：共用 Flask + Socket.IO + Vue 3 架构、统一用户鉴权、设备抢占锁（Reservations）与标准设备控制接口。
- **多机协同（Hub + Worker）**：支持单机直连，也支持通过节点接入将 Windows 上高速运行的 Scrcpy 安卓节点与 Mac 上的 iOS 节点聚合到同一个设备大厅。
- **双原生投屏引擎**：Android 保留原生 Scrcpy H.264/WebRTC 极速链路，iOS 保留 WDA MJPEG / WebRTC / HEVC 链路，不为了统一而牺牲帧率。
- **AI Agent 友好**：面向纯视觉 Agent 提供统一设备列表、截图与归一化坐标（`0.0~1.0`）触控接口。

详细技术方案与模块划分见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（上游原版 iOS 说明归档于 [docs/README_ios_upstream.md](docs/README_ios_upstream.md)）。

---

## 合并二开路线图

- [x] **Base**：以 `WebAppFlaskauto-iOS` 为底座建库，修复系统 HTTP 代理环境下回环 WDA / MJPEG 端口被误代理导致 `502` 的问题（`trust_env=False`）
- [ ] **Phase 1**：抽象后端 `AdapterRegistry`（`IOSAdapter` + `AndroidAdapter` + 跨机 `RemoteNodeAdapter`）
- [ ] **Phase 2**：前端 `DeviceScreen.vue` 双引擎播放器自动切换（Scrcpy WebRTC / iOS Stream）
- [ ] **Phase 3**：面板差异化适配（`.apk`/`.ipa`、导航键、`logcat`/`syslog`）
- [ ] **Phase 4**：跨平台群控同步（Sync）与统一 AI Agent HTTP API

---

## 快速开始（当前 Base：iOS 控制台可运行底座）

```bash
# 1. 创建虚拟环境并安装依赖（Python 3.12）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 构建前端
cd frontend && npm install && npm run build && cd ..

# 3. 配置环境变量与初始化数据库
cp .env.example .env
python scripts/init_db.py init

# 4. 启动服务
python app.py
```

> 说明：Windows 环境请参考 [docs/README_ios_upstream.md](docs/README_ios_upstream.md) 配置 `requirements.txt` 与 iOS WDA 签名。

---

## 致谢与协议

本项目采用 **MIT License** 开源（见 [LICENSE](LICENSE)），衷心感谢原作者 `zhoujun94511` 的以下两个开源项目提供的坚实基础：
- [WebAppFlaskauto-iOS](https://github.com/zhoujun94511/WebAppFlaskauto-iOS)
- [WebAppFlaskscrcpy](https://github.com/zhoujun94511/WebAppFlaskscrcpy)
