# QwenPaw WeClawBot Bridge Channel Plugin

将 WeClawBot-Bridge 的微信消息接入 QwenPaw。

> 依赖项目：[WeClawBot-Bridge](https://github.com/gowfqk/WeClawBot-Bridge)

## 架构

```text
微信 → WeClawBot-Bridge → 本插件 (WebSocket) → QwenPaw
```

## 安装

```bash
# 1. 先停止正在运行的 QwenPaw 服务。
# 插件声明的 Python 依赖会由 QwenPaw 自动安装，无需手动 pip install。
qwenpaw plugin install /path/to/qwenpaw-weclawbot-channel

# 2. 启动 QwenPaw
qwenpaw app
```

也可以在 QwenPaw 停止时将插件复制到 plugins 目录，然后启动 QwenPaw：

```bash
cp -r qwenpaw-weclawbot-channel ~/.qwenpaw/plugins/
qwenpaw app
```

## 配置

### Bridge 端

在 Bridge 管理面板创建 Agent：

| 字段 | 值 |
|---|---|
| ID | `qwenpaw` |
| 名称 | QwenPaw |
| 命令 | `qwenpaw` |
| 类型 | **WS Remote** |
| 超时 | `180000` |

复制 Token。

### QwenPaw 端

插件安装后在 QwenPaw 控制台「频道管理」中添加 WeClawBot Bridge 频道，填写：

| 字段 | 说明 |
|---|---|
| WS Token | Bridge 生成的 Token |
| Bridge URL | 必填。`wss://<your-bridge-url>/ws/agent`（TLS）或 `ws://<bridge-host>:3000/ws/agent`（本地/未启用 TLS） |
| Agent ID | `qwenpaw`（可选） |

也可通过环境变量配置：

```bash
export WECLAWBOT_TOKEN=*** Token ***
# TLS 反向代理使用 wss://；本地或未启用 TLS 的 Bridge 使用 ws://
export WECLAWBOT_BRIDGE_URL=wss://<your-bridge-url>/ws/agent
export WECLAWBOT_AGENT_ID=qwenpaw
```

## 验证

QwenPaw 日志中查看：

```text
WeClawBot: authenticated as agent qwenpaw
```

微信发消息，确认 QwenPaw 回复。

## 切换 Agent

微信内发送：

```text
#hermes    → Hermes
#openclaw  → OpenClaw
#qwenpaw   → QwenPaw
```

## 故障排查

**插件未加载**

```bash
qwenpaw plugin list | grep weclawbot
```

**认证失败**

- 检查 Token 是否与 Bridge Agent 中生成的一致
- 确认 Agent ID 匹配
- 确认 Bridge 可达（协议需与 Bridge URL 匹配）：

```bash
# 本地或未启用 TLS 的 Bridge
curl -fsS http://<bridge-host>:3000/api/health

# 经 HTTPS/TLS 反向代理暴露的 Bridge
curl -fsS https://<your-bridge-url>/api/health
```
