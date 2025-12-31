# Claude Code Remote

移动端远程编码平台 - 通过手机/iPad 连接服务器使用 Claude Agent 进行代码操作

## 项目结构

```
mule/
├── server/          # Python FastAPI 服务端
│   ├── app/
│   │   ├── main.py              # 应用入口
│   │   ├── config.py            # 配置管理
│   │   ├── api/
│   │   │   ├── websocket.py     # WebSocket 处理
│   │   │   ├── workspaces.py    # 工作区 API
│   │   │   └── auth.py          # 认证
│   │   └── services/
│   │       ├── claude_agent.py  # Claude Agent 封装
│   │       └── workspace_manager.py
│   ├── workspaces/              # 工作区存储目录
│   ├── requirements.txt
│   └── .env.example
│
└── mobile/          # Flutter 移动端
    ├── lib/
    │   ├── main.dart
    │   ├── config/
    │   ├── models/
    │   ├── services/
    │   ├── providers/
    │   ├── screens/
    │   └── widgets/
    └── pubspec.yaml
```

## 快速开始

### 1. 服务端启动

```bash
cd server

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 复制并配置环境变量
cp .env.example .env
# 编辑 .env 设置:
# - ANTHROPIC_API_KEY: 你的 Claude API Key
# - API_TOKEN: 访问认证 Token
# - WORKSPACE_BASE_DIR: 工作区根目录 (默认 ./workspaces)

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Flutter 移动端

```bash
cd mobile

# 安装依赖
flutter pub get

# 运行 (模拟器或真机)
flutter run

# 构建 iOS
flutter build ios

# 构建 Android
flutter build apk
```

### 3. 配置连接

在 App 设置页面配置:
- **Server Host**: 服务器地址 (如 `192.168.1.100:8000`)
- **API Token**: 与服务端 `.env` 中的 `API_TOKEN` 一致
- **Use HTTPS**: 生产环境建议开启

## 功能特性

- 多工作区管理
- 实时流式响应
- 代码文件操作 (读/写/搜索)
- Shell 命令执行
- 会话历史保存
- iPad 分屏优化 (计划中)

## 安全注意事项

1. 生产环境请务必修改默认 Token
2. 建议配置 HTTPS/WSS
3. 工作区目录隔离，防止路径逃逸
4. 命令执行有超时限制

## API 文档

启动服务后访问: `http://localhost:8000/docs`

## License

MIT
