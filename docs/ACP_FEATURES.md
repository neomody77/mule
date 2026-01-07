# ACP 功能说明

本文档介绍 Mule 新增的 ACP (Agent Client Protocol) 功能，包括远程权限审批和本地/远程模式切换。

## 概述

ACP 功能让你可以：
1. **远程权限审批** - 在手机上批准或拒绝 AI 的操作请求
2. **本地/远程模式切换** - 在本地终端和远程客户端之间切换控制权
3. **会话级批准** - 批准某类操作后，同类操作自动通过

## 配置

### 启用 ACP

在 `.env` 文件中设置：

```bash
# 使用 ACP 协议（无 Docker 隔离）
AGENT_BACKEND=acp

# 或使用 ACP + Docker 沙箱（推荐）
AGENT_BACKEND=acp_sandbox
```

### 权限模式

```bash
# 远程审批（推荐）- 权限请求发送到手机/Web
ACP_PERMISSION_MODE=remote

# 跳过权限 - 自动允许所有操作
ACP_PERMISSION_MODE=bypass

# 本地交互 - 在终端中交互（不适用于远程场景）
ACP_PERMISSION_MODE=local
```

## 权限审批

### 权限请求流程

```
1. 用户发送 prompt
2. AI 执行任务
3. AI 需要执行敏感操作（如运行命令）
4. 服务器发送 permission_request 到客户端
5. 用户在手机上选择：批准/会话批准/拒绝/中止
6. 服务器将决策返回给 AI
7. AI 继续或停止执行
```

### 权限决策选项

| 决策 | 说明 |
|------|------|
| `approved` | 批准此次操作 |
| `approved_for_session` | 批准此次，且会话期间同类操作自动批准 |
| `denied` | 拒绝此次操作，AI 会尝试其他方法 |
| `abort` | 中止整个任务 |

### WebSocket 消息格式

**服务器 → 客户端 (权限请求)**
```json
{
  "event": "permission_request",
  "workspace_id": "default",
  "session_id": "xxx",
  "data": {
    "tool_use_id": "tool_xxx",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /tmp/test"},
    "description": "Run command: rm -rf /tmp/test"
  }
}
```

**客户端 → 服务器 (权限响应)**
```json
{
  "type": "permission_response",
  "workspace_id": "default",
  "session_id": "xxx",
  "tool_use_id": "tool_xxx",
  "decision": "approved"
}
```

## 模式切换

### 使用场景

- **远程模式 (remote)**: 通过手机/Web 控制 AI
- **本地模式 (local)**: 在电脑终端直接操作

### 切换流程

```
1. 用户在手机上点击"切换到本地"
2. 服务器发送 mode_changed 通知
3. 控制权转移到本地终端
4. 本地用户可以直接与 AI 交互
5. 本地用户完成后，可以切回远程模式
```

### WebSocket 消息格式

**切换模式**
```json
{
  "type": "switch_mode",
  "workspace_id": "default",
  "session_id": "xxx",
  "mode": "local"
}
```

**获取当前模式**
```json
{"type": "get_mode", "workspace_id": "default", "session_id": "xxx"}
```

**请求交接**
```json
{
  "type": "request_handoff",
  "workspace_id": "default",
  "session_id": "xxx",
  "to_mode": "local"
}
```

**模式变化通知**
```json
{
  "event": "mode_changed",
  "data": {
    "mode": "local",
    "previous_mode": "remote",
    "reason": "user_request"
  }
}
```

### 模式切换原因

| 原因 | 说明 |
|------|------|
| `user_request` | 用户主动请求 |
| `timeout` | 远程模式超时（默认10分钟无连接） |
| `disconnect` | 所有远程连接断开 |
| `handoff` | 控制权交接 |

## 测试工具

### 命令行测试客户端

```bash
# 安装依赖
pip install websockets

# 运行测试客户端
python scripts/test_acp_client.py --host localhost --port 8000 --token your-token
```

