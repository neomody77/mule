#!/bin/bash
# 动态创建与宿主机相同 UID/GID 的用户
# 确保容器内创建的文件在宿主机上有正确的权限

set -e

USER_UID=${USER_UID:-1000}
USER_GID=${USER_GID:-1000}
USER_NAME="coder"

# 创建组（如果不存在）
if ! getent group $USER_GID > /dev/null 2>&1; then
    groupadd -g $USER_GID $USER_NAME
fi

# 创建用户（如果不存在）
if ! id -u $USER_NAME > /dev/null 2>&1; then
    useradd -u $USER_UID -g $USER_GID -m -s /bin/bash $USER_NAME
fi

# 配置 sudo 免密码
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USER_NAME
chmod 440 /etc/sudoers.d/$USER_NAME

# 确保 workspace 目录权限正确
chown $USER_UID:$USER_GID /workspace

# 创建用户的 .claude 目录（用于凭证）
mkdir -p /home/$USER_NAME/.claude
chown -R $USER_UID:$USER_GID /home/$USER_NAME

# 如果挂载了 Claude 凭证，设置正确权限
if [ -f /home/$USER_NAME/.claude/.credentials.json ]; then
    chmod 600 /home/$USER_NAME/.claude/.credentials.json
fi

# 设置 HOME 环境变量
export HOME=/home/$USER_NAME

# 使用 gosu 切换到指定用户执行命令
exec gosu $USER_NAME "$@"
