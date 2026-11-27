# uni-mobile-hub

统一的 **Android（Scrcpy） + iOS（WDA / go-ios）** Web 真机控制台与 AI 视觉自动化底座。

本项目基于优秀的开源项目 [`zhoujun94511/WebAppFlaskauto-iOS`](https://github.com/zhoujun94511/WebAppFlaskauto-iOS) 与 [`zhoujun94511/WebAppFlaskscrcpy`](https://github.com/zhoujun94511/WebAppFlaskscrcpy) 合并二开构建，目标是用一套统一的前后端控制台，同时纳管跨机器/跨系统的真机设备（例如 Mac 上的 iPhone 与 Windows/Linux 上的 Android）。

---

## 核心特性与设计目标

- **双端统一底座**：共用 Flask + Socket.IO + Vue 3 架构、统一用户鉴权、设备抢占锁（Reservations）与标准设备控制接口。
- **多机协同（Hub + Worker）**：支持单机直连，也支持通过节点接入将 Windows 上高速运行的 Scrcpy 安卓节点与 Mac 上的 iOS 节点聚合到同一个设备大厅。
- **双原生投屏引擎**：Android 保留原生 Scrcpy H.264/WebRTC 极速链路，iOS 保留 WDA MJPEG / WebRTC / HEVC 链路，不为了统一而牺牲帧率。
- **Termix 2.0 极简工作台**：提供 5 套内置主题与 0px 直角几何设计、可折叠/拖拽设备树侧栏、支持后台静默休眠/唤醒的多标签页、`1×2` / `2×2` 分屏与内联主从同步、单机真全屏、可折叠检查器停靠栏（Inspector Dock）、全局命令面板（`Cmd/Ctrl+K` 或双击左 `Shift`）以及 iOS DVT 实时内存与多任务切换弹窗。
- **AI Agent 友好**：面向纯视觉 Agent 提供统一设备列表、截图与归一化坐标（`0.0~1.0`）触控接口。

详细技术方案与模块划分见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，AI Agent API 手册见 [docs/AGENT_API.md](docs/AGENT_API.md)，部署与迁移指南见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)（上游原版 iOS 说明归档于 [docs/README_ios_upstream.md](docs/README_ios_upstream.md)）。

---

## 合并二开路线图

- [x] **Base**：以 `WebAppFlaskauto-iOS` 为底座建库，修复系统 HTTP 代理环境下回环 WDA / MJPEG 端口被误代理导致 `502` 的问题（`trust_env=False`）
- [x] **Phase 1**：抽象后端 `AdapterRegistry`（`IOSAdapter` + `AndroidAdapter` + 跨机 `RemoteNodeAdapter`）
- [x] **Phase 2**：前端 `DeviceScreen.vue` 双引擎播放器自动切换（Scrcpy WebRTC / iOS Stream）
- [x] **Phase 3**：面板差异化适配（`.apk`/`.ipa`、导航键、`logcat`/`syslog`）
- [x] **Phase 4**：跨平台群控同步（Sync）与统一 AI Agent HTTP API（`Bearer Token` + `/api/v1/agent/*`）
- [x] **Phase 5**：Scrcpy 同源 WebRTC 信令中继、跨端输入/旋转适配、`/api/nodes` 可观测性与 CI/Docker/常驻工程化
- [x] **Phase 6**：参考 `Termix-SSH/Termix` 的 UI/UX 2.0 工作台重构（5 套主题、0px 直角 UI、设备树侧栏、休眠/唤醒多标签、`1×2`/`2×2` 分屏与内联同步、全屏、检查器停靠栏、命令面板及 iOS DVT 实时内存/多任务管理）

### 工作台快捷键

| 快捷键 | 功能 |
| :--- | :--- |
| `Cmd/Ctrl + K` 或双击左 `Shift` | 打开全局命令面板（设备跳转 / 分屏 / 控屏 / 布局 / 主题） |
| `Cmd/Ctrl + B` | 折叠 / 展开左侧设备树侧栏 |
| `Cmd/Ctrl + I` | 折叠 / 展开右侧检查器停靠栏（文件 / 应用 / 日志） |
| `Esc` | 退出单机全屏模式 / 关闭命令面板 |

---

## 快速开始

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
