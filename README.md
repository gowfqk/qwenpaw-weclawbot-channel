# QwenPaw WeClawBot Bridge Channel Plugin

将 WeClawBot-Bridge 的微信消息接入 QwenPaw。

> 依赖项目：[WeClawBot-Bridge](https://github.com/gowfqk/WeClawBot-Bridge)

## 架构

```text
微信 → WeClawBot-Bridge → 本插件 (WebSocket) → QwenPaw
```

## 安装

```bash
# 1. 安装依赖
pip install websockets

# 2. 安装插件到 QwenPaw
qwenpaw plugin install /path/to/qwenpaw-weclawbot-channel

# 3. 重启 QwenPaw 使插件生效
```

或放入 QwenPaw 的 plugins 目录：

```bash
cp -r qwenpaw-weclawbot-channel ~/.qwenpaw/plugins/
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
| Bridge URL | `wss://<your-bridge-url>/ws/agent`（可选） |
| Agent ID | `qwenpaw`（可选） |

也可通过环境变量配置：

```bash
export WECLAWBOT_TOKEN=*** Token ***
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
- 确认 `<your-bridge-url>` 可达：

```bash
curl -sS https://<your-bridge-url>/api/health
```
