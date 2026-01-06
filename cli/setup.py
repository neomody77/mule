#!/usr/bin/env python3
"""
Mule CLI 安装配置

安装方式:
    cd /path/to/mule
    pip install -e cli/

功能:
    mule "prompt"           - 发送提示到 Mule 执行
    mule --interactive      - 交互模式
    mule handoff            - 将当前 Claude Code 会话接手到 Mule
    mule-handoff            - 独立的 handoff 命令
"""
from setuptools import setup

setup(
    name="mule-cli",
    version="0.2.0",
    description="Mule CLI - 通过后端 WebSocket 执行 Claude Agent，支持会话接手",
    author="Mule Team",
    packages=["cli"],
    package_dir={"cli": "."},
    python_requires=">=3.10",
    install_requires=[
        "websockets>=12.0",
        "httpx>=0.25.0",
    ],
    entry_points={
        "console_scripts": [
            "mule=cli.mule_cli:main",
            "mule-handoff=cli.handoff:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
