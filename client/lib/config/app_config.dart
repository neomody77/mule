/// 认证模式
enum AuthMode { token, clerk }

/// 应用配置
class AppConfig {
  /// 服务器主机地址
  /// Android 模拟器使用 10.0.2.2，真机使用内网 IP
  static String serverHost = '192.168.71.51';

  /// 服务器端口
  static int serverPort = 8000;

  /// 是否使用 HTTPS/WSS
  static bool useSecure = false;

  /// API Token（Token 模式使用）
  static String apiToken = 'test-token-123';

  // ==================== Clerk 配置 ====================

  /// 认证模式: token（默认）或 clerk
  static AuthMode authMode = AuthMode.token;

  /// Clerk Publishable Key（从 Clerk Dashboard 获取）
  /// 仅当 authMode = clerk 时需要配置
  static String? clerkPublishableKey;

  /// 是否使用 Clerk 认证
  static bool get useClerkAuth => authMode == AuthMode.clerk;

  // ==================== URL 生成 ====================

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
    AuthMode? authMode,
    String? clerkPublishableKey,
  }) {
    if (host != null) AppConfig.serverHost = host;
    if (port != null) AppConfig.serverPort = port;
    if (secure != null) AppConfig.useSecure = secure;
    if (token != null) AppConfig.apiToken = token;
    if (authMode != null) AppConfig.authMode = authMode;
    if (clerkPublishableKey != null) {
      AppConfig.clerkPublishableKey = clerkPublishableKey;
    }
  }
}
