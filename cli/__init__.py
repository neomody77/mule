"""
Mule CLI - Claude Code 包装器

用法:
    mule "你的提示"
    mule --server ws://192.168.1.100:8989 "你的提示"

功能:
    - 使用 ClaudeSDKClient 执行任务
    - 实时同步到 Mule 服务器
    - 支持手机端查看进度和发送消息
    - 权限请求转发到移动端审批
"""

__version__ = "0.1.0"
