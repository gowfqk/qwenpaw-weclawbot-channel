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
| Agent ID | 与 Bridge 面板中的 Agent 一致（默认 `qwenpaw`） |
| Agent Name | 可选。**留空则沿用 Bridge 面板配置**，仅在需要覆盖时填写 |
| Command Alias | 可选。**留空则沿用 Bridge 面板配置**，仅在需要覆盖时填写 |

> **名称 / 命令以 Bridge 面板为准。** 插件默认不再上报 `Agent Name` / `Command Alias`，
> 连接时不会改写你在 Bridge 面板里为该 Agent 配置的名称和切换命令。只有留空时想覆盖才填写。

也可通过环境变量配置：

```bash
export WECLAWBOT_TOKEN=*** Token ***
# TLS 反向代理使用 wss://；本地或未启用 TLS 的 Bridge 使用 ws://
export WECLAWBOT_BRIDGE_URL=wss://<your-bridge-url>/ws/agent
export WECLAWBOT_AGENT_ID=qwenpaw
```

### 接入多个 QwenPaw 实例

一个 Bridge 可以同时接入多个 QwenPaw 实例，供微信端切换。要点：

1. 在 Bridge 面板为每个实例创建独立的 WS Remote Agent，分配**不同的 `Agent ID`**（如 `qwenpaw-a`、`qwenpaw-b`），并各设一个**不同的切换命令**（如 `#qa`、`#qb`）。
2. 每个 QwenPaw 实例的插件里，`Agent ID` 填对应的 ID，`Token` 填对应的 Token；`Agent Name` / `Command Alias` **留空**，交给 Bridge 面板管理。
3. 微信端用各自的命令切换（如 `#qa` / `#qb`）。

> 若多个实例都用相同的 `Agent ID`，Bridge 会把先连接的踢下线（同一 ID 只允许一个活动连接），因此务必分配不同的 `Agent ID`。

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
