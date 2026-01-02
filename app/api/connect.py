"""
连接配置 API - 提供 QR Code 供移动端扫码连接
"""
import json
import socket
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.config import settings
from app.utils.crypto import encrypt_connect_info, decrypt_connect_info, generate_connect_url

router = APIRouter()


def get_local_ip() -> str:
    """获取本机局域网 IP"""
    try:
        # 创建一个 UDP socket 连接到外部地址来获取本机 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_connect_config(
    name: Optional[str] = None,
    host: Optional[str] = None,
    use_https: bool = False,
    token_index: int = 0,
) -> dict:
    """生成连接配置 JSON"""
    tokens = settings.token_list
    token = tokens[token_index] if token_index < len(tokens) else tokens[0]
    return {
        "name": name or f"Mule Server",
        "host": host or get_local_ip(),
        "port": settings.port,
        "token": token,
        "https": use_https,
    }


@router.get("/config")
async def get_connect_config(
    name: Optional[str] = Query(None, description="服务器名称"),
    host: Optional[str] = Query(None, description="自定义 host（默认自动检测局域网 IP）"),
    https: bool = Query(False, description="是否使用 HTTPS"),
):
    """
    获取连接配置 JSON

    移动端可以通过剪切板粘贴这个 JSON 来添加服务器
    """
    return generate_connect_config(name=name, host=host, use_https=https)


@router.get("/qrcode")
async def get_connect_qrcode(
    name: Optional[str] = Query(None, description="服务器名称"),
    host: Optional[str] = Query(None, description="自定义 host（默认自动检测局域网 IP）"),
    https: bool = Query(False, description="是否使用 HTTPS"),
    size: int = Query(300, description="QR Code 尺寸（像素）", ge=100, le=1000),
):
    """
    生成连接配置的 QR Code 图片

    移动端扫描此二维码即可添加服务器

    Returns:
        PNG 图片
    """
    try:
        import qrcode
        from qrcode.image.pure import PyPNGImage
    except ImportError:
        return Response(
            content="qrcode package not installed. Run: pip install qrcode[pil]",
            status_code=500,
            media_type="text/plain",
        )

    # 生成配置 JSON
    config = generate_connect_config(name=name, host=host, use_https=https)
    config_json = json.dumps(config, ensure_ascii=False)

    # 生成 QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(config_json)
    qr.make(fit=True)

    # 生成图片
    img = qr.make_image(fill_color="black", back_color="white")

    # 调整大小
    img = img.resize((size, size))

    # 转为 bytes
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache",
            "Content-Disposition": "inline; filename=mule-connect.png",
        },
    )


