# Mule

移动端远程编码平台 - 通过手机/iPad 连接服务器使用 Claude Agent 进行代码操作

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

### Docker 隔离模式
```bash
AGENT_BACKEND=sandbox
# 需要先构建镜像: docker build -t mule-workspace:latest -f docker/Dockerfile.workspace .
```

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
