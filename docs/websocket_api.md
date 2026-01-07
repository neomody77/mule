# Mule WebSocket API 文档

## 连接

```
ws://<host>:<port>/ws?token=<api_token>
```

## 消息格式

所有消息都是 JSON 格式，包含 `type` 字段表示消息类型。

---

## 客户端 → 服务器

### 基础消息

#### 订阅会话
```json
{
  "type": "subscribe",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 取消订阅
```json
{
  "type": "unsubscribe",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 发送 Prompt
```json
{
  "type": "prompt",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "content": "帮我写一个 Hello World",
  "image": {
    "data": "base64-encoded-image-data",
    "media_type": "image/png"
  }
}
```

#### 取消任务
```json
{
  "type": "cancel",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 同步状态
```json
{
  "type": "sync",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 压缩上下文
```json
{
  "type": "compact",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 心跳
```json
{"type": "ping"}
```

---

### 权限相关 (ACP/ACP_SANDBOX 模式)

#### 响应权限请求
```json
{
  "type": "permission_response",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "tool_use_id": "tool-use-id",
  "decision": "approved",
  "updated_input": {}
}
```

**decision 选项:**
| 值 | 说明 |
|---|---|
| `approved` | 单次批准 |
| `approved_for_session` | 会话期间自动批准同类操作 |
| `denied` | 拒绝此操作 |
| `abort` | 中止整个任务 |

#### 获取待处理权限
```json
{
  "type": "get_pending_permissions",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

---

### 模式切换 (ACP/ACP_SANDBOX 模式)

#### 切换控制模式
```json
{
  "type": "switch_mode",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "mode": "local"
}
```

**mode 选项:**
| 值 | 说明 |
|---|---|
| `local` | 本地控制（终端） |
| `remote` | 远程控制（手机/Web） |

#### 获取当前模式
```json
{
  "type": "get_mode",
  "workspace_id": "default",
  "session_id": "uuid-session-id"
}
```

#### 请求控制权交接
```json
{
  "type": "request_handoff",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "to_mode": "local"
}
```

---

## 服务器 → 客户端

### 基础事件

#### 订阅成功
```json
{
  "event": "subscribed",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "workspace_id": "default",
    "session_id": "uuid-session-id"
  }
}
```

#### 文本输出 (流式)
```json
{
  "event": "text_delta",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "text": "这是 AI 的回复..."
  }
}
```

#### 工具调用开始
```json
{
  "event": "tool_use_start",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "id": "tool-use-id",
    "name": "Bash",
    "input": {"command": "ls -la"},
    "description": "Running: ls -la"
  }
}
```

#### 工具调用结果
```json
{
  "event": "tool_result",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "id": "tool-use-id",
    "content": "total 0\ndrwxr-xr-x ...",
    "is_error": false
  }
}
```

#### 消息结束
```json
{
  "event": "message_end",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "session_id": "claude-session-id",
    "is_error": false,
    "result": "",
    "duration_ms": 1234,
    "num_turns": 1,
    "total_cost_usd": 0.01
  }
}
```

#### 状态更新
```json
{
  "event": "status",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "type": "thinking",
    "message": "Thinking..."
  }
}
```

**status.type 选项:**
- `task_start` - 任务开始
- `thinking` - 思考中
- `compacting` - 压缩上下文中
- `compact_done` - 压缩完成
- `cancelled` - 任务已取消

#### 错误
```json
{
  "event": "error",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "message": "错误信息"
  }
}
```

---

### 权限事件 (ACP/ACP_SANDBOX 模式)

#### 权限请求
```json
{
  "event": "permission_request",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "tool_use_id": "tool-use-id",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /tmp/test"},
    "description": "Run command: rm -rf /tmp/test",
    "options": []
  }
}
```

#### 权限响应确认
```json
{
  "event": "permission_responded",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "tool_use_id": "tool-use-id",
    "decision": "approved"
  }
}
```

#### 待处理权限列表
```json
{
  "event": "pending_permissions",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "permissions": [
      {
        "tool_use_id": "...",
        "tool_name": "Bash",
        "tool_input": {...},
        "description": "..."
      }
    ]
  }
}
```

---

### 模式切换事件 (ACP/ACP_SANDBOX 模式)

#### 模式变化
```json
{
  "event": "mode_changed",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "mode": "local",
    "previous_mode": "remote",
    "reason": "user_request"
  }
}
```

**reason 选项:**
- `user_request` - 用户主动请求
- `timeout` - 超时自动切换
- `disconnect` - 连接断开
- `handoff` - 主动交接

#### 模式状态
```json
{
  "event": "mode_status",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "mode": "remote",
    "switched_at": 1234567890.123,
    "reason": "user_request",
    "previous_mode": null,
    "remote_connections": 1,
    "local_active": false
  }
}
```

#### 交接结果
```json
{
  "event": "handoff_result",
  "workspace_id": "default",
  "session_id": "uuid-session-id",
  "data": {
    "success": true,
    "current_mode": "local"
  }
}
```

---

## 典型流程

### 1. 基础使用流程

```
Client                              Server
  |                                    |
  |-- subscribe ------------------->   |
  |<-- subscribed ------------------   |
  |                                    |
  |-- prompt ---------------------->   |
  |<-- status (task_start) ---------   |
  |<-- status (thinking) -----------   |
  |<-- text_delta ------------------   |
  |<-- tool_use_start --------------   |
  |<-- tool_result -----------------   |
  |<-- text_delta ------------------   |
  |<-- message_end -----------------   |
  |                                    |
```

### 2. 权限审批流程 (ACP 模式)

```
Client                              Server                          Claude
  |                                    |                               |
  |-- prompt ---------------------->   |                               |
  |                                    |-- execute ----------------->  |
  |                                    |<-- permission_request ------  |
  |<-- permission_request ----------   |                               |
  |                                    |                               |
  |   (用户在手机上审批)                 |                               |
  |                                    |                               |
  |-- permission_response --------->   |                               |
  |                                    |-- respond ----------------->  |
  |<-- permission_responded --------   |                               |
  |                                    |<-- continue ----------------  |
  |<-- tool_result -----------------   |                               |
  |                                    |                               |
```

### 3. 模式切换流程

```
Client (手机)                       Server                     Client (终端)
  |                                    |                               |
  |-- switch_mode (local) --------->   |                               |
  |<-- mode_changed (local) --------   |-- mode_changed ----------->   |
  |                                    |                               |
  |   (控制权转移到终端)                 |                               |
  |                                    |                               |
  |                                    |<-- prompt -----------------   |
  |<-- text_delta ------------------   |-- text_delta ------------>    |
  |                                    |                               |
```

---

## Agent 后端配置

在 `.env` 文件中配置:

```bash
# 可选值: claude, sandbox, adk, acp, acp_sandbox
AGENT_BACKEND=acp_sandbox

# ACP 权限模式 (仅 acp/acp_sandbox)
ACP_PERMISSION_MODE=remote
```

| 后端 | 权限审批 | Docker隔离 | 模式切换 |
|------|---------|-----------|---------|
| `claude` | ❌ | ❌ | ❌ |
| `sandbox` | ❌ | ✅ | ❌ |
| `adk` | ❌ | ❌ | ❌ |
| `acp` | ✅ | ❌ | ✅ |
| `acp_sandbox` | ✅ | ✅ | ✅ |
