"""
加密工具 - 用于加密/解密连接信息

使用 AES-GCM 加密，URL-safe base64 编码
"""
import base64
import hashlib
import json
import os
import time
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _get_key() -> bytes:
    """从 secret 派生 256-bit 密钥"""
    return hashlib.sha256(settings.connect_secret.encode()).digest()


def encrypt_connect_info(
    host: str,
    port: int,
    token: str,
    name: str = "Mule Server",
    https: bool = False,
    ttl: int = 3600,  # 有效期，秒
) -> str:
    """
    加密连接信息

    Args:
        host: 服务器地址
        port: 端口
        token: API token
        name: 服务器名称
        https: 是否使用 HTTPS
        ttl: 有效期（秒），默认 1 小时

    Returns:
        加密后的 URL-safe base64 字符串
    """
    # 构建数据
    data = {
        "h": host,      # host
        "p": port,      # port
        "t": token,     # token
        "n": name,      # name
        "s": https,     # https
        "e": int(time.time()) + ttl,  # expire time
        "r": base64.b64encode(os.urandom(8)).decode(),  # random salt
    }

    # JSON 编码
    plaintext = json.dumps(data, separators=(',', ':')).encode()

    # 生成随机 nonce (96-bit for GCM)
    nonce = os.urandom(12)

    # AES-GCM 加密
    key = _get_key()
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    # 组合: nonce + ciphertext
    encrypted = nonce + ciphertext

    # URL-safe base64 编码
    return base64.urlsafe_b64encode(encrypted).decode().rstrip('=')


def decrypt_connect_info(encrypted: str) -> Optional[dict]:
    """
    解密连接信息

    Args:
        encrypted: 加密的 URL-safe base64 字符串

    Returns:
        解密后的连接信息 dict，如果失败或过期返回 None
    """
    try:
        # 补齐 base64 padding
        padding = 4 - len(encrypted) % 4
        if padding != 4:
            encrypted += '=' * padding

        # URL-safe base64 解码
        encrypted_bytes = base64.urlsafe_b64decode(encrypted)

        # 分离 nonce 和 ciphertext
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]

        # AES-GCM 解密
        key = _get_key()
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        # JSON 解码
        data = json.loads(plaintext.decode())

        # 检查是否过期
        if data.get("e", 0) < time.time():
            return None

        # 验证 token 是否有效
        if not settings.is_valid_token(data.get("t", "")):
            return None

        # 返回标准格式
        return {
            "host": data["h"],
            "port": data["p"],
            "token": data["t"],
            "name": data.get("n", "Mule Server"),
            "https": data.get("s", False),
        }

    except Exception:
        return None


def generate_connect_url(
    host: str,
    port: int,
    token: str,
    name: str = "Mule Server",
    https: bool = False,
    ttl: int = 86400,  # 默认 24 小时
) -> str:
    """
    生成带加密参数的连接 URL

    Returns:
        完整的连接 URL，如: http://host:port/?c=encrypted_data
    """
    encrypted = encrypt_connect_info(host, port, token, name, https, ttl)
    protocol = "https" if https else "http"
    return f"{protocol}://{host}:{port}/?c={encrypted}"
