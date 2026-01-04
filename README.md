# Mule

Mobile remote coding platform - Access Claude Agent from your phone/iPad to perform code operations on a remote server.

[中文版](README_CN.md)

## Why Mule?

**Code while walking** — That's the motivation behind this project.

Most of the time, vibe coding just needs you to pull the AI back on track when it goes astray. The ideal scenario: give it a computer, let it work on its own, and just check in occasionally.

There was a similar community project [happy](https://github.com/slopus/happy), but it became incompatible after Claude Code updates. Fortunately, the official SDK was released, and this project was born.

**Mule** — A tool built with Claude Code, to squeeze more out of Claude Code.

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

- **Backend**: Deployed on Linux dev machine, FastAPI provides API and WebSocket
- **Client**: Flutter mobile app (also supports PWA via web)
- **Security Isolation**: Docker container isolates code execution environment
- **Tunnel**: Cloudflare Tunnel exposes the service

## Design Philosophy

Human interaction doesn't consume many resources — humans are the bottleneck. Heavy computation should be offloaded to the cloud/backend.

## Project Structure

```
mule/
├── app/                 # Python FastAPI server
│   ├── main.py         # Application entry
│   ├── config.py       # Configuration
│   ├── api/
│   │   ├── websocket.py    # WebSocket handling
│   │   ├── workspaces.py   # Workspace API
│   │   └── auth.py         # Authentication
│   └── services/
│       ├── claude_agent.py     # Claude Agent wrapper
│       ├── adk_agent.py        # Google ADK wrapper
│       ├── sandbox_agent.py    # Docker isolated execution
│       ├── task_manager.py     # Task queue management
│       ├── message_store.py    # Message persistence
│       └── workspace_manager.py
│
├── client/              # Flutter client
│   ├── lib/
│   │   ├── main.dart
│   │   ├── config/
│   │   ├── models/
│   │   ├── services/
│   │   ├── providers/      # Riverpod state management
│   │   ├── screens/
│   │   └── widgets/
│   └── pubspec.yaml
│
├── cli/                 # CLI tool
│   └── mule_cli/       # Terminal remote sync
│
└── docker/             # Docker configuration
    ├── Dockerfile.workspace
    └── entrypoint-workspace.sh
```

## Quick Start

### 1. Start the Server

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies (uv recommended)
uv pip install -e . --python .venv/bin/python

# Copy and configure environment variables
cp .env.example .env
# Edit .env to set:
# - ANTHROPIC_API_KEY: Claude API Key
# - API_TOKENS: Authentication tokens (comma-separated)
# - WORKSPACE_BASE_DIR: Workspace root directory

# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Flutter Client

```bash
cd client

# Install dependencies
flutter pub get

# Run (simulator or device)
flutter run

# Build web version
flutter build web

# Build Android APK
flutter build apk --release
```

### 3. Configure Connection

In the App settings page:
- **Server Host**: Server address (e.g., `192.168.1.100:8000`)
- **API Token**: Must match `API_TOKENS` in server's `.env`
- **Use HTTPS**: Recommended for production

## Features

- **Multi-workspace Management** - Isolate different projects
- **Real-time Streaming** - WebSocket bidirectional communication
- **Cross-device Session Sync** - Real-time sync of messages and state across clients
- **Code File Operations** - Read/write/search files
- **Shell Command Execution** - Run terminal commands
- **Session History** - Persistent message storage
- **Multiple Agent Backends**:
  - Claude Agent SDK (default)
  - Google ADK (Gemini)
  - Docker isolated execution

## Agent Backend Configuration

### Claude Agent (Default)
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

### Docker Isolation Mode (Linux)
```bash
AGENT_BACKEND=sandbox
# Build image first: docker build -t mule-workspace:latest -f docker/Dockerfile.workspace .
```

Docker isolation mode automatically uses the host's Claude login credentials on Linux:

**Authentication File Mounting Strategy:**
- `~/.claude/.credentials.json` → Read-only mount to container (OAuth token, auto-synced)
- `~/.claude.json` → Copied to container-specific directory (Claude needs write access)
- `~/.claude/` directory → Independent copy per container (avoids projects/ conflicts)

**Prerequisites:**
1. Host has logged in via `claude` command (`~/.claude/.credentials.json` exists)
2. Container runs as host user (handles file permissions automatically)

**How it works:**
```
Host                              Container
~/.claude/.credentials.json  →  /home/user/.claude/.credentials.json (read-only)
~/.claude.json               →  /home/user/.claude.json (copied)
data/containers/{id}/.claude →  /home/user/.claude/ (read-write)
workspaces/{id}              →  /workspace
```

This allows Claude Code in the container to use the host's login state without re-authentication.

**GitHub CLI Configuration (Optional):**
```bash
SHARE_GH_CONFIG=true
```
When enabled, mounts the host's `~/.config/gh/` directory read-only to the container, allowing `gh` commands for GitHub operations (create PRs, manage issues, etc.). Requires `gh auth login` on the host first.

## WebSocket Protocol

Unified endpoint: `/ws`

### Client Events
- `subscribe` - Subscribe to session
- `unsubscribe` - Unsubscribe
- `prompt` - Send prompt (queued if task running)
- `sync` - Sync current state
- `cancel` - Cancel running task

### Server Events
- `subscribed` - Subscription successful
- `task_started` / `task_completed` / `task_failed`
- `content` / `tool_use` / `tool_result` - Agent responses
- `user_message` - User message sync (cross-device)

## Security Notes

1. Always change default tokens in production
2. Configure HTTPS/WSS recommended
3. Workspace directory isolation prevents path traversal
4. Docker isolation mode provides additional security layer

## API Documentation

After starting the server, visit: `http://localhost:8000/docs`

## License

MIT