### 测试客户端命令

```
/subscribe [session_id]  - 订阅会话
/prompt <text>           - 发送 prompt
/approve [id]            - 批准权限请求
/approve_session [id]    - 会话级批准
/deny [id]               - 拒绝
/abort [id]              - 中止任务
/mode local|remote       - 切换模式
/status                  - 获取模式状态
/cancel                  - 取消当前任务
/quit                    - 退出
```

### 测试示例

```
> /subscribe test-session
[*] Subscribed to session: test-session

> /prompt 列出当前目录的文件

[12:00:01] [STATUS] task_start: Starting...
[12:00:02] [STATUS] thinking: Thinking...
[12:00:03] [TOOL] Bash: Running: ls -la

[12:00:03] [!] PERMISSION REQUEST
    Tool: Bash
    Description: Running: ls -la
    ID: tool_xxx
    Commands: /approve, /approve_session, /deny, /abort

> /approve
[12:00:05] [+] Permission tool_xxx: approved
[12:00:05] [RESULT] [OK] total 8...
[12:00:06] [AI] 当前目录包含以下文件：
...
[12:00:07] [END] Done

> /mode local
[12:00:10] [MODE] Changed: remote -> local (user_request)
```

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户交互层                                   │
├───────────────────────┬─────────────────────────────────────────┤
│    Flutter App        │           Web PWA                       │
│    (手机)             │           (浏览器)                       │
└───────────┬───────────┴─────────────────┬───────────────────────┘
            │                             │
            │         WebSocket           │
            ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Server                                │
├─────────────────────────────────────────────────────────────────┤
│  WebSocket Handler                                               │
│  ├── permission_response  → 权限适配器                           │
│  ├── switch_mode          → 模式管理器                           │
│  └── prompt               → 任务管理器                           │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ACP Agent / ACP Sandbox Agent                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ ACP Transport   │  │ Permission      │  │ Mode Manager    │  │
│  │ (JSON-RPC)      │  │ Adapter         │  │                 │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │           │
└───────────┼────────────────────┼────────────────────┼───────────┘
            │                    │                    │
            ▼                    │                    │
┌─────────────────────┐          │                    │
│   Claude Code       │          │                    │
│   (子进程/容器)      │ ◄────────┘                    │
└─────────────────────┘                               │
                                                      │
┌─────────────────────────────────────────────────────┘
│
│  模式状态广播到所有客户端
│
▼
┌─────────────────────────────────────────────────────────────────┐
│  所有订阅该会话的客户端都会收到模式变化通知                         │
└─────────────────────────────────────────────────────────────────┘
```

## 与其他 Agent 后端对比

| 功能 | claude | sandbox | adk | acp | acp_sandbox |
|------|--------|---------|-----|-----|-------------|
| 远程权限审批 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 会话级批准 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 本地/远程切换 | ❌ | ❌ | ❌ | ✅ | ✅ |
| Docker 隔离 | ❌ | ✅ | ❌ | ❌ | ✅ |
| OAuth 自动刷新 | ❌ | ✅ | - | ❌ | ✅ |
| 协议级控制 | ❌ | ❌ | ❌ | ✅ | ✅ |

## FAQ

### Q: 权限请求超时怎么办？
A: 默认超时时间为 5 分钟。超时后会使用默认行为（允许）。可以在 `PermissionAdapter` 中修改 `DEFAULT_TIMEOUT`。

### Q: 如何实现"永久批准某类操作"？
A: 目前支持"会话级批准"，会话结束后重置。如需永久设置，可以使用 `ACP_PERMISSION_MODE=bypass`。

### Q: 模式切换时任务会中断吗？
A: 不会。模式切换只影响控制权，不影响正在执行的任务。

### Q: 如何知道当前是谁在控制？
A: 使用 `get_mode` 消息获取当前模式状态，包括远程连接数和本地活跃状态。
