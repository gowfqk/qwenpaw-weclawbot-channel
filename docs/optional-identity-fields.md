# 插件不再强制上报 Agent 名称与命令

## 背景

本插件把微信消息经 [WeClawBot-Bridge](https://github.com/gowfqk/WeClawBot-Bridge) 接入 QwenPaw。它以 Bridge 的 **`ws-remote`** 方式工作：插件作为客户端主动连接 Bridge 的 `/ws/agent`，握手时发送一条 `auth` 消息：

```json
{ "type": "auth", "token": "...", "agentId": "qwenpaw",
  "name": "QwenPaw", "command": "qwenpaw", "description": "QwenPaw Channel Plugin" }
```

Bridge 收到握手后，会用其中的 `name` / `command` / `description` 去**注册/更新**这个 Agent。其中 `command` 是微信端切换 Agent 的命令（`#command`）。

在 `channel.py` 里，这几个字段来自频道配置，改动前带有硬编码兜底：

```python
self._agent_name = agent_name or "QwenPaw"
self._command = command or "qwenpaw"
```

也就是说，**只要操作者没填，插件就一定上报 `QwenPaw` / `qwenpaw`**。

## 直觉

设想你想在同一个 Bridge 上接两个 QwenPaw 实例，在 Bridge 面板分别配好：

| 实例 | Agent ID | 面板命令 |
|---|---|---|
| A | `qwenpaw-a` | `qa` |
| B | `qwenpaw-b` | `qb` |

但两个实例的插件都没填 `Command Alias`，于是握手都上报 `command="qwenpaw"`。Bridge 一旦以握手为准，就把 A、B 的命令都改成 `qwenpaw` —— 命令表冲突，第二个实例再也切不到。

修好这个问题需要「两端配合」：

- **Bridge 端**（姊妹 PR）：让面板配置成为权威，已存在的 Agent 连接时不被握手覆盖。
- **插件端**（本 PR）：不再强加 `QwenPaw` / `qwenpaw` 默认值。操作者留空时就发空字符串，把「叫什么名、用什么命令」交还给 Bridge 面板。

两者合起来形成双保险：即便面对未修复的旧 Bridge，插件也不会主动去污染别的实例的命令（最坏情况是回退到 `agentId`，而 `agentId` 本就要求各实例唯一）。

## 代码

**`channel.py`** —— 去掉硬编码兜底，未配置即为空：

```python
# 名称/命令是可选覆盖项；留空则交给 Bridge 面板，避免连接时改写他人配置。
self._agent_name = agent_name.strip() if agent_name else ""
self._command = command.strip() if command else ""
```

**`plugin.py`** —— 去掉 `Agent Name` / `Command Alias` 两个配置项的 `default`，占位提示改为「留空则沿用 Bridge 面板配置」。

**`README.md`** —— 新增「接入多个 QwenPaw 实例」小节，说明每个实例分配独立 `Agent ID`、名称/命令留空由面板管理。

**`tests/test_protocol_adapter.py`** —— 新增 `IdentityConfigTest`：未配置时 `_agent_name`/`_command` 为空；显式配置时原样保留。

## 验证

- `python3 -m py_compile channel.py plugin.py` → 通过。
- `python3 -m unittest discover -s tests -v` → **6 passed**（含新增 2 例）。

手动质量验收：

1. 只跑单实例：`Agent Name`/`Command Alias` 留空，确认 QwenPaw 日志出现 `authenticated as agent qwenpaw`，微信收发正常，切换命令仍是 Bridge 面板里配的那个。
2. 跑双实例：见 README「接入多个 QwenPaw 实例」，两实例分配不同 `Agent ID`、命令留空，微信端用各自命令切换互不干扰。

## 替代方案

| 方案 | 优点 | 缺点 |
|---|---|---|
| 仅改插件、不动 Bridge | 改动面小 | 治标不治本：旧 Bridge 的 `authenticate()` 仍会把空字段回填成 `agentId` 并覆盖面板配置。需配合 Bridge 端改动才能真正以面板为准 |
| 保留默认值，但要求操作者手动清空 | 无需改代码 | 依赖人不出错，多实例极易踩坑；默认值本身就是坑 |

## 建议与之交谈的人员

- **gowfqk / Zhang Deshuai**（`guowenqing43@gmail.com`）—— `channel.py`、`plugin.py` 的作者，熟悉握手字段与 Bridge 协议对接，适合确认「名称/命令默认留空」不会影响既有单实例部署。

## 测验

<details>
<summary>1. 改动前，操作者不填 Command Alias 时插件上报什么命令？</summary>

- **A. 空字符串** — 错。改动前有兜底。
- **B. `qwenpaw`（硬编码默认值）** — ✅ 正确：`self._command = command or "qwenpaw"`。
- **C. `agentId`** — 错。回退到 `agentId` 是 Bridge 端在字段为空时的行为，改动前插件根本不会发空值。
- **D. 报错** — 错。
</details>

<details>
<summary>2. 为什么这个问题必须「插件 + Bridge」两端一起改？</summary>

- **A. 插件无法发空字段** — 错。可以发空。
- **B. 即便插件发空，旧 Bridge 的 `authenticate()` 也会把空 `name`/`command` 回填为 `agentId` 并覆盖面板配置，因此必须 Bridge 端也让面板优先** — ✅ 正确。
- **C. Bridge 改完插件就不用动** — 不完整。插件仍会强加默认值，作为客户端最好也别污染，形成双保险。
- **D. 纯属重构** — 错。是修复多实例路由问题。
</details>

<details>
<summary>3. 多实例接入时，为什么每个实例必须用不同的 Agent ID？</summary>

- **A. Token 按名称区分** — 错。Token 按 `agentId` 管理。
- **B. Bridge 对同一 `agentId` 只允许一个活动连接，重复连接会把先连的踢下线** — ✅ 正确（见 `ws-agent-server.ts` 的「重复连接，踢掉旧连接」）。
- **C. QwenPaw 不支持相同名称** — 错。与 QwenPaw 无关。
- **D. 微信限制** — 错。
</details>

<details>
<summary>4. 改动后，显式填写了 Command Alias 会怎样？</summary>

- **A. 被忽略，一律留空** — 错。
- **B. 原样保留并上报（`command.strip()`），作为对面板配置的显式覆盖** — ✅ 正确。留空才交给面板。
- **C. 被改成 agentId** — 错。那是 Bridge 在收到空值时的回退。
- **D. 报错** — 错。
</details>

<details>
<summary>5. 单实例默认部署（agent_id 用默认 qwenpaw、命令留空）会不会因此坏掉？</summary>

- **A. 会，因为命令变空了** — 不准确。配合 Bridge 端「面板优先」，面板里该 Agent 的命令保持不变；即便是全新动态接入，Bridge 也会回退到 `agentId`（默认恰好是 `qwenpaw`）。
- **B. 不会：命令要么沿用面板配置，要么回退到 `agentId`（默认 `qwenpaw`），单实例行为不变** — ✅ 正确。
- **C. 会，认证失败** — 错。认证只看 token/agentId。
- **D. 会，插件无法启动** — 错。
</details>
