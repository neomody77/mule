#!/bin/bash
set -e

# Mule 部署脚本

# 检查 Flutter 是否安装
if ! command -v flutter &> /dev/null; then
    echo "Warning: Flutter not installed, skipping web build"
else
    echo "Building Flutter web..."
    cd client && flutter build web --release
    cd ..

    echo "Copying to static/..."
    rm -rf static/
    cp -r client/build/web static/
fi

# 同步依赖
echo "Syncing Python dependencies..."
uv sync

# 启动服务
echo "Starting server on port 8080..."
uv run python main.py