@router.get("/qrcode/html")
async def get_connect_qrcode_page(
    name: Optional[str] = Query(None, description="服务器名称"),
    host: Optional[str] = Query(None, description="自定义 host"),
    https: bool = Query(False, description="是否使用 HTTPS"),
):
    """
    返回一个包含 QR Code 的 HTML 页面

    方便在浏览器中打开并用手机扫描
    """
    config = generate_connect_config(name=name, host=host, use_https=https)
    config_json = json.dumps(config, indent=2, ensure_ascii=False)

    # 构建 QR Code 图片 URL
    qr_url = f"/api/connect/qrcode?size=300"
    if name:
        qr_url += f"&name={name}"
    if host:
        qr_url += f"&host={host}"
    if https:
        qr_url += "&https=true"

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connect to Mule Server</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0D2C06 0%, #1a4a0d 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 24px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 400px;
            width: 100%;
        }}
        h1 {{
            color: #0D2C06;
            font-size: 24px;
            margin-bottom: 8px;
        }}
        .subtitle {{
            color: #687C64;
            font-size: 14px;
            margin-bottom: 24px;
        }}
        .qr-container {{
            background: #F2F4F2;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .qr-container img {{
            border-radius: 8px;
        }}
        .config {{
            background: #f8f9f8;
            border-radius: 12px;
            padding: 16px;
            text-align: left;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px;
            color: #3A5435;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }}
        .config-label {{
            color: #96A493;
            font-size: 12px;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .copy-btn {{
            margin-top: 16px;
            padding: 12px 24px;
            background: #0D2C06;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .copy-btn:hover {{
            background: #0A2304;
        }}
        .copy-btn:active {{
            transform: scale(0.98);
        }}
        .instructions {{
            margin-top: 24px;
            padding-top: 24px;
            border-top: 1px solid #C4CCC3;
        }}
        .instructions h3 {{
            color: #3A5435;
            font-size: 14px;
            margin-bottom: 12px;
        }}
        .instructions ol {{
            text-align: left;
            color: #687C64;
            font-size: 13px;
            padding-left: 20px;
        }}
        .instructions li {{
            margin-bottom: 8px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Mule Server</h1>
        <p class="subtitle">Scan to connect your mobile device</p>

        <div class="qr-container">
            <img src="{qr_url}" alt="QR Code" width="260" height="260">
        </div>

        <div class="config-label">Connection Config</div>
        <div class="config" id="config">{config_json}</div>

        <button class="copy-btn" onclick="copyConfig()">Copy Config</button>

        <div class="instructions">
            <h3>How to connect</h3>
            <ol>
                <li>Open Mule app on your phone</li>
                <li>Go to Settings > Servers</li>
                <li>Tap "Scan" and scan this QR code</li>
                <li>Or tap "Paste" after copying the config</li>
            </ol>
        </div>
    </div>

    <script>
        function copyConfig() {{
            const config = document.getElementById('config').textContent;
            navigator.clipboard.writeText(config).then(() => {{
                const btn = document.querySelector('.copy-btn');
                btn.textContent = 'Copied!';
                setTimeout(() => btn.textContent = 'Copy Config', 2000);
            }});
        }}
    </script>
</body>
</html>
"""
    return Response(content=html, media_type="text/html")


@router.get("/url")
async def get_encrypted_url(
    name: Optional[str] = Query(None, description="服务器名称"),
    host: Optional[str] = Query(None, description="自定义 host（默认自动检测局域网 IP）"),
    https: bool = Query(False, description="是否使用 HTTPS"),
    token_index: int = Query(0, description="使用第几个 token（0-based）"),
    ttl: int = Query(86400, description="URL 有效期（秒），默认 24 小时"),
):
    """
    生成加密的连接 URL

    用户可以直接打开这个 URL 自动连接到服务器
    """
    tokens = settings.token_list
    token = tokens[token_index] if token_index < len(tokens) else tokens[0]
    actual_host = host or get_local_ip()

    url = generate_connect_url(
        host=actual_host,
        port=settings.port,
        token=token,
        name=name or "Mule Server",
        https=https,
        ttl=ttl,
    )

    return {
        "url": url,
        "expires_in": ttl,
    }


@router.get("/decrypt")
async def decrypt_url_param(
    c: str = Query(..., description="加密的连接参数"),
):
    """
    解密连接参数

    前端可以调用这个 API 来解密 URL 中的 c 参数
    """
    result = decrypt_connect_info(c)
    if result is None:
        return {"error": "Invalid or expired connection info"}

    return result


@router.get("/qrcode/url")
async def get_url_qrcode(
    name: Optional[str] = Query(None, description="服务器名称"),
    host: Optional[str] = Query(None, description="自定义 host"),
    https: bool = Query(False, description="是否使用 HTTPS"),
    token_index: int = Query(0, description="使用第几个 token"),
    ttl: int = Query(86400, description="URL 有效期（秒）"),
    size: int = Query(300, description="QR Code 尺寸", ge=100, le=1000),
):
    """
    生成加密 URL 的 QR Code

    扫描后可以直接在浏览器中打开并自动连接
    """
    try:
        import qrcode
    except ImportError:
        return Response(
            content="qrcode package not installed",
            status_code=500,
            media_type="text/plain",
        )

    tokens = settings.token_list
    token = tokens[token_index] if token_index < len(tokens) else tokens[0]
    actual_host = host or get_local_ip()

    url = generate_connect_url(
        host=actual_host,
        port=settings.port,
        token=token,
        name=name or "Mule Server",
        https=https,
        ttl=ttl,
    )

    # 生成 QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache",
            "Content-Disposition": "inline; filename=mule-connect-url.png",
        },
    )
