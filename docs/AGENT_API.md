# Unified AI Agent API (`/api/v1/agent/*`)

面向纯视觉 AI Agent 的跨系统（Android + iOS + Remote Worker）统一 HTTP 接口：支持静态 Bearer Token 无状态鉴权、按需自动抢占与连接设备，以及跨分辨率 `0.0 ~ 1.0` 归一化坐标。

## 1. 鉴权配置

在服务端 `.env` 中配置强随机密钥即可启用：

```env
AGENT_API_TOKEN=replace-with-random-secret
```

请求时任选其一传入请求头（当 `AGENT_API_TOKEN` 为空时静态 Token 鉴权禁用）：

```http
Authorization: Bearer <AGENT_API_TOKEN>
```

或：

```http
X-Agent-Token: <AGENT_API_TOKEN>
```

> 仍兼容常规登录 Cookie 会话，同一端点可在本地测试或远程 Agent 服务复用。

---

## 2. 核心端点一览

| 方法与路径 | 说明 |
| :--- | :--- |
| `GET /api/v1/agent/devices` | 发现并列出全部在线 Android / iOS / Worker 设备（含 `platform`、`node_id`、分辨率与连接状态） |
| `GET /api/v1/agent/devices/<udid>/screenshot` | 获取 JPEG 截图；默认返回 `image/jpeg` 二进制流（Header 含 `X-Device-Width` / `X-Device-Height`），传 `?format=json` 或用 `POST` 返回 JSON Base64 |
| `POST /api/v1/agent/devices/<udid>/tap` | 点击：支持归一化 `{"nx": 0.5, "ny": 0.5}`，或像素 `{"x": 540, "y": 1200}` |
| `POST /api/v1/agent/devices/<udid>/doubletap` | 双击：同上 |
| `POST /api/v1/agent/devices/<udid>/longpress` | 长按：`nx`/`ny`（或 `x`/`y`）+ 可选 `"duration": 0.8` |
| `POST /api/v1/agent/devices/<udid>/swipe` | 滑动：`{"nx1": 0.5, "ny1": 0.8, "nx2": 0.5, "ny2": 0.2, "duration": 0.3}`（亦支持 `x1,y1,x2,y2`） |
| `POST /api/v1/agent/devices/<udid>/text` | 输入文本：`{"text": "你好", "enter": false}` |
| `POST /api/v1/agent/devices/<udid>/key` | 按键/系统动作：`{"name": "home"}`（支持 `home`/`back`/`recent`/`lock`/`unlock`/`power`/`enter`/`backspace`/`tab`/`space`/`volumeup`/`volumedown`） |
| `GET /api/v1/agent/devices/<udid>/apps` | 列出已安装应用（`?system=1` 包含系统应用） |
| `POST /api/v1/agent/devices/<udid>/open_app` | 启动应用：`{"app": "com.tencent.mm"}`（兼容 `bundle_id` / `package` 字段） |
| `POST /api/v1/agent/devices/<udid>/close_app` | 结束应用：`{"app": "com.tencent.mm"}` |

---

## 3. Curl 调用示例

```bash
export HUB="http://127.0.0.1:5001"
export TOKEN="your-agent-token"

# 1. 列出全平台设备
curl -s -H "Authorization: Bearer $TOKEN" "$HUB/api/v1/agent/devices" | jq .

# 2. 抓取截图到 /tmp/screen.jpg
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HUB/api/v1/agent/devices/<UDID>/screenshot" -o /tmp/screen.jpg

# 3. 归一化中心点击（兼容任意 Android / iOS 分辨率）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"nx": 0.5, "ny": 0.5}' \
  "$HUB/api/v1/agent/devices/<UDID>/tap"

# 4. 输入并回车
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "uni-mobile-hub", "enter": true}' \
  "$HUB/api/v1/agent/devices/<UDID>/text"
```

---

## 4. `mobile-control` Skill 联动

当环境变量设置 `UNI_HUB_URL` 与 `UNI_HUB_TOKEN` 时，`mobile-control` Skill 中的 `mobile_ctl.py` 会自动经由 `/api/v1/agent/*` 统一操作本机及远程 Worker 上的全部 Android / iOS 设备；未设置时自动保持原有直连 ADB + iOS Console 模式。
