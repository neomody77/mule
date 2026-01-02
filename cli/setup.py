#!/usr/bin/env python3
"""
Mule CLI 安装配置

安装方式:
    cd /Users/mira/playground/mule
    uv pip install -e cli/ --python .venv/bin/python
"""
from setuptools import setup

setup(
    name="mule-cli",
    version="0.1.0",
    description="Mule CLI - Claude Code 包装器，支持远程同步",
    author="Mule Team",
    packages=["cli"],
    package_dir={"cli": "."},
    python_requires=">=3.10",
    install_requires=[
        "claude-agent-sdk>=0.1.0",
        "websockets>=12.0",
    ],
    entry_points={
        "console_scripts": [
            "mule=cli.mule_cli:main",
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
