/// 应用配置
class AppConfig {
  /// 服务器主机地址
  /// Android 模拟器使用 10.0.2.2，真机使用内网 IP
  static String serverHost = '192.168.71.51';

  /// 服务器端口
  static int serverPort = 8000;

  /// 是否使用 HTTPS/WSS
  static bool useSecure = false;

  /// API Token
  static String apiToken = 'test-token-123';

  /// 获取完整服务器地址 (host:port)
  static String get serverAddress => '$serverHost:$serverPort';

  /// 获取 HTTP 基础 URL
  static String get httpBaseUrl {
    final protocol = useSecure ? 'https' : 'http';
    return '$protocol://$serverAddress';
  }

  /// 获取 WebSocket 基础 URL
  static String get wsBaseUrl {
    final protocol = useSecure ? 'wss' : 'ws';
    return '$protocol://$serverAddress';
  }

  /// 获取 WebSocket URL (带认证)
  static String getWsUrl(String workspaceId) {
    return '$wsBaseUrl/ws/$workspaceId?token=$apiToken';
  }

  /// 更新配置
  static void update({
    String? host,
    int? port,
    bool? secure,
    String? token,
  }) {
    if (host != null) serverHost = host;
    if (port != null) serverPort = port;
    if (secure != null) useSecure = secure;
    if (token != null) apiToken = token;
  }
}
