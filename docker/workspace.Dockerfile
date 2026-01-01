# Workspace Container - 隔离的代码执行环境
# 每个workspace在独立容器中运行Claude CLI
#
# 注意：使用动态 UID/GID 映射，确保容器内外文件权限一致

FROM ubuntu:22.04

# 避免交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 安装基础开发工具 + gosu (用于动态切换用户) + sudo
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    ripgrep \
    jq \
    unzip \
    gosu \
    sudo \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 20.x (Claude CLI 需要 Node 18+)
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安装 Claude CLI (使用 npm)
RUN npm install -g @anthropic-ai/claude-code

# 创建 workspace 目录
RUN mkdir -p /workspace

# 入口脚本 - 动态创建用户并切换
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

# 环境变量 - 默认 UID/GID，可在运行时覆盖
ENV USER_UID=1000
ENV USER_GID=1000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
