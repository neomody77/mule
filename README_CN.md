# Mule

移动端远程编码平台 - 通过手机/iPad 连接服务器使用 Claude Agent 进行代码操作

[English](README.md)

## Why Mule?

**边散步边工作** —— 这是做这个项目的初衷。

大多数时候 vibe coding 只需要在跑偏时把 AI 拉回来就行。理想情况是：丢给它一台电脑让它自己折腾，时不时看一眼就好。

之前社区有个类似的项目 [happy](https://github.com/slopus/happy)，可惜 Claude Code 升级后不兼容了。好在后来官方出了 SDK，就有了这个项目。

**Mule（骡子）** —— 用 Claude Code 开发出来，压榨 Claude Code 的工具 😂

## Architecture

```
┌──────────────┐     Cloudflare      ┌──────────────────────────┐
│   Mobile     │ ◄── Tunnel ──────►  │   Linux Dev Machine      │
│   Client     │                     │  ┌────────────────────┐  │
│  (Flutter)   │                     │  │   Mule Backend     │  │
└──────────────┘                     │  │   (FastAPI)        │  │
                                     │  └─────────┬──────────┘  │
                                     │            │             │
                                     │  ┌─────────▼──────────┐  │
                                     │  │  Docker Sandbox    │  │
                                     │  │  (Claude Code)     │  │
                                     │  └────────────────────┘  │
                                     └──────────────────────────┘
```

- **后端**：部署在 Linux 开发机，FastAPI 提供 API 和 WebSocket
- **客户端**：Flutter 移动端（也支持 PWA，网页即可访问）
- **安全隔离**：Docker 容器隔离代码执行环境
- **内网穿透**：Cloudflare Tunnel 暴露服务

## Design Philosophy

与人交互的部分其实不占太多资源，相比之下人是低效的。大量的计算应该放到云端/后台去。

## 项目结构

```
mule/
├── app/                 # Python FastAPI 服务端
│   ├── main.py         # 应用入口
│   ├── config.py       # 配置管理
│   ├── api/
│   │   ├── websocket.py    # WebSocket 处理
│   │   ├── workspaces.py   # 工作区 API
│   │   └── auth.py         # 认证
│   └── services/
│       ├── claude_agent.py     # Claude Agent 封装
│       ├── adk_agent.py        # Google ADK 封装
│       ├── sandbox_agent.py    # Docker 隔离执行
│       ├── task_manager.py     # 任务队列管理
│       ├── message_store.py    # 消息持久化
│       └── workspace_manager.py
│
├── client/              # Flutter 客户端
│   ├── lib/
│   │   ├── main.dart
│   │   ├── config/
│   │   ├── models/
│   │   ├── services/
│   │   ├── providers/      # Riverpod 状态管理
│   │   ├── screens/
│   │   └── widgets/
│   └── pubspec.yaml
│
├── cli/                 # CLI 工具
│   └── mule_cli/       # 终端远程同步
│
└── docker/             # Docker 配置
    ├── Dockerfile.workspace
    └── entrypoint-workspace.sh
```

## 快速开始

### 1. 服务端启动

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖 (推荐使用 uv)
uv pip install -e . --python .venv/bin/python

# 复制并配置环境变量
cp .env.example .env
# 编辑 .env 设置:
# - ANTHROPIC_API_KEY: Claude API Key
# - API_TOKENS: 访问认证 Token (逗号分隔多个)
# - WORKSPACE_BASE_DIR: 工作区根目录

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Flutter 客户端

```bash
cd client

# 安装依赖
flutter pub get

# 运行 (模拟器或真机)
flutter run

# 构建 Web 版本
flutter build web

# 构建 Android APK
flutter build apk --release
```

### 3. 配置连接

在 App 设置页面配置:
- **Server Host**: 服务器地址 (如 `192.168.1.100:8000`)
- **API Token**: 与服务端 `.env` 中的 `API_TOKENS` 一致
- **Use HTTPS**: 生产环境建议开启

## 功能特性

- **多工作区管理** - 隔离不同项目
- **实时流式响应** - WebSocket 双向通信
- **跨设备会话同步** - 多客户端实时同步消息和状态
- **代码文件操作** - 读/写/搜索文件
- **Shell 命令执行** - 运行终端命令
- **会话历史保存** - 消息持久化存储
- **多 Agent 后端支持**:
  - Claude Agent SDK (默认)
  - Google ADK (Gemini)
  - Docker 隔离执行

## Agent 后端配置

### Claude Agent (默认)
```bash
AGENT_BACKEND=claude
ANTHROPIC_API_KEY=your_key
```

### Google ADK
```bash
AGENT_BACKEND=adk
GOOGLE_API_KEY=your_key
ADK_MODEL=gemini-2.0-flash
```

### Docker 隔离模式 (Linux)
```bash
AGENT_BACKEND=sandbox
# 需要先构建镜像: docker build -t mule-workspace:latest -f docker/Dockerfile.workspace .
```

Docker 隔离模式在 Linux 主机上会自动使用宿主机的 Claude 登录信息：

**认证文件挂载策略：**
- `~/.claude/.credentials.json` → 只读挂载到容器（OAuth token，自动同步更新）
- `~/.claude.json` → 复制到容器专属目录（Claude 需要写入）
- `~/.claude/` 目录 → 每个容器独立副本（避免 projects/ 冲突）

**前置条件：**
1. 宿主机已通过 `claude` 命令登录（存在 `~/.claude/.credentials.json`）
2. 容器以宿主机用户身份运行（自动处理文件权限）

**工作原理：**
```
宿主机                          容器
~/.claude/.credentials.json  →  /home/user/.claude/.credentials.json (只读)
~/.claude.json               →  /home/user/.claude.json (复制)
data/containers/{id}/.claude →  /home/user/.claude/ (可读写)
workspaces/{id}              →  /workspace
```

这样容器内的 Claude Code 可以直接使用宿主机的登录状态，无需在容器内重新登录。

**GitHub CLI 配置传递（可选）：**
```bash
SHARE_GH_CONFIG=true
```
启用后会将宿主机的 `~/.config/gh/` 目录只读挂载到容器，允许容器内使用 `gh` 命令操作 GitHub（创建 PR、管理 issues 等）。前提是宿主机已通过 `gh auth login` 登录。

## WebSocket 协议

统一端点: `/ws`

### 客户端事件
- `subscribe` - 订阅 session
- `unsubscribe` - 取消订阅
- `prompt` - 发送提示 (支持排队)
- `sync` - 同步当前状态
- `cancel` - 取消运行中的任务

### 服务端事件
- `subscribed` - 订阅成功
- `task_started` / `task_completed` / `task_failed`
- `content` / `tool_use` / `tool_result` - Agent 响应
- `user_message` - 用户消息同步 (跨设备)

## 安全注意事项

1. 生产环境请务必修改默认 Token
2. 建议配置 HTTPS/WSS
3. 工作区目录隔离，防止路径逃逸
4. Docker 隔离模式提供额外安全层

## API 文档

启动服务后访问: `http://localhost:8000/docs`

## License

MIT
