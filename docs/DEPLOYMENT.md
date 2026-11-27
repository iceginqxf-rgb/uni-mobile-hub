# Deployment & Migration Guide

本指南覆盖 Docker 部署、macOS `launchd` 常驻、Windows Android Worker 配置，以及从旧版 `mobile-hub`（`portal.py` + `ios-console`）平滑迁移到单一 `uni-mobile-hub` 服务的方法。

---

## 1. Docker Compose（Linux / Android Hub 推荐）

```bash
cp .env.example .env
# 修改 SECRET_KEY、AGENT_API_TOKEN、ANDROID_ENABLED=1 等
docker compose up -d --build
```

- 镜像已内置多阶段前端构建、`android-tools-adb`、`usbmuxd`、`ffmpeg` 与自动数据库初始化。
- 使用 `network_mode: host` 以确保 WebRTC ICE 与 Scrcpy 局域网/Tailscale 端口可达。

---

## 2. macOS 常驻（替代旧 `portal.py` + `ios-console`）

1. 复制并修改模板：
   ```bash
   cp deploy/macos/com.unimobilehub.server.plist.example ~/Library/LaunchAgents/com.unimobilehub.server.plist
   ```
2. 将其中的 `/ABS/PATH/TO/...` 替换为本机虚拟环境与仓库实际绝对路径。
3. 在 `.env` 中配置：
   ```env
   PORT=5001
   OPEN_BROWSER=0
   IOS_ENABLED=1
   IOS_USE_GOIOS=1
   IOS_GOIOS_TUNNEL=1
   ANDROID_ENABLED=0
   REMOTE_NODES=[{"id":"win-worker","type":"scrcpy","url":"http://<WORKER_IP>:8002","username":"admin","password":"<PASSWORD>","ssh_host":"<SSH_HOST>"}]
   AGENT_API_TOKEN=<RANDOM_HEX_TOKEN>
   ```
4. 如果之前运行过旧双入口服务，停掉旧服务后加载新服务：
   ```bash
   launchctl load -w ~/Library/LaunchAgents/com.unimobilehub.server.plist
   ```

---

## 3. Windows Worker 部署（Android Scrcpy 节点）

- 如需继续复用现有 `WebAppFlaskscrcpy`（`8002` 端口），在 Hub `.env` 中设 `type: "scrcpy"` 即可；Hub 会自动通过同源 `/api/nodes` 与 Socket.IO 中继代理信令。
- 如需直接运行 `uni-mobile-hub` 作为 Worker，可执行：
  ```powershell
  powershell -ExecutionPolicy Bypass -File deploy\windows\start_worker.ps1.example
  ```

---

## 4. 节点监控与 CI

- `GET /api/nodes`：查看本地适配器与所有远端 Worker 状态（`online`、`latency_ms`、`device_count`）及实时推流 FPS。
- `POST /api/nodes/<node_id>/reconnect`：清除指数退避并立即触发远端节点重连。
- `.github/workflows/ci.yml`：每次 Push / PR 自动运行前端 `vite build` 与全量 `pytest`。
